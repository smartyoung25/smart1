/**
 * KAASA SmartOS Mobile — data.js
 * 데이터 연동 레이어
 *
 * 역할:
 *  1. 기존 dashboard/modules/core.js의 apiFetch, WebSocket 패턴 재사용
 *  2. P1~P5 관수 Period 정의 및 현재 Period 판별
 *  3. Priva ET₀ 스케줄 API 연동 (/api/farms/{id}/irrigation/schedule/priva)
 *  4. AI 추천 API 연동 (/api/v2/recommend)
 *  5. 실시간 센서 WebSocket (/ws/farms/{id}/sensors)
 *  6. 농진청 표준 → KAASA 현장학습 → 내 농장 맞춤 3단계 폴백
 *
 * 사용법 (각 screen_*.html에서):
 *   <script src="../components/data.js"></script>
 *   KaasaData.init({ farmId:'farm_001', onSensor: cb, onPeriod: cb });
 */

const KaasaData = (() => {
  'use strict';

  // ── 내부 상태 ──────────────────────────────────────────────────────────────
  let _token   = sessionStorage.getItem('sf_token')   || '';
  let _apiBase = sessionStorage.getItem('sf_api')     ||
    (location.protocol !== 'file:' ? location.origin : 'http://localhost:8000');
  let _farmId  = sessionStorage.getItem('sf_farm_id') || 'farm_001';
  let _ws      = null;
  let _wsRetryDelay = 2000;
  let _wsTimer  = null;
  let _pingTimer = null;
  let _callbacks = {};
  let _latestEnv = {};
  let _latestPriva = null;
  let _periodCache = null;

  // ── P1~P6 관수 Period 정의 (Grodan/Priva 일일 WC·EC 곡선 기반) ──────────────
  /**
   * P1~P6은 하루 관수 Period입니다 (우선순위가 아님).
   * 선진 벤치마킹(Grodan 함수율 전략·Priva 일사적산): 6단계 일일 곡선
   *   P1 일출前 점검 → P2 첫관수(재포화) → P3 첫배액(≈400 J/cm²) →
   *   P4 정오 유지 → P5 오후 dry-down(조기종료) → P6 야간 dry-back(무관수 기본)
   * 트리거는 일사 적산(J/cm²) 우선, 시각은 폴백. 야간 dry-back은 생식/영양 조절 레버.
   *
   * 구조:
   *   adapter.period 1 → P1(일출前) + P2(첫관수) 로 분리
   *   adapter.period 2 → P3(오전)
   *   adapter.period 3 → P4(정오 고부하)
   *   adapter.period 4 → P5(오후~마감)
   */
  const PERIODS = [
    {
      id: 'P1', label: 'P1', name: '일출 前 점검',
      timeRange: '05:00~07:00',
      colorVar: '--p1-color', softVar: '--p1-soft',
      adapterPeriod: 1,          // irrigation_adapter period 번호
      privaPhase: null,          // Priva 페이즈 해당 없음 (준비 구간)
      icon: '🌅',
      radiationTrigger: '일사 적산 시작 前',
      description: '일출 前 — 야간 dry-back(10~20%) 결과 확인, EC/pH 기준값 점검, 첫 관수량 산정',
      targets: { drainPct: { min: 0, max: 0 }, ecDrain: { min: 3.5, max: 5.5 }, supply: 0, drybackPct: { min: 10, max: 20 } },
      steering: '야간 농축 EC 최고점 — 과다 시 P2 첫 관수량 상향으로 보정',
      alertRules: [
        { metric: 'dryback', min: 25, severity: 'warn', msg: '야간 dry-back 과다(>25%) — 첫 관수 앞당김 권장' }
      ]
    },
    {
      id: 'P2', label: 'P2', name: '첫 관수(재포화)',
      timeRange: '일출 후 2~3h',
      colorVar: '--p2-color', softVar: '--p2-soft',
      adapterPeriod: 1,
      privaPhase: 0,
      icon: '🌱',
      radiationTrigger: '일사 적산 ~100 J/cm² 또는 함수율 하한',
      description: '재포화·염류 세척 — 큰 급액(슬랩량 4~6%)으로 EC 낮추고 근권 리셋. 첫 배액 前',
      targets: { drainPct: { min: 0, max: 10 }, ecDrain: { min: 2.8, max: 4.0 }, supply: null },
      steering: '큰 급액 = EC↓·세척. 시작 시각이 빠를수록 영양생장(vegetative)',
      alertRules: [
        { metric: 'drainPct', max: 0, severity: 'info', msg: '첫 배액 전 — 함수율 회복 확인' }
      ]
    },
    {
      id: 'P3', label: 'P3', name: '오전 관수(첫 배액)',
      timeRange: '일출 후 4~5h',
      colorVar: '--p3-color', softVar: '--p3-soft',
      adapterPeriod: 2,
      privaPhase: 1,
      icon: '☀️',
      radiationTrigger: '일사 적산 ≈400 J/cm² (≈600 W/m²) — 첫 배액 개시',
      description: '일사 상승 대응 — 첫 배액 시작, 최고 일사대에서 배액 EC 최저로 유도(스트레스 방지)',
      targets: { drainPct: { min: 20, max: 30 }, ecDrain: { min: 3.0, max: 4.5 }, supply: null },
      steering: '최고 광량 = 배액 EC 최저. 흐린 날 EC 무리하게 낮추지 않음',
      alertRules: [
        { metric: 'vpd', max: 1.2, severity: 'warn',   msg: 'VPD 낮음 — 환기 강화 권장' },
        { metric: 'vpd', min: 2.0, severity: 'danger', msg: 'VPD 높음 — 증산 과다, 급액 증가' }
      ]
    },
    {
      id: 'P4', label: 'P4', name: '정오 고부하(유지)',
      timeRange: '12:00~15:00',
      colorVar: '--p4-color', softVar: '--p4-soft',
      adapterPeriod: 3,
      privaPhase: 2,
      icon: '🌞',
      radiationTrigger: '일사 피크 — 소량·빈번 급액(슬랩량 ~3%)',
      description: '최대 증산·고부하 — 함수율 64~65% 안정 유지, 배액률 20~30%(고EB 시 25~50% 세척). 12% 미만 시 즉시 추가 관수',
      targets: { drainPct: { min: 20, max: 35 }, ecDrain: { min: 3.0, max: 5.0 }, supply: null, leachMax: 50 },
      steering: '소량·빈번 급액으로 산소 확보(샷 사이 1.5~2% 함수율 변동)',
      alertRules: [
        { metric: 'drainPct', max: 12, severity: 'danger', msg: '⚠ P4 배액률 위험 — 즉시 추가 관수 필요' },
        { metric: 'ecDrain',  min: 5.0, severity: 'warn',  msg: '배액 EC 높음 — EC 낮추기 고려' }
      ]
    },
    {
      id: 'P5', label: 'P5', name: '오후 dry-down',
      timeRange: '15:00~일몰',
      colorVar: '--p5-color', softVar: '--p5-soft',
      adapterPeriod: 4,
      privaPhase: null,
      icon: '🌇',
      radiationTrigger: '조기 종료(early stop) — 일몰까지 2~5% dry-back 도달',
      description: '관수 조기 종료 — 일몰 전 2~5% dry-back으로 생식생장 유도, EC 상향 허용, 마지막 급액 확정',
      targets: { drainPct: { min: 0, max: 25 }, ecDrain: { min: 3.5, max: 5.5 }, supply: null, drybackPct: { min: 2, max: 5 } },
      steering: '조기 종료가 이를수록 생식생장(generative)·EC 상승',
      alertRules: [
        { metric: 'slabWt', min: null, max: null, msg: '마감 슬랩 무게·dry-back 목표 확인' }
      ]
    },
    {
      id: 'P6', label: 'P6', name: '야간 dry-back',
      timeRange: '일몰~05:00',
      colorVar: '--p6-color', softVar: '--p6-soft',
      adapterPeriod: null,       // 야간 — 무관수가 기본 (어댑터 매핑 없음)
      privaPhase: null,
      icon: '🌙',
      radiationTrigger: '무관수 기본 (일사 없음)',
      description: '야간 건조 — 함수율 10~20% dry-back으로 생식/영양 생장 조절·뿌리 산소화, 배액 0%·EC 상향. 야간 관수는 예외(과도 dry-back·고EC 억제 시에만)',
      targets: { drainPct: { min: 0, max: 0 }, ecDrain: { min: 3.5, max: 6.0 }, supply: 0, drybackPct: { min: 10, max: 20 } },
      steering: '큰 dry-back=생식, 작은 dry-back=영양. 3시간당 ~3% 감소가 기준',
      alertRules: [
        { metric: 'dryback', min: 25, severity: 'warn',   msg: '야간 dry-back 과다 — 영양작물·경량배지 시 야간 소량 관수 검토' },
        { metric: 'ecDrain', min: 6.0, severity: 'danger', msg: '야간 EC 과다 상승 — 새벽 관수량 상향 또는 야간 1회 관수' }
      ]
    }
  ];

  // ── 프리바 관수 시작 조건 모델 (한국네타핌 Priva 운용매뉴얼 3.17.1 기반) ──────
  // 시작 트리거 우선순위: ① 적산일사량(J/cm²)+배액 보정 → ② 증산물량 → ③ 휴지시간/수분/장력 폴백
  // 첫 관수가 분배되면 적산일사량은 0으로 리셋.
  const IRRIGATION_START = {
    priority: [
      { key: 'rad_sum',  name_ko: '적산일사량 + 배액 보정', desc: '측정 적산일사(J/cm²)가 한계 초과 시 시작. 배액률로 한계 보정, 첫 관수 후 0 리셋' },
      { key: 'transp',   name_ko: '증산물량(Transpiration sum)', desc: 'VPD·일사·환기 기반 증산 적산이 한계 초과 시 시작' },
      { key: 'interval', name_ko: '최대 휴지시간(Interval)', desc: '마지막 관수 후 경과시간 초과 시 폴백 시작' },
      { key: 'moisture', name_ko: '수분/장력(Moisture·Tensio)', desc: '함수율 하한 또는 수분장력 초과 시 시작' },
    ],
    // Period별 활성 시작 조건 (프리바 시작원인 표 대응)
    byPeriod: {
      P1: ['무관수 — 야간 dry-back 결과 확인', '첫 관수량 산정'],
      P2: ['적산일사 ~100 J/cm² 또는 수분 하한', '큰 급액으로 EC 세척(첫 배액 前)'],
      P3: ['적산일사 ≈400 J/cm² → 첫 배액 개시', '배액률 피드백 보정'],
      P4: ['최대 휴지시간', '증산물량(VPD·일사)', '함수율 하한'],
      P5: ['조기 종료(early stop) — 적산일사 감소', 'dry-back 2~5% 목표'],
      P6: ['무관수(야간 dry-back)', '예외: 과도 dry-back·고EC 시 1회'],
    }
  };
  function getStartConditions(periodId) { return IRRIGATION_START.byPeriod[periodId] || []; }

  // ── 프리바 관수 구조·처방 (운용매뉴얼 3.17.5~3.17.7) ──────────────────────────
  // 계층: 시작 프로그램 → 밸브 그룹 → 밸브. 각 처방(Recipe)에 목표 EC/pH 지정.
  const IRRIGATION_STRUCTURE = {
    hierarchy: ['시작 프로그램(Start program)', '밸브 그룹(Valve group)', '밸브(Valve)'],
    recipe: {
      name_ko: '처방(Recipe)',
      desc: '공급용수+비료의 목표값 — 급액 EC·pH를 처방별로 지정',
      targets: { ec_supply: { min: 2.5, max: 3.5, unit: 'dS/m' }, ph_supply: { min: 5.5, max: 6.5 } }
    },
    flowPreControl: {
      name_ko: '유량 사전제어(Flow pre-control)',
      desc: '여러 공급용수를 유량 비율(%)로 사전 혼합 — 처방별 공급용수 %를 설정'
    }
  };

  // ── 현재 Period 판별 ────────────────────────────────────────────────────────
  function getCurrentPeriod(now) {
    const d   = now || new Date();
    const h   = d.getHours();
    const min = d.getMinutes();
    const hm  = h + min / 60;

    // 야간(일몰~새벽) → P6 dry-back 구간 (일사 없음)
    if (hm >= 19 || hm < 5) return PERIODS[5]; // P6
    if (hm < 7)  return PERIODS[0]; // P1 (05:00~07:00 일출 前)
    if (hm < 10) return PERIODS[1]; // P2
    if (hm < 12) return PERIODS[2]; // P3
    if (hm < 15) return PERIODS[3]; // P4
    return PERIODS[4];              // P5 (15:00~19:00 일몰)
  }

  // ── 배액률 상태 판별 ────────────────────────────────────────────────────────
  function getDrainStatus(drainPct, period) {
    const t = period?.targets?.drainPct;
    if (!t || drainPct == null) return 'unknown';
    if (drainPct < 12) return 'danger';
    if (drainPct < t.min) return 'warn';
    if (drainPct > t.max) return 'warn';
    return 'ok';
  }

  // ── API 헬퍼 ───────────────────────────────────────────────────────────────
  const _inflight = new Map();
  async function apiFetch(path, opts = {}) {
    const isGet = !opts.method || opts.method.toUpperCase() === 'GET';
    let ctrl;
    if (isGet) {
      if (_inflight.has(path)) _inflight.get(path).abort();
      ctrl = new AbortController();
      _inflight.set(path, ctrl);
    }
    try {
      const res = await fetch(_apiBase + path, {
        signal: ctrl?.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(opts.headers || {}),
          ...(_token ? { Authorization: `Bearer ${_token}` } : {})
        },
        ...opts
      });
      if (isGet) _inflight.delete(path);
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status}: ${txt.slice(0, 120)}`);
      }
      return res.json();
    } catch (e) {
      if (isGet) _inflight.delete(path);
      if (e.name === 'AbortError') return null;
      throw e;
    }
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────
  function wsConnect() {
    if (_ws) { _ws.onclose = null; _ws.close(); }
    clearTimeout(_wsTimer);
    const url = `${_apiBase.replace(/^http/, 'ws')}/ws/farms/${_farmId}/sensors`;
    try { _ws = new WebSocket(url); } catch { _scheduleRetry(); return; }

    _ws.onopen = () => {
      _wsRetryDelay = 2000;
      _emit('wsStatus', 'connected');
      if (_pingTimer) clearInterval(_pingTimer);
      _pingTimer = setInterval(() => {
        if (_ws?.readyState === 1) _ws.send(JSON.stringify({ type: 'ping' }));
      }, 30_000);
    };
    _ws.onmessage = e => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'env') {
          _latestEnv = { ..._latestEnv, ...msg };
          _applyPeriodAlerts(_latestEnv);
          _emit('sensor', _latestEnv);
        }
        if (msg.type === 'ping') _ws.send(JSON.stringify({ type: 'pong' }));
      } catch { /* silent */ }
    };
    _ws.onerror   = () => {};
    _ws.onclose   = () => { _emit('wsStatus', 'reconnecting'); _scheduleRetry(); };
  }
  function _scheduleRetry() {
    _wsTimer = setTimeout(wsConnect, _wsRetryDelay);
    _wsRetryDelay = Math.min(_wsRetryDelay * 2, 30_000);
  }

  // ── Period 경보 적용 ────────────────────────────────────────────────────────
  function _applyPeriodAlerts(env) {
    const period = getCurrentPeriod();
    const alerts = [];
    for (const rule of period.alertRules) {
      const val = env[rule.metric];
      if (val == null) continue;
      if (rule.max != null && val < rule.max) alerts.push({ ...rule, value: val, period: period.id });
      if (rule.min != null && val > rule.min) alerts.push({ ...rule, value: val, period: period.id });
    }
    if (alerts.length) _emit('periodAlert', alerts);
  }

  // ── Priva ET₀ 스케줄 ───────────────────────────────────────────────────────
  async function loadPrivaSchedule({ growthStage = 'mid', plantSizePct = 100 } = {}) {
    try {
      const d = await apiFetch(
        `/api/farms/${_farmId}/irrigation/schedule/priva` +
        `?growth_stage=${growthStage}&plant_size_pct=${plantSizePct}`
      );
      if (!d) return null;
      _latestPriva = d;
      // Priva phases → P2~P4 매핑
      const mapped = _mapPrivaToperiods(d);
      _emit('priva', { raw: d, periods: mapped });
      return { raw: d, periods: mapped };
    } catch (e) {
      _emit('error', { source: 'priva', message: e.message });
      return null;
    }
  }

  function _mapPrivaToperiods(priva) {
    const phases = priva?.phases || [];
    return PERIODS.map(p => {
      const ph = p.privaPhase != null ? phases[p.privaPhase] : null;
      return {
        periodId: p.id,
        nMax:     ph?.n_max ?? null,
        supplyMl: ph?.supply_ml ?? null,
        drainTargetPct: ph?.drain_target_pct ?? p.targets?.drainPct?.min ?? null,
        startHHMM: ph?.start_hhmm ?? p.timeRange.split('~')[0],
        endHHMM:   ph?.end_hhmm   ?? p.timeRange.split('~')[1]
      };
    });
  }

  // ── AI 추천 (3단계 폴백) ────────────────────────────────────────────────────
  async function loadRecommend({ crop = '토마토', tier = 'semi_auto', areaMeter = 1000 } = {}) {
    try {
      // Layer 1: /api/v2/recommend (KAASA 현장학습모델)
      const body = {
        crop, tier, farm_id: _farmId, area_m2: areaMeter, horizon_days: 30,
        env: {
          temp_internal: _latestEnv.temp_internal ?? null,
          humidity_int:  _latestEnv.humidity_int  ?? null,
          co2_ppm:       _latestEnv.co2_ppm       ?? null,
          solar_rad:     _latestEnv.solar_rad      ?? null,
          ec_dsm:        _latestEnv.ec_dsm         ?? null,
          temp_external: _latestEnv.temp_external  ?? null
        }
      };
      const d = await apiFetch('/api/v2/recommend', {
        method: 'POST',
        body: JSON.stringify(body)
      });
      if (!d) return null;
      // 빈 추천 배열 → 농진청 표준 폴백 (env 전체 null 시 모델이 추천 생략)
      if (!d.recommendations || d.recommendations.length === 0) {
        console.warn('[KaasaData] recommend returned empty — using 농진청 fallback');
        const fallback = _rnghimStandard();
        fallback._modelLayer = '농진청표준';
        _emit('recommend', fallback);
        return fallback;
      }
      d._modelLayer = d.model_source || 'KAASA';
      _emit('recommend', d);
      return d;
    } catch (e) {
      // Layer 2: 농진청 표준 폴백 (정적 기준값 사용)
      console.warn('[KaasaData] recommend fallback to 농진청 standard:', e.message);
      const fallback = _rnghimStandard();
      fallback._modelLayer = '농진청표준';
      _emit('recommend', fallback);
      return fallback;
    }
  }

  // 농진청 표준 폴백값 (딸기 기준, 실제 crop_config.py 값 참조)
  function _rnghimStandard() {
    return {
      _modelLayer: '농진청표준',
      alerts: [],
      recommendations: [
        { action: 'irrigation', title_ko: '관수 기준값 확인', action_ko: '배액률 20~30% 유지 (농진청 표준)', confidence: 0.70, rank: 1, profit_delta: 0, revenue_delta: 0, cost_delta: 0, tier_action: 'suggest', canonical_changes: {} },
        { action: 'ec_check',   title_ko: 'EC·pH 점검',     action_ko: '급액 EC 2.5~3.5 dS/m 확인',         confidence: 0.65, rank: 2, profit_delta: 0, revenue_delta: 0, cost_delta: 0, tier_action: 'suggest', canonical_changes: {} }
      ]
    };
  }

  // ── 관수 실행 기록 (POST /irrigation) ─────────────────────────────────────
  async function submitIrrigation({ date, crop, periods, slabVolL, maxWtKg, minWtKg, sunsetWtKg }) {
    try {
      const d = await apiFetch(`/api/farms/${_farmId}/irrigation`, {
        method: 'POST',
        body: JSON.stringify({
          farm_id: _farmId, crop, date,
          periods, slab_vol_l: slabVolL,
          max_wt_kg: maxWtKg, min_wt_kg: minWtKg, sunset_wt_kg: sunsetWtKg
        })
      });
      _emit('irrigationSaved', d);
      return d;
    } catch (e) {
      _emit('error', { source: 'irrigation', message: e.message });
      throw e;
    }
  }

  // ── 관수 분석 조회 ──────────────────────────────────────────────────────────
  async function loadIrrigationAnalysis(days = 7) {
    return apiFetch(`/api/farms/${_farmId}/irrigation/analysis?days=${days}`);
  }

  // ── 환경 데이터 조회 (REST 폴백) ───────────────────────────────────────────
  async function loadEnvironment() {
    try {
      const d = await apiFetch(`/api/farms/${_farmId}/environment`);
      if (d) {
        _latestEnv = { ..._latestEnv, ...d };
        _emit('sensor', _latestEnv);
      }
      return d;
    } catch (e) {
      _emit('error', { source: 'environment', message: e.message });
      return null;
    }
  }

  // ── 이벤트 에미터 ──────────────────────────────────────────────────────────
  function _emit(event, data) {
    const fns = _callbacks[event] || [];
    fns.forEach(fn => { try { fn(data); } catch { /* silent */ } });
  }
  function on(event, fn) {
    _callbacks[event] = _callbacks[event] || [];
    _callbacks[event].push(fn);
  }
  function off(event, fn) {
    _callbacks[event] = (_callbacks[event] || []).filter(f => f !== fn);
  }

  // ── 공개 초기화 ────────────────────────────────────────────────────────────
  function init({ farmId, token, apiBase, onSensor, onPriva, onRecommend, onPeriod, onStatus, onAlert } = {}) {
    if (farmId)  { _farmId  = farmId;  sessionStorage.setItem('sf_farm_id', farmId); }
    if (token)   { _token   = token;   sessionStorage.setItem('sf_token', token); }
    if (apiBase) { _apiBase = apiBase; sessionStorage.setItem('sf_api', apiBase); }

    if (onSensor)    on('sensor',      onSensor);
    if (onPriva)     on('priva',       onPriva);
    if (onRecommend) on('recommend',   onRecommend);
    if (onPeriod)    on('periodAlert', onPeriod);
    if (onStatus)    on('wsStatus',    onStatus);
    if (onAlert)     on('periodAlert', onAlert);

    wsConnect();
    return KaasaData;
  }

  // ── 유틸 ───────────────────────────────────────────────────────────────────
  function fmt1(v, fallback = '—') { return v != null ? Number(v).toFixed(1) : fallback; }
  function fmt0(v, fallback = '—') { return v != null ? Math.round(v).toString() : fallback; }
  function fmtPct(v, fallback = '—') { return v != null ? `${Number(v).toFixed(1)}%` : fallback; }

  function getSensorValue(key) { return _latestEnv[key] ?? null; }
  function getLatestPriva() { return _latestPriva; }
  function getFarmId() { return _farmId; }
  function getApiBase() { return _apiBase; }

  // ── 전역 기능형 메뉴 드로어 (전 화면 ≡ 메뉴 활성화) ─────────────────────────
  const _NAV = [
    { g: '바로가기', items: [
      ['c3_home.html', '🏠', '통합 홈'],
      ['g1_home.html', '🌱', '온실 홈'],
      ['f1_field.html', '🌾', '노지 홈'],
      ['c12_joint.html', '🚚', '공동출하'],
    ]},
    { g: '온실', items: [
      ['g3_period.html', '💧', '관수·양액 (P1~P6)'],
      ['g2_env.html', '🌡️', '환경 제어'],
      ['g4_growth.html', '🌿', '생육·수확예측'],
      ['g5_disease.html', '🔬', '병해·품질'],
      ['g6_harvest.html', '📦', '수확·유통'],
    ]},
    { g: '노지', items: [
      ['f8_cluster.html', '🛰️', '클러스터 작황'],
      ['f4_soil.html', '💧', '토양수분·관개'],
      ['f3_weather.html', '🌦️', '기상·재해'],
      ['f2_gis.html', '🗺️', '필지 GIS'],
      ['f5_remote.html', '🛰️', '원격탐사'],
      ['f6_pest.html', '🐛', '병해충·방제'],
      ['f7_harvest.html', '🚜', '노지 수확'],
    ]},
    { g: '경영·시스템', items: [
      ['c20_cluster_admin.html', '🗺️', '다중농가 클러스터 관제'],
      ['c17_diagnosis.html', '🩺', '시스템 종합진단'],
      ['c16_equipment.html', '🔌', '시설 기자재'],
      ['c5_erp.html', '💰', '수익성 ERP'],
      ['c14_report.html', '📋', '월간 리포트'],
      ['c4_diagnosis.html', '📊', 'AI 진단'],
      ['c13_chat.html', '🤖', 'AI 비서'],
      ['c15_education.html', '🎓', '교육'],
    ]},
  ];
  function _drawerPrefix() {
    return location.pathname.includes('/screens/') ? '' : 'screens/';
  }
  function _buildDrawer() {
    if (document.getElementById('kaasaDrawer')) return;
    const pfx = _drawerPrefix();
    const farm = sessionStorage.getItem('sf_farm_id') || _farmId || 'farm_001';
    const ov = document.createElement('div'); ov.className = 'drawer-overlay'; ov.id = 'kaasaDrawerOv';
    const dr = document.createElement('aside'); dr.className = 'drawer'; dr.id = 'kaasaDrawer';
    dr.innerHTML =
      `<div class="drawer-head">
         <h2>KAASA SmartOS</h2>
         <p>농장 <b id="kdFarm">${farm}</b> · <span id="kdTier" style="padding:1px 7px;border-radius:6px;background:rgba(255,255,255,.18);font-weight:800;">등급 확인 중</span></p>
         <button class="drawer-close" onclick="KaasaData.closeMenu()" aria-label="닫기">✕</button>
       </div>
       <div style="padding:10px 12px 0;">
         <input id="kdSearch" placeholder="🔎 화면 검색…" style="width:100%;min-height:42px;padding:10px 12px;border:none;border-radius:10px;background:rgba(255,255,255,.12);color:#fff;font-size:14px;outline:none;"/>
       </div>
       <nav id="kdNav">${_NAV.map(s =>
          `<div class="drawer-group">${s.g}</div>` +
          s.items.map(([h,i,n]) => `<a href="${pfx}${h}" data-name="${n}"><span style="font-size:17px;">${i}</span> ${n}</a>`).join('')
        ).join('')}</nav>
       <div class="drawer-group">농장 전환</div>
       <div style="padding:0 16px;">
         <select id="kdFarmSel" style="width:100%;min-height:42px;border-radius:10px;padding:9px;background:rgba(255,255,255,.12);color:#fff;border:none;font-size:14px;">
           ${['farm_001','farm_002','farm_003','farm_004','farm_005'].map(f=>`<option value="${f}" ${f===farm?'selected':''}>${f}</option>`).join('')}
         </select>
       </div>
       <nav style="margin-top:6px;">
         <a href="${pfx}c1_setup.html"><span style="font-size:17px;">⚙️</span> 농장 세팅</a>
         <a href="${location.pathname.includes('/screens/')?'../index.html':'index.html'}"><span style="font-size:17px;">≡</span> 전체 메뉴</a>
         <a href="javascript:void(0)" onclick="KaasaData.logout()"><span style="font-size:17px;">🚪</span> 로그아웃</a>
       </nav>
       <div style="padding:14px 18px;font-size:10px;opacity:.5;">KAASA SmartOS · SFROP v2.0</div>`;
    document.body.appendChild(ov); document.body.appendChild(dr);
    ov.addEventListener('click', closeMenu);
    // 검색 필터
    dr.querySelector('#kdSearch').addEventListener('input', e => {
      const q = e.target.value.trim().toLowerCase();
      dr.querySelectorAll('#kdNav a').forEach(a => {
        const hit = a.dataset.name.toLowerCase().includes(q);
        a.style.display = hit ? '' : 'none';
      });
      dr.querySelectorAll('#kdNav .drawer-group').forEach(g => { g.style.display = q ? 'none' : ''; });
    });
    // 농장 전환
    dr.querySelector('#kdFarmSel').addEventListener('change', e => {
      sessionStorage.setItem('sf_farm_id', e.target.value);
      const u = new URL(location.href); u.searchParams.set('farm', e.target.value); location.href = u.toString();
    });
    // 등급 칩 (best-effort)
    _loadTierChip(farm);
  }
  async function _loadTierChip(farm) {
    const el = document.getElementById('kdTier');
    if (!_token) { if (el) el.textContent = '기본 등급'; return; }   // 토큰 없으면 조회 생략(401 방지)
    try {
      const r = await fetch(`${_apiBase}/api/farms/${farm}/billing/plan`, { headers: { Authorization: `Bearer ${_token}` } });
      if (!r.ok) return; const d = await r.json();
      if (el) el.textContent = (d.tier_name_ko || d.tier || '기본') + ' 등급';
    } catch (e) {}
  }
  function openMenu()  { _buildDrawer(); _loadTierChip(sessionStorage.getItem('sf_farm_id') || _farmId || 'farm_001'); document.getElementById('kaasaDrawerOv')?.classList.add('open'); document.getElementById('kaasaDrawer')?.classList.add('open'); }
  function closeMenu() { document.getElementById('kaasaDrawerOv')?.classList.remove('open'); document.getElementById('kaasaDrawer')?.classList.remove('open'); }
  function logout() { try { sessionStorage.removeItem('sf_token'); } catch(e){} location.href = _drawerPrefix() + 'c0_signup.html'; }
  function _bindMenuTab() {
    // 하단 5탭의 ≡ 메뉴 버튼을 드로어로 연결 (기존 navigator 이동 대체)
    document.querySelectorAll('.sf-bottom-nav .bnav-tab, .bnav-tab').forEach(btn => {
      if ((btn.textContent || '').includes('메뉴')) {
        btn.onclick = (e) => { e.preventDefault(); openMenu(); };
      }
    });
  }

  // 경영전략 교차연결 밴드 — 진단→성과→수익성→ROI→벤치마킹 (고립 화면 단절 해소)
  const _STRAT = [
    ['c17', 'c17_diagnosis.html', '🩺 진단'],
    ['c14', 'c14_report.html', '📋 성과'],
    ['c5',  'c5_erp.html', '💰 수익성'],
    ['c10', 'c10_roi.html', '📈 ROI'],
    ['c9',  'c9_benchmark.html', '🏆 벤치마킹'],
  ];
  function _renderStratBands() {
    document.querySelectorAll('.strat-band').forEach(el => {
      const cur = el.getAttribute('data-cur') || '';
      el.innerHTML = _STRAT.map(([k, href, label]) => {
        const active = k === cur;
        const st = active
          ? 'background:var(--green);color:#fff;border:1px solid var(--green);'
          : 'background:var(--panel);color:var(--text);border:1px solid var(--border);';
        return `<a href="${href}" style="flex:0 0 auto;padding:7px 12px;border-radius:18px;font-size:12px;font-weight:700;text-decoration:none;white-space:nowrap;${st}">${label}</a>`;
      }).join('');
    });
  }
  // ── 전역 오프라인/연결 감지 배너 (현장 통신 불안정 대응) ──────────────────
  function _ensureNetBanner() {
    if (document.getElementById('kaasaNetBar')) return document.getElementById('kaasaNetBar');
    const el = document.createElement('div'); el.id = 'kaasaNetBar';
    el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
    el.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:9999;transform:translateY(-100%);'
      + 'transition:transform .25s;padding:8px 14px;text-align:center;font-size:12.5px;font-weight:800;'
      + 'padding-top:calc(8px + env(safe-area-inset-top,0px));';
    document.body.appendChild(el); return el;
  }
  let _netHideTimer = null;
  function _setNet(online) {
    const el = _ensureNetBanner();
    if (_netHideTimer) { clearTimeout(_netHideTimer); _netHideTimer = null; }
    if (!online) {
      el.style.background = '#dc2626'; el.style.color = '#fff';
      el.textContent = '⚠ 오프라인 — 네트워크 연결이 끊겨 데이터가 갱신되지 않습니다';
      el.style.transform = 'translateY(0)';
    } else {
      el.style.background = '#1f9d55'; el.style.color = '#fff';
      el.textContent = '✓ 연결 복구됨';
      el.style.transform = 'translateY(0)';
      _netHideTimer = setTimeout(() => { el.style.transform = 'translateY(-100%)'; }, 1800);
    }
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('offline', () => _setNet(false));
    window.addEventListener('online',  () => _setNet(true));
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
      try {
        _buildDrawer(); _bindMenuTab(); _renderStratBands();
        if (navigator && navigator.onLine === false) _setNet(false);  // 진입 시 오프라인이면 즉시 표시
      } catch (e) {}
    });
  }

  // ── 공개 API ───────────────────────────────────────────────────────────────
  return {
    // 초기화
    init,
    // 이벤트
    on, off,
    // Period
    PERIODS, getCurrentPeriod, getDrainStatus,
    // 프리바 관수 시작 조건·구조
    IRRIGATION_START, getStartConditions, IRRIGATION_STRUCTURE,
    // 전역 메뉴 드로어
    openMenu, closeMenu, logout,
    // 데이터 로드
    loadPrivaSchedule, loadRecommend, loadEnvironment,
    submitIrrigation, loadIrrigationAnalysis,
    // 현재 센서
    getSensorValue, getLatestPriva, getFarmId, getApiBase,
    // 유틸
    fmt1, fmt0, fmtPct,
    // 내부 접근 (디버그용)
    _latestEnv: () => _latestEnv
  };
})();
