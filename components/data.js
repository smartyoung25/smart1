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

  // ── P1~P5 관수 Period 정의 ─────────────────────────────────────────────────
  /**
   * P1~P5는 하루 관수 Period입니다 (우선순위가 아님).
   * 기존 irrigation_adapter의 P1~P4(일출/오전/오후/일몰)를 5구간으로 확장.
   *
   * 구조:
   *   adapter.period 1 → P1(일출前) + P2(첫관수) 로 분리
   *   adapter.period 2 → P3(오전)
   *   adapter.period 3 → P4(정오 고부하)
   *   adapter.period 4 → P5(오후~마감)
   */
  const PERIODS = [
    {
      id: 'P1', label: 'P1', name: '관수 前 점검',
      timeRange: '05:00~07:00',
      colorVar: '--p1-color', softVar: '--p1-soft',
      adapterPeriod: 1,          // irrigation_adapter period 번호
      privaPhase: null,          // Priva 페이즈 해당 없음 (준비 구간)
      icon: '🌅',
      description: '일출 前 — 야간 배액 잔량 확인, EC/pH 기준값 점검, 첫 관수 준비',
      targets: { drainPct: null, ecDrain: null, supply: 0 },
      alertRules: [
        { metric: 'slabWt', min: null, max: null, msg: '새벽 슬랩 무게 확인 필요' }
      ]
    },
    {
      id: 'P2', label: 'P2', name: '첫 관수',
      timeRange: '07:00~10:00',
      colorVar: '--p2-color', softVar: '--p2-soft',
      adapterPeriod: 1,
      privaPhase: 0,
      icon: '🌱',
      description: '첫 급액 — 근권 활성화, 목표 배액률 20~30% 도달 확인',
      targets: { drainPct: { min: 20, max: 30 }, ecDrain: { min: 2.8, max: 4.0 }, supply: null },
      alertRules: [
        { metric: 'drainPct', max: 15, severity: 'danger', msg: '배액률 부족 — 급액량 증가 필요' },
        { metric: 'drainPct', min: 40, severity: 'warn',   msg: '배액률 과잉 — 급액량 감소 필요' }
      ]
    },
    {
      id: 'P3', label: 'P3', name: '오전 관수',
      timeRange: '10:00~12:00',
      colorVar: '--p3-color', softVar: '--p3-soft',
      adapterPeriod: 2,
      privaPhase: 1,
      icon: '☀️',
      description: '일사 상승 대응 — DLI 누적에 따른 급액량 조정, VPD 상승 모니터링',
      targets: { drainPct: { min: 20, max: 35 }, ecDrain: { min: 3.0, max: 4.5 }, supply: null },
      alertRules: [
        { metric: 'vpd', max: 1.2, severity: 'warn',   msg: 'VPD 낮음 — 환기 강화 권장' },
        { metric: 'vpd', min: 2.0, severity: 'danger', msg: 'VPD 높음 — 증산 과다, 급액 증가' }
      ]
    },
    {
      id: 'P4', label: 'P4', name: '정오 고부하',
      timeRange: '12:00~15:00',
      colorVar: '--p4-color', softVar: '--p4-soft',
      adapterPeriod: 3,
      privaPhase: 2,
      icon: '🌞',
      description: '최대 증산·고부하 급액 — 배액률 12% 미만 시 즉시 추가 관수',
      targets: { drainPct: { min: 20, max: 35 }, ecDrain: { min: 3.0, max: 5.0 }, supply: null },
      alertRules: [
        { metric: 'drainPct', max: 12, severity: 'danger', msg: '⚠ P4 배액률 위험 — 즉시 추가 관수 필요' },
        { metric: 'ecDrain',  min: 5.0, severity: 'warn',  msg: '배액 EC 높음 — EC 낮추기 고려' }
      ]
    },
    {
      id: 'P5', label: 'P5', name: '오후~마감',
      timeRange: '15:00~일몰',
      colorVar: '--p5-color', softVar: '--p5-soft',
      adapterPeriod: 4,
      privaPhase: null,
      icon: '🌇',
      description: '야간 준비 — EC 상향 조정, 마지막 급액 확정, 배액 완료 확인',
      targets: { drainPct: { min: 15, max: 25 }, ecDrain: { min: 3.5, max: 5.0 }, supply: null },
      alertRules: [
        { metric: 'slabWt', min: null, max: null, msg: '마감 슬랩 무게 기록 필요' }
      ]
    }
  ];

  // ── 현재 Period 판별 ────────────────────────────────────────────────────────
  function getCurrentPeriod(now) {
    const d   = now || new Date();
    const h   = d.getHours();
    const min = d.getMinutes();
    const hm  = h + min / 60;

    if (hm < 7)  return PERIODS[0]; // P1
    if (hm < 10) return PERIODS[1]; // P2
    if (hm < 12) return PERIODS[2]; // P3
    if (hm < 15) return PERIODS[3]; // P4
    return PERIODS[4];              // P5
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

  // ── 공개 API ───────────────────────────────────────────────────────────────
  return {
    // 초기화
    init,
    // 이벤트
    on, off,
    // Period
    PERIODS, getCurrentPeriod, getDrainStatus,
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
