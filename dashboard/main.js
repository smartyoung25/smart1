// ── 상태 ──────────────────────────────────────────────────────────────────────
let _token   = sessionStorage.getItem('sf_token') || '';
// 서버에서 서빙될 때 자동으로 현재 origin 사용 (file:// 인 경우 localhost:8000 폴백)
let _apiBase = sessionStorage.getItem('sf_api') ||
  (location.protocol !== 'file:' ? location.origin : 'http://localhost:8000');

// ── 빌링 상태 ──────────────────────────────────────────────────────────────────
let _myFarmId  = sessionStorage.getItem('sf_farm_id') || '';
let _myTier    = sessionStorage.getItem('sf_tier')    || 'basic';
let _planCache = null;   // GET /billing/plan 캐시
let _featCache = {};     // { section: [features] }
let _chatHistory = [];   // AI 채팅 대화 이력 [{ role, content }]
let _chatFarmId  = '';   // 현재 채팅 중인 농장 ID (변경 시 이력 초기화)

function _decodeJwt(token) {
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch { return {}; }
}

const $ = id => document.getElementById(id);

// 로그인 폼 API URL을 현재 origin으로 초기화 (sessionStorage 우선)
// nginx(:80)로 접속 시 → http://localhost, 직접(:8000)으로 접속 시 → http://localhost:8000
{ const _el = document.getElementById('login-api-url'); if (_el) _el.value = _apiBase; }

// ── 폼 결과 메시지 헬퍼 ────────────────────────────────────────────────────────
// _setResult('some-result-el-id', 'ok'|'err'|'warn', '메시지')
function _setResult(elId, status, msg) {
  const el = $(elId);
  if (!el) return;
  const cls = status === 'ok' ? 'result-ok' : status === 'err' ? 'result-err' : 'result-warn';
  el.innerHTML = `<span class="${cls}">${_esc(msg)}</span>`;
}

if (_token) {
  $('login-overlay').classList.add('hidden');
  $('login-api-url').value = _apiBase;
  // JWT에서 farm_id/tier 복원 (sessionStorage에 없는 경우 디코딩)
  if (!_myFarmId) {
    const claims = _decodeJwt(_token);
    _myFarmId = claims.farm_id || '';
    _myTier   = claims.tier    || 'basic';
  }
  refreshAll();
  if (_myFarmId) loadPlanBadge(_myFarmId);
  // URL 해시로 초기 섹션 자동 전환 (예: /#environ, /#growth)
  // showSection()이 _farmsData 미적재 시 자동 로드 처리하므로 300ms면 충분
  const _initHash = location.hash.slice(1);
  const _VALID_SECTIONS = ['dashboard','environ','control','irrigation','growth','market','energy','system'];
  if (_initHash && _VALID_SECTIONS.includes(_initHash)) {
    setTimeout(() => showSection(_initHash), 300);
  }
  // hashchange 이벤트로 브라우저 뒤로/앞으로 탐색 지원 (중복 등록 방지)
  if (!window._hashListenerRegistered) {
    window._hashListenerRegistered = true;
    window.addEventListener('hashchange', () => {
      const h = location.hash.slice(1);
      if (_VALID_SECTIONS.includes(h)) showSection(h);
    });
  }
}

// ── 인증 탭 전환 ─────────────────────────────────────────────────────────────
function switchAuthTab(tab) {
  ['login','reg'].forEach(t => {
    $(`tab-${t}`).classList.toggle('active', t === tab);
    $(`panel-${t}`).classList.toggle('active', t === tab);
  });
  // API URL 동기
  if (tab === 'reg') $('reg-api-url').value = $('login-api-url').value;
}

// ── 로그인 공통 후처리 ────────────────────────────────────────────────────────
function _applyAuthSuccess(data, username, api) {
  _token   = data.access_token;
  _apiBase = api;
  sessionStorage.setItem('sf_token', _token);
  sessionStorage.setItem('sf_api',   _apiBase);
  const claims = _decodeJwt(_token);
  _myFarmId = claims.farm_id || data.farm_id || '';
  _myTier   = data.tier || claims.tier || 'basic';
  sessionStorage.setItem('sf_farm_id', _myFarmId);
  sessionStorage.setItem('sf_tier',    _myTier);
  $('login-overlay').classList.add('hidden');
  $('logged-as').textContent = `👤 ${username}`;
  if (data.onboarding_required) {
    startOnboarding();
  } else {
    refreshAll();
    if (_myFarmId) loadPlanBadge(_myFarmId);
    // 로그인 후에도 URL 해시가 있으면 해당 섹션으로 이동
    // (세션 만료 후 재로그인 시 이전 섹션 복원)
    const _VALID = ['dashboard','environ','control','irrigation','growth','market','energy','system'];
    const h = location.hash.slice(1);
    if (h && _VALID.includes(h) && h !== 'dashboard') {
      setTimeout(() => showSection(h), 400);
    }
    // hashchange 이벤트 리스너 등록 (최초 로그인 시 미등록 방지)
    if (!window._hashListenerRegistered) {
      window._hashListenerRegistered = true;
      window.addEventListener('hashchange', () => {
        const hh = location.hash.slice(1);
        if (_VALID.includes(hh)) showSection(hh);
      });
    }
  }
}

// ── 로그인 ────────────────────────────────────────────────────────────────────
async function doLogin() {
  const btn = $('btn-login'), errEl = $('login-err');
  errEl.textContent = '';
  btn.disabled = true; btn.textContent = '로그인 중…';
  const api  = $('login-api-url').value.replace(/\/$/, '');
  const user = $('in-user').value.trim();
  const pass = $('in-pass').value;
  try {
    const r = await fetch(`${api}/api/v1/auth/token`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: user, password: pass}),
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) { const b = await r.json().catch(()=>({})); throw new Error(b.detail||`HTTP ${r.status}`); }
    const data = await r.json();
    _applyAuthSuccess(data, user, api);
  } catch(e) {
    errEl.textContent = '로그인 실패: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = '로그인';
  }
}
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !$('login-overlay').classList.contains('hidden')) {
    const activeTab = $('panel-login').classList.contains('active') ? 'login' : 'reg';
    if (activeTab === 'login') doLogin(); else doRegister();
  }
});
function doLogout() {
  _token = '';
  if (typeof _TIMERS !== 'undefined') _TIMERS.forEach(t => clearInterval(t));
  sessionStorage.removeItem('sf_token');
  $('login-overlay').classList.remove('hidden');
  $('logged-as').textContent = '';
  switchAuthTab('login');
}

// ── 회원가입 ──────────────────────────────────────────────────────────────────
async function doRegister() {
  const btn = $('btn-reg'), errEl = $('reg-err');
  errEl.textContent = '';
  const api  = $('reg-api-url').value.replace(/\/$/, '') || $('login-api-url').value.replace(/\/$/, '');
  const uname = $('reg-username').value.trim();
  const pw1   = $('reg-password').value;
  const pw2   = $('reg-password2').value;
  const name  = $('reg-name').value.trim();
  const email = $('reg-email').value.trim();

  if (!uname) { errEl.textContent = '사용자명을 입력하세요.'; return; }
  if (!/^[a-zA-Z0-9_]{3,32}$/.test(uname)) { errEl.textContent = '사용자명: 영문·숫자·_ 3~32자'; return; }
  if (pw1.length < 4) { errEl.textContent = '패스워드는 4자 이상이어야 합니다.'; return; }
  if (pw1 !== pw2) { errEl.textContent = '패스워드가 일치하지 않습니다.'; return; }

  btn.disabled = true; btn.textContent = '가입 중…';
  try {
    const r = await fetch(`${api}/api/v1/auth/register`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: uname, password: pw1, name, email}),
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) { const b = await r.json().catch(()=>({})); throw new Error(b.detail||`HTTP ${r.status}`); }
    const data = await r.json();
    // 회원가입 성공 → API URL도 login 쪽에 동기
    $('login-api-url').value = api;
    _applyAuthSuccess(data, uname, api);
  } catch(e) {
    errEl.textContent = '가입 실패: ' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = '가입하기';
  }
}

// ── 온보딩 위저드 ─────────────────────────────────────────────────────────────
const _OB_CROPS = [
  {id:'tomato',        label:'완숙토마토', icon:'🍅'},
  {id:'cherry_tomato', label:'방울토마토', icon:'🍒'},
  {id:'cucumber',      label:'오이',       icon:'🥒'},
  {id:'paprika',       label:'파프리카',   icon:'🫑'},
  {id:'strawberry',    label:'딸기',       icon:'🍓'},
  {id:'melon',         label:'멜론',       icon:'🍈'},
];
const _OB_PAIN = [
  '병해충 조기 탐지', '에너지 비용 절감', '수분/관수 최적화',
  '수확량 예측 부정확', '시장가격 정보 부족', '재배 데이터 관리',
  '노동력 부족', '환경 제어 자동화',
];
let _ob = {step:1, crop_ko:'', facility_type:'', area_m2:'', cultivation_method:'토경',
            region:'', season_start:'', season_end:'', growing_year:1,
            pain_points:[], kpi_yield_kg:'', kpi_revenue_wan:'', kpi_energy_save:'', kpi_drain_rate:''};

function startOnboarding() {
  _ob = {..._ob, step:1};
  $('onboarding-overlay').classList.remove('hidden');
  obRender();
}

function obRender() {
  const s = _ob.step;
  // 진행 바
  for (let i=1;i<=5;i++) {
    const pip = $(`ob-pip-${i}`);
    pip.className = 'ob-pip' + (i < s ? ' done' : i === s ? ' active' : '');
  }
  $('ob-step-badge').textContent = `${s} / 5`;
  $('ob-back-btn').style.display = s > 1 ? '' : 'none';
  const next = $('ob-next-btn');

  const titles = ['작목 선택','시설 정보','작기 정보','현재 애로사항','KPI 목표'];
  const descs  = [
    '재배하실 주요 작목을 선택해 주세요.',
    '시설 유형과 재배 면적을 입력해 주세요.',
    '재배 지역과 작기 일정을 설정해 주세요.',
    '현재 가장 어려운 부분을 선택해 주세요. (복수 선택 가능)',
    '올해 목표 수치를 입력해 주세요. (선택 사항)',
  ];
  $('ob-title').textContent = titles[s-1];
  $('ob-desc').textContent  = descs[s-1];

  const c = $('ob-content');
  if (s === 1) {
    // 작목 카드
    c.innerHTML = `<div class="crop-grid">${_OB_CROPS.map(cr =>
      `<div class="crop-card${_ob.crop_ko===cr.id?' selected':''}" onclick="obSelectCrop('${cr.id}')">
        <span class="crop-card-icon">${cr.icon}</span>${cr.label}
      </div>`).join('')}</div>`;
    next.textContent = '다음 →';
  } else if (s === 2) {
    c.innerHTML = `
      <div class="ob-field">
        <label>시설 유형</label>
        <select id="ob-facility">
          ${['비닐온실','유리온실','스마트팜(복합환경제어)','노지','기타'].map(v =>
            `<option value="${v}"${_ob.facility_type===v?' selected':''}>${v}</option>`).join('')}
        </select>
      </div>
      <div class="ob-grid2">
        <div class="ob-field">
          <label>재배 면적 (㎡)</label>
          <input id="ob-area" type="number" min="1" placeholder="예: 3000" value="${_ob.area_m2||''}">
        </div>
        <div class="ob-field">
          <label>재배 방식</label>
          <select id="ob-method">
            ${['토경','수경(NFT)','수경(DWC)','양액재배','수경(기타)'].map(v =>
              `<option value="${v}"${_ob.cultivation_method===v?' selected':''}>${v}</option>`).join('')}
          </select>
        </div>
      </div>`;
    next.textContent = '다음 →';
  } else if (s === 3) {
    c.innerHTML = `
      <div class="ob-field">
        <label>재배 지역</label>
        <select id="ob-region">
          ${['','서울/경기','강원','충북','충남','전북','전남','경북','경남','제주','기타'].map(v =>
            `<option value="${v}"${_ob.region===v?' selected':''}>${v||'선택 안 함'}</option>`).join('')}
        </select>
      </div>
      <div class="ob-grid2">
        <div class="ob-field">
          <label>작기 시작일</label>
          <input id="ob-season-start" type="date" value="${_ob.season_start||''}">
        </div>
        <div class="ob-field">
          <label>작기 종료 예정일</label>
          <input id="ob-season-end" type="date" value="${_ob.season_end||''}">
        </div>
      </div>
      <div class="ob-field">
        <label>재배 연차</label>
        <select id="ob-year">
          ${[1,2,3,4,5,10].map(v =>
            `<option value="${v}"${_ob.growing_year==v?' selected':''}>${v}년차${v===10?' 이상':''}</option>`).join('')}
        </select>
      </div>`;
    next.textContent = '다음 →';
  } else if (s === 4) {
    c.innerHTML = `<div class="pain-grid">${_OB_PAIN.map(p =>
      `<label class="pain-item${_ob.pain_points.includes(p)?' checked':''}">
        <input type="checkbox" value="${p}"${_ob.pain_points.includes(p)?' checked':''}
               onchange="obTogglePain('${p}',this.checked)"> ${p}
      </label>`).join('')}</div>`;
    next.textContent = '다음 →';
  } else if (s === 5) {
    c.innerHTML = `
      <div class="ob-grid2">
        <div class="ob-field">
          <label>목표 수확량 (kg/작기)</label>
          <input id="ob-kpi-yield" type="number" min="0" placeholder="예: 5000" value="${_ob.kpi_yield_kg||''}">
        </div>
        <div class="ob-field">
          <label>목표 매출 (만원/작기)</label>
          <input id="ob-kpi-rev" type="number" min="0" placeholder="예: 2000" value="${_ob.kpi_revenue_wan||''}">
        </div>
        <div class="ob-field">
          <label>에너지 절감 목표 (%)</label>
          <input id="ob-kpi-energy" type="number" min="0" max="100" placeholder="예: 15" value="${_ob.kpi_energy_save||''}">
        </div>
        <div class="ob-field">
          <label>배액률 목표 (%)</label>
          <input id="ob-kpi-drain" type="number" min="0" max="100" placeholder="예: 5" value="${_ob.kpi_drain_rate||''}">
        </div>
      </div>`;
    next.textContent = '완료 ✓';
  }
}

function obSelectCrop(id) {
  _ob.crop_ko = id;
  document.querySelectorAll('.crop-card').forEach(el => {
    el.classList.toggle('selected', el.onclick?.toString().includes(`'${id}'`));
  });
  // 좀 더 확실하게
  document.querySelectorAll('.crop-card').forEach((el,i) => {
    el.classList.toggle('selected', _OB_CROPS[i]?.id === id);
  });
}
function obTogglePain(p, checked) {
  if (checked) { if (!_ob.pain_points.includes(p)) _ob.pain_points.push(p); }
  else _ob.pain_points = _ob.pain_points.filter(x=>x!==p);
  document.querySelectorAll('.pain-item').forEach(el => {
    el.classList.toggle('checked', el.querySelector('input').checked);
  });
}

function obCollectStep() {
  const s = _ob.step;
  if (s === 2) {
    _ob.facility_type      = $('ob-facility')?.value || '';
    _ob.area_m2            = parseFloat($('ob-area')?.value) || null;
    _ob.cultivation_method = $('ob-method')?.value || '토경';
  } else if (s === 3) {
    _ob.region       = $('ob-region')?.value || '';
    _ob.season_start = $('ob-season-start')?.value || '';
    _ob.season_end   = $('ob-season-end')?.value || '';
    _ob.growing_year = parseInt($('ob-year')?.value) || 1;
  } else if (s === 5) {
    _ob.kpi_yield_kg    = parseFloat($('ob-kpi-yield')?.value)  || null;
    _ob.kpi_revenue_wan = parseFloat($('ob-kpi-rev')?.value)    || null;
    _ob.kpi_energy_save = parseFloat($('ob-kpi-energy')?.value) || null;
    _ob.kpi_drain_rate  = parseFloat($('ob-kpi-drain')?.value)  || null;
  }
}

async function obNext() {
  obCollectStep();
  if (_ob.step === 1 && !_ob.crop_ko) {
    showToast('작목을 선택해 주세요.'); return;
  }
  if (_ob.step < 5) {
    _ob.step++;
    obRender();
  } else {
    // 마지막 단계 → API 저장
    await obSubmit();
  }
}
function obPrev() {
  obCollectStep();
  if (_ob.step > 1) { _ob.step--; obRender(); }
}
async function obSkip() {
  $('onboarding-overlay').classList.add('hidden');
  refreshAll();
  if (_myFarmId) loadPlanBadge(_myFarmId);
}

async function obSubmit() {
  const btn = $('ob-next-btn');
  btn.disabled = true; btn.textContent = '저장 중…';
  try {
    const payload = {
      farm_id:            _myFarmId || '',
      crop_ko:            _ob.crop_ko,
      facility_type:      _ob.facility_type,
      area_m2:            _ob.area_m2,
      cultivation_method: _ob.cultivation_method,
      region:             _ob.region,
      season_start:       _ob.season_start,
      season_end:         _ob.season_end,
      growing_year:       _ob.growing_year,
      pain_points:        _ob.pain_points,
      kpi_yield_kg:       _ob.kpi_yield_kg,
      kpi_revenue_wan:    _ob.kpi_revenue_wan,
      kpi_energy_save:    _ob.kpi_energy_save,
      kpi_drain_rate:     _ob.kpi_drain_rate,
    };
    const r = await fetch(`${_apiBase}/api/v1/auth/onboarding`, {
      method:'POST',
      headers:{'Content-Type':'application/json', 'Authorization':`Bearer ${_token}`},
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) { const b = await r.json().catch(()=>({})); throw new Error(b.detail||`HTTP ${r.status}`); }
    $('onboarding-overlay').classList.add('hidden');
    refreshAll();
    if (_myFarmId) loadPlanBadge(_myFarmId);
  } catch(e) {
    showToast('온보딩 저장 오류: ' + e.message);
    $('onboarding-overlay').classList.add('hidden');
    refreshAll();
  } finally {
    btn.disabled = false; btn.textContent = '완료 ✓';
  }
}

// ── API 헬퍼 ─────────────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  let r;
  try {
    r = await fetch(`${_apiBase}${path}`, {
      ...opts,
      headers: { Authorization: `Bearer ${_token}`, ...(opts.headers||{}) },
      signal: AbortSignal.timeout(15000),
    });
  } catch(netErr) {
    const e = new Error(netErr.name === 'TimeoutError' ? '응답 시간 초과 (15초)' : '서버에 연결할 수 없음');
    e.code = netErr.name === 'TimeoutError' ? 'TIMEOUT' : 'NETWORK';
    e.cause = netErr;
    throw e;
  }
  if (r.status === 401) { doLogout(); const e = new Error('인증 만료'); e.code = 401; throw e; }
  if (!r.ok) {
    // Try to extract server-side error detail from JSON body
    let detail = '';
    try {
      const errBody = await r.json();
      detail = errBody.detail || errBody.message || errBody.msg || '';
      if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    } catch (_) {}
    const e = new Error(detail ? `HTTP ${r.status}: ${detail}` : `HTTP ${r.status}`);
    e.code = r.status;
    throw e;
  }
  return r.json();
}

// ── HTML 특수문자 이스케이프 (innerHTML 삽입 전 사용) ─────────────────────────
function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── API 오류 → 사용자 친화적 한국어 원인 + 조치 안내 ───────────────────────
function _errReason(e) {
  if (!e) return { msg: '알 수 없는 오류', action: null };
  const code = e.code;
  if (code === 'NETWORK')  return { msg: '🔴 서버에 연결할 수 없습니다', action: 'API 서버(uvicorn)가 실행 중인지 확인하세요.' };
  if (code === 'TIMEOUT')  return { msg: '⏱️ 응답 시간 초과 (15초)', action: '서버 부하 또는 네트워크 문제. 잠시 후 새로고침하세요.' };
  if (code === 401)        return { msg: '🔑 로그인 세션이 만료되었습니다', action: null };
  if (code === 403)        return { msg: '🔒 이 기능은 상위 구독 등급이 필요합니다', action: '설정 탭에서 플랜 업그레이드를 확인하세요.' };
  if (code === 404)        return { msg: '📭 데이터가 없습니다', action: '농장이 등록되었는지, 센서 데이터가 수집 중인지 확인하세요.' };
  if (code === 422)        return { msg: '⚠️ 요청 파라미터 오류', action: '농장 선택 후 다시 시도하세요.' };
  if (code === 500)        return { msg: '🔧 서버 내부 오류가 발생했습니다', action: '잠시 후 재시도하거나 관리자에게 문의하세요.' };
  return { msg: `⚠️ 오류: ${_esc(e.message)}`, action: null };
}

// ── 에러 박스 HTML 생성 ────────────────────────────────────────────────────
function _errBoxHtml(e, contextTitle = '데이터 조회 실패') {
  const { msg, action } = _errReason(e);
  return `<div class="data-err-box">
    <span>❌ ${contextTitle}</span>
    <span class="data-err-reason">${msg}</span>
    ${action ? `<span class="data-err-reason" style="color:var(--muted)">${action}</span>` : ''}
  </div>`;
}

// ── null 값 이유 박스 HTML 생성 ────────────────────────────────────────────
// nullFields: [ [label, reason], ... ] — 표시할 항목 목록
function _nullReasonHtml(nullFields) {
  if (!nullFields || !nullFields.length) return '';
  return `<div class="data-reason-box">
    <span class="data-reason-title">ℹ️ 일부 수치가 표시되지 않는 이유</span>
    ${nullFields.map(([label, reason]) =>
      `<span class="data-reason-item">· <strong>${label}</strong>: ${reason}</span>`
    ).join('')}
  </div>`;
}

// ── 전체 새로고침 ──────────────────────────────────────────────────────────────
async function refreshAll() {
  $('last-refresh').textContent = '로딩 중…';
  await loadHealth();
  await Promise.all([
    loadOverview(), loadCropModels(),
    loadPipelineState(), loadEtlStatus(), loadRetrainHistory(),
    loadFarmsOverview(),
    loadAdvisoryHistory(),
    loadAdvisorySummary(),
    loadPricesLatest(),
  ]);
  $('last-refresh').textContent = '갱신: ' + new Date().toLocaleTimeString('ko-KR');
  if (_token && !_wsActive) wsConnect($('sensor-farm-sel').value);
  // 농장 데이터 로드 완료 후 셀렉트 채우기 + 현재 활성 섹션 갱신
  populateAllFarmSels();
  const _activeSec = document.querySelector('.sec.active');
  const _activeName = _activeSec?.id?.replace('sec-', '');
  if (_activeName === 'dashboard') {
    // Hero 대시보드: 데이터 로드 후 자동 표시 (admin 포함)
    const heroFid = $('hero-farm-sel')?.value || _defaultFarm();
    if (heroFid) {
      _autoSel('hero-farm-sel', heroFid);
      loadHeroDashboard(heroFid);
    }
  } else if (_activeName && SECTION_LOADERS[_activeName] &&
             _activeName !== 'system') {
    // 현재 비대시보드 섹션도 갱신 (중복 호출 방지 위해 system 제외)
    // system 탭은 무거운 로드가 많으므로 사용자가 직접 트리거할 때만
  }
}

// ── Health ────────────────────────────────────────────────────────────────────
async function loadHealth() {
  try {
    const d = await apiFetch('/health');
    $('kpi-api').textContent = '정상';
    $('kpi-api').className   = 'kc-val green';
    $('kpi-api-ver').textContent = d.version || '—';
    $('status-badge').className  = 'online';
    $('status-badge').querySelector('span').textContent = 'API 연결됨';
  } catch(e) {
    const { msg } = _errReason(e);
    $('kpi-api').textContent = '오류';
    $('kpi-api').className   = 'kc-val red';
    $('status-badge').className = 'offline';
    $('status-badge').querySelector('span').textContent = msg;
  }
}

// ── Overview ──────────────────────────────────────────────────────────────────
async function loadOverview() {
  try {
    const d = await apiFetch('/api/admin/overview');
    const modEl = $('kpi-models');
    if (modEl) modEl.textContent = d.models_loaded ?? '—';
    const r2El = $('kpi-r2');
    if (r2El) r2El.textContent = d.avg_model_r2 != null ? d.avg_model_r2.toFixed(3) : '—';
  } catch(e) {
    const modEl = $('kpi-models');
    if (modEl) { modEl.textContent = '오류'; modEl.className = 'kc-val red'; }
    const r2El = $('kpi-r2');
    if (r2El) { r2El.textContent = '오류'; r2El.className = 'kc-val red'; }
  }
}

// ── Crop models ───────────────────────────────────────────────────────────────
async function loadCropModels() {
  const el = $('crop-models-body');
  try {
    const d = await apiFetch('/api/admin/models/crops');
    const rows = (d.crops||[]).map(c => {
      const st = c.status === 'loaded' ? '✅' : '⚠️';
      // /api/admin/models/crops 응답 필드: stage2_mape, stage2_cv_r2, stage1_cv_r2
      const mape   = c.stage2_mape ?? c.mape ?? null;
      const r2     = c.stage2_cv_r2 ?? c.stage1_cv_r2 ?? c.r2 ?? null;
      const m1Gate = c.stage1_gate ?? c.gate_m1 ?? null;
      const m2Gate = c.stage2_gate ?? c.gate_m2 ?? (mape != null ? mape <= 35 : null);
      const gateBadge = (passed, label) => {
        if (passed == null) return '';
        const cls = passed ? 'pass' : 'fail';
        const txt = passed ? '✓' : '✗';
        return `<span class="gate-badge ${cls}">${label}${txt}</span>`;
      };
      return `<tr>
        <td>${st} ${_esc(c.crop_ko||c.crop)}</td>
        <td>${mape!=null?Number(mape).toFixed(1)+'%':'—'}${gateBadge(m2Gate,'M2')}</td>
        <td>${r2!=null?Number(r2).toFixed(3):'—'}${gateBadge(m1Gate,'M1')}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="table-scroll-wrap"><table><thead><tr><th>작물</th><th>MAPE</th><th>R²</th></tr></thead><tbody>${rows||'<tr><td colspan="3" style="color:var(--muted);text-align:center">데이터 없음</td></tr>'}</tbody></table></div>`;
  } catch(e) { el.innerHTML = _errBoxHtml(e, '모델 목록 조회 실패'); }
}

// ── Pipeline state ────────────────────────────────────────────────────────────
async function loadPipelineState() {
  const el = $('pipeline-state-body');
  try {
    const d = await apiFetch('/api/admin/pipeline/state');
    el.innerHTML = `
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
          <span>환경 데이터</span><span>${d.new_env_rows} / ${d.env_threshold} 행 (${d.env_pct}%)</span>
        </div>
        <div class="prog-bar"><div class="prog-fill green" style="width:${Math.min(d.env_pct,100)}%"></div></div>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
          <span>생산량 데이터</span><span>${d.new_prod_rows} / ${d.prod_threshold} 행 (${d.prod_pct}%)</span>
        </div>
        <div class="prog-bar"><div class="prog-fill blue" style="width:${Math.min(d.prod_pct,100)}%"></div></div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:8px">갱신: ${(d.last_updated||'—').slice(0,19).replace('T',' ')}</div>`;
  } catch(e) { el.innerHTML = _errBoxHtml(e, '파이프라인 상태 조회 실패'); }
}

// ── 수동 재학습 트리거 (어드민 전용) ─────────────────────────────────────────
function triggerRetrainManual() {
  const resEl = $('retrain-trigger-result');
  const btn   = $('retrain-trigger-btn');
  BottomSheet.open(
    '⚠️ 전체 모델 재학습',
    '<p style="line-height:1.7;font-size:13px">전체 작목 AI 모델 재학습을 시작합니다.<br>약 <b>10~30분</b> 소요될 수 있습니다.</p>',
    '재학습 시작',
    async () => {
      if (btn) btn.disabled = true;
      if (resEl) resEl.innerHTML = '<span style="color:var(--muted);font-size:12px">재학습 요청 중…</span>';
      try {
        const d = await apiFetch('/api/admin/pipeline/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: '대시보드 수동 트리거', confirm: true }),
        });
        if (resEl) resEl.innerHTML = `<div style="color:var(--green);font-size:12px">✅ 재학습 시작됨 (run_id: ${_esc(d.run_id || '—')})</div>`;
        setTimeout(() => { loadRetrainHistory(); loadPipelineState(); }, 10_000);
      } catch(e) {
        if (resEl) resEl.innerHTML = `<div style="color:var(--red);font-size:12px">❌ 실패: ${_esc(e.message)}</div>`;
      } finally {
        if (btn) btn.disabled = false;
      }
    }
  );
}

// ── ETL status ────────────────────────────────────────────────────────────────
async function loadEtlStatus() {
  const el = $('etl-log');
  try {
    const d = await apiFetch('/api/admin/pipeline/etl-status?lines=30');
    // kpi-done — deprecated (DOM에 없으므로 안전하게 처리)
    setText('kpi-done', d.done_files ?? '—');
    if (d.last_modified) $('etl-mtime').textContent = d.last_modified.slice(0,19).replace('T',' ');
    const lines = (d.log_tail||[]).map(l => {
      const cls = l.includes('ERROR') ? 'log-error' : l.includes('WARN') ? 'log-warn' : '';
      return `<div class="log-line ${cls}">${_esc(l)}</div>`;
    }).join('');
    el.innerHTML = `<div class="log-box">${lines||'<span style="color:var(--muted)">로그 없음</span>'}</div>`;
    el.querySelector('.log-box').scrollTop = 9999;
  } catch(e) { el.innerHTML = _errBoxHtml(e, 'ETL 상태 조회 실패'); }
}

// ── Retrain history ───────────────────────────────────────────────────────────
async function loadRetrainHistory() {
  const el = $('retrain-events');
  try {
    const d = await apiFetch('/api/admin/pipeline/retrain-history?limit=10');
    if (!d.events?.length) { el.innerHTML = '<span style="color:var(--muted)">이력 없음</span>'; return; }
    el.innerHTML = d.events.map(ev => {
      const icon = ev.fail_count > 0 ? '❌' : '✅';
      return `<div class="event-item">
        <div style="display:flex;justify-content:space-between">
          <span>${icon} ${_esc(ev.crops?.join(', ')||'—')}</span>
          <span style="color:var(--muted);font-size:11px">${(ev.timestamp||'').slice(0,16).replace('T',' ')}</span>
        </div>
        <div style="font-size:11px;color:var(--muted)">성공 ${ev.success_count} / 실패 ${ev.fail_count} · ${_esc(ev.triggered_by||'—')}</div>
      </div>`;
    }).join('');
  } catch(e) { el.innerHTML = _errBoxHtml(e, '재학습 이력 조회 실패'); }
}

// ── 멀티 농장 비교 ────────────────────────────────────────────────────────────
let _farmsData    = [];
let _farmsSortKey = 'farm_id';
let _farmsSortAsc = true;

async function loadFarmsOverview() {
  try {
    const d = await apiFetch('/api/admin/farms/overview?limit=200');
    _farmsData = d.farms || [];
    const bar = $('farms-summary-bar');
    if (bar) bar.innerHTML =
      `<span class="farms-stat-chip farms-stat-total">전체 ${d.total}</span>` +
      `<span class="farms-stat-chip farms-stat-online">🟢 온라인 ${d.online}</span>` +
      `<span class="farms-stat-chip farms-stat-anomaly">🔴 이상 ${d.anomaly}</span>` +
      `<span class="farms-stat-chip farms-stat-offline">⚫ 오프라인 ${d.total - d.online}</span>`;
    renderFarmsTable();
    populateProfitFarmSel(_farmsData);
    populateAllFarmSels();
    // 대시보드 헤더 KPI — 공동출하 준비 농가 수
    const poolReady = _farmsData.filter(f => f.online && !f.anomaly).length;
    setText('kpi-pool-ready', poolReady + '개');
    // IoT 상태 KPI — 온라인 농가 비율
    if (d.total > 0) {
      const onlinePct = Math.round(d.online / d.total * 100);
      setText('kpi-iot-status', onlinePct + '%');
    }
  } catch(e) {
    const tb = $('farms-tbody');
    if (tb) tb.innerHTML = `<tr><td colspan="10" style="color:var(--muted);text-align:center;font-size:12px">내 농장 데이터 로드 중…</td></tr>`;
    // farmer 역할은 admin/overview 403 → 본인 농장만 단독 구성
    if (_myFarmId && !_farmsData.length) {
      try {
        const meta = await apiFetch(`/api/farms/${_myFarmId}/meta`);
        _farmsData = [{
          farm_id:  _myFarmId,
          crop_ko:  meta.crop_ko || meta.crop || '—',
          sido:     meta.sido    || '—',
          sigungu:  meta.sigungu || '—',
          online:   false,
          anomaly:  false,
        }];
        populateProfitFarmSel(_farmsData);
        populateAllFarmSels();
      } catch(_) { /* 메타 없으면 무시 */ }
    }
  }
}

function sortFarms(key) {
  if (_farmsSortKey === key) _farmsSortAsc = !_farmsSortAsc;
  else { _farmsSortKey = key; _farmsSortAsc = true; }
  renderFarmsTable();
}

function renderFarmsTable() {
  const search     = ($('farm-search')?.value     || '').toLowerCase();
  const cropFilter = $('farm-crop-filter')?.value  || '';
  const statFilter = $('farm-status-filter')?.value || '';

  let rows = _farmsData.filter(f => {
    if (cropFilter && f.crop_ko !== cropFilter) return false;
    if (statFilter === 'online'  && (!f.online || f.anomaly)) return false;
    if (statFilter === 'anomaly' && !f.anomaly)  return false;
    if (statFilter === 'offline' && f.online)    return false;
    if (search) {
      if (!`${f.farm_id} ${f.crop_ko} ${f.sido} ${f.sigungu}`.toLowerCase().includes(search)) return false;
    }
    return true;
  });

  rows.sort((a, b) => {
    let av = a[_farmsSortKey], bv = b[_farmsSortKey];
    if (av == null) av = _farmsSortAsc ? Infinity : -Infinity;
    if (bv == null) bv = _farmsSortAsc ? Infinity : -Infinity;
    if (typeof av === 'string') return _farmsSortAsc ? av.localeCompare(bv,'ko') : bv.localeCompare(av,'ko');
    return _farmsSortAsc ? av - bv : bv - av;
  });

  const fc = $('farms-count');
  if (fc) fc.textContent = `${rows.length}개 표시`;

  const tbody = $('farms-tbody');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;color:var(--muted)">조건에 맞는 농장이 없습니다</td></tr>';
    return;
  }

  const tempCls = v => v==null?'': v>35?'farm-val-hi': v<5?'farm-val-lo':'farm-val-ok';
  const humiCls = v => v==null?'': v>95?'farm-val-hi': v<30?'farm-val-lo':'';
  const co2Cls  = v => v==null?'': v>1500?'farm-val-hi':'';
  const fmt     = (v, d=1) => v!=null ? Number(v).toFixed(d) : '—';
  const fmtTs   = ts => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'}); }
    catch { return ts.slice(11,16); }
  };

  tbody.innerHTML = rows.map((f, idx) => {
    const stCls  = f.anomaly?'anomaly': f.online?'online':'offline';
    const stText = f.anomaly?'🔴 이상': f.online?'🟢 온라인':'⚫ 오프라인';
    return `<tr data-farmid="${_esc(f.farm_id)}" onclick="openChartPanel(this.dataset.farmid,this)" tabindex="0" role="button" onkeydown="if(event.key==='Enter'||event.key===' '){openChartPanel(this.dataset.farmid,this);event.preventDefault()}">
      <td style="font-family:monospace;font-size:11px">${_esc(f.farm_id)}</td>
      <td>${_esc(f.crop_ko)}</td>
      <td>${_esc(f.sido)} ${_esc(f.sigungu)}</td>
      <td class="${tempCls(f.temp_internal)}">${fmt(f.temp_internal)}</td>
      <td class="${humiCls(f.humidity_int)}">${fmt(f.humidity_int)}</td>
      <td class="${co2Cls(f.co2_ppm)}">${fmt(f.co2_ppm,0)}</td>
      <td>${fmt(f.soil_temp)}</td>
      <td>${fmt(f.ec_dsm,2)}</td>
      <td><span class="farm-status ${stCls}">${stText}</span></td>
      <td style="color:var(--muted);font-size:11px">${fmtTs(f.last_ts)}</td>
    </tr>`;
  }).join('');
}

setInterval(() => { if (_token) loadFarmsOverview(); }, 30_000);

// ── 센서 이력 차트 (Chart.js) ─────────────────────────────────────────────────
let _chartInstance  = null;
let _chartFarmId    = null;
let _chartMetric    = 'temp_internal';

const METRIC_CFG = {
  temp_internal: { label:'내부온도 (°C)',   color:'#f2645a', yLabel:'°C'     },
  humidity_int:  { label:'내부습도 (%)',     color:'#4f8ef7', yLabel:'%'      },
  co2_ppm:       { label:'CO₂ (ppm)',        color:'#3ecf8e', yLabel:'ppm'    },
  soil_temp:     { label:'지온 (°C)',        color:'#f5c842', yLabel:'°C'     },
};

let _detailTab = 'env';

function openChartPanel(farmId, rowEl) {
  // 선택 행 강조
  document.querySelectorAll('#farms-tbody tr').forEach(r => r.classList.remove('selected'));
  rowEl.classList.add('selected');

  _chartFarmId = farmId;
  $('chart-farm-label').textContent = farmId;

  // 농장 작목명 표시
  const farmInfo = _farmsData.find(f => f.farm_id === farmId);
  if ($('chart-farm-crop')) $('chart-farm-crop').textContent = farmInfo?.crop_ko || '';

  $('chart-panel').classList.add('open');

  // 현재 활성 탭 기준으로 로드
  if (_detailTab === 'env')     reloadChart();
  else if (_detailTab === 'reco')    loadFarmRecommendations(farmId);
  else if (_detailTab === 'harvest') loadFarmHarvestRevenue(farmId);
  else if (_detailTab === 'disease') loadFarmDiseaseRisk(farmId);
}

function setDetailTab(tab) {
  _detailTab = tab;
  // 탭 버튼 active 전환
  document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
  const tabIdx = ['env','reco','harvest','disease'].indexOf(tab);
  document.querySelectorAll('.detail-tab')[tabIdx]?.classList.add('active');
  // 패널 pane 전환
  ['detail-env','detail-reco','detail-harvest','detail-disease'].forEach(id => {
    const el = $(id); if (el) el.classList.remove('active');
  });
  $(`detail-${tab}`)?.classList.add('active');
  // 데이터 로드
  if (!_chartFarmId) return;
  if (tab === 'env')     reloadChart();
  else if (tab === 'reco')    loadFarmRecommendations(_chartFarmId);
  else if (tab === 'harvest') loadFarmHarvestRevenue(_chartFarmId);
  else if (tab === 'disease') loadFarmDiseaseRisk(_chartFarmId);
}

function closeChartPanel() {
  $('chart-panel').classList.remove('open');
  document.querySelectorAll('#farms-tbody tr').forEach(r => r.classList.remove('selected'));
  if (_chartInstance) { _chartInstance.destroy(); _chartInstance = null; }
}

function setChartMetric(metric) {
  _chartMetric = metric;
  document.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
  const keys = Object.keys(METRIC_CFG);
  const idx  = keys.indexOf(metric);
  document.querySelectorAll('.chart-tab')[idx]?.classList.add('active');
  reloadChart();
}

async function reloadChart() {
  if (!_chartFarmId) return;
  const days    = parseInt($('chart-days-sel').value || '7', 10);
  const canvas  = $('farm-chart-canvas');
  const noData  = $('chart-no-data');
  const srcLabel= $('chart-source-label');

  canvas.style.display = 'none';
  noData.style.display  = 'none';
  srcLabel.textContent  = '로딩 중…';

  try {
    const d = await apiFetch(`/api/admin/farms/${_chartFarmId}/history?days=${days}`);
    const pts = d.points || [];

    if (!pts.length) {
      noData.style.display = 'block';
      noData.textContent   = `${_chartFarmId} — ${days}일 이내 데이터가 없습니다 (소스: ${d.source})`;
      srcLabel.textContent = '';
      return;
    }

    const cfg = METRIC_CFG[_chartMetric];
    const labels = pts.map(p => {
      try { return new Date(p.ts).toLocaleString('ko-KR',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
      catch { return p.ts.slice(5,16); }
    });
    const values = pts.map(p => p[_chartMetric]);

    if (_chartInstance) _chartInstance.destroy();

    canvas.style.display = 'block';
    _chartInstance = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label:           cfg.label,
          data:            values,
          borderColor:     cfg.color,
          backgroundColor: cfg.color + '22',
          borderWidth:     1.5,
          pointRadius:     pts.length > 200 ? 0 : 2,
          tension:         0.3,
          fill:            true,
          spanGaps:        true,
        }],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        animation:           { duration: 300 },
        interaction:         { mode:'index', intersect:false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#0d1117',
            borderColor:     '#1f7a4d',
            borderWidth:     1,
            titleColor:      '#a8d5bc',
            bodyColor:       '#ffffff',
          },
        },
        scales: {
          x: {
            ticks: { color:'#607066', maxTicksLimit:10, maxRotation:0, font:{size:10} },
            grid:  { color:'rgba(220,230,220,.8)' },
          },
          y: {
            title: { display:true, text:cfg.yLabel, color:'#607066', font:{size:10} },
            ticks: { color:'#607066', font:{size:10} },
            grid:  { color:'rgba(220,230,220,.8)' },
          },
        },
      },
    });

    srcLabel.textContent = `${pts.length}포인트 · 소스: ${d.source}`;
  } catch(e) {
    noData.style.display = 'block';
    noData.textContent   = '차트 로드 실패: ' + e.message;
    srcLabel.textContent = '';
  }
}

// ── 농가 상세: AI 권고 ────────────────────────────────────────────────────────
const RECO_FIELD_LABELS = {
  temp_internal:'내부온도', humidity_int:'내부습도',
  co2_ppm:'CO₂', soil_temp:'지온', ec_dsm:'EC',
};

// 공통 권고 아이템 렌더 헬퍼 (RecommendationItem 스키마 기반)
function _renderRecoItems(items, farmId) {
  const TIER_BADGE = { auto:'🤖 자동', approval_required:'✋ 승인필요', checklist:'📋 체크' };
  const TIER_CLS   = { auto:'good', approval_required:'warn', checklist:'info' };
  const listHtml = items.map(r => {
    const profitCls = (r.profit_delta ?? 0) >= 0 ? 'positive' : 'negative';
    const sign = (r.profit_delta ?? 0) >= 0 ? '+' : '';
    const tierKey = r.tier_action || '';
    const tierTxt = TIER_BADGE[tierKey] || _esc(r.tier_action || '');
    const tierCls = TIER_CLS[tierKey] || 'info';
    const changes = r.canonical_changes || {};
    const changeSummary = Object.entries(changes)
      .map(([k, v]) => `${_esc(RECO_FIELD_LABELS[k]||k)} ${v>=0?'+':''}${Number(v).toFixed(1)}`)
      .join(', ');
    const action = r.action_ko || r.action || r.message || '—';
    const confPct = r.confidence != null ? Math.round((r.confidence??0)*100) : null;
    const confBadge = confPct != null
      ? `<span class="status-badge ${confPct>=80?'good':confPct>=50?'warn':'danger'}" style="font-size:10px">${confPct}%</span>`
      : '';
    return `<div class="reco-item">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px;flex-wrap:wrap">
        <span class="reco-action" style="flex:1;min-width:0">${r.rank != null ? `#${r.rank} ` : ''}${_esc(action)}</span>
        <span class="status-badge ${tierCls}" style="white-space:nowrap;font-size:10px">${tierTxt}</span>
      </div>
      ${changeSummary ? `<div style="font-size:10px;color:var(--muted);margin-top:2px">조정: ${changeSummary}</div>` : ''}
      <div style="display:flex;gap:8px;align-items:center;margin-top:5px;font-size:11px;flex-wrap:wrap">
        <span class="reco-val ${profitCls}">수익 ${sign}${Math.round(r.profit_delta??0).toLocaleString('ko-KR')}원</span>
        ${confBadge}
      </div>
    </div>`;
  }).join('');
  const totalProfit = items.reduce((s, r) => s + (r.profit_delta ?? 0), 0);
  const gainHtml = items.length > 0
    ? `<div class="reco-gain">📈 권고 전체 적용 시 기대 수익: +${Math.round(totalProfit).toLocaleString('ko-KR')}원</div>`
    : '';
  return { listHtml, gainHtml };
}

async function loadFarmRecommendations(farmId) {
  const el = $('detail-reco-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner" style="margin:40px auto;display:block"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/recommendations`);
    const items = d.recommendations || d.items || [];
    if (!items.length) {
      el.innerHTML = '<div style="text-align:center;color:var(--muted);padding:40px 0">현재 권고 사항이 없습니다 ✅</div>';
      return;
    }
    const { listHtml, gainHtml } = _renderRecoItems(items, farmId);
    el.innerHTML = `
      <div class="reco-list">${listHtml}</div>
      ${gainHtml}
      <button class="reco-apply-btn" data-farmid="${_esc(farmId)}" onclick="applyRecommendations(this.dataset.farmid)">✅ 권고 적용 요청</button>`;
  } catch(e) {
    el.innerHTML = `<div style="color:var(--red);padding:12px">권고 조회 실패: ${_esc(e.message)}</div>`;
  }
}

function applyRecommendations(farmId) {
  BottomSheet.open(
    'AI 권고 적용',
    `<p style="line-height:1.7;font-size:13px"><b>${_esc(farmId)}</b> 농장의 AI 권고를 적용합니다.<br>권고 내용을 확인 후 진행하세요.</p>`,
    '적용 요청',
    async () => {
      try {
        await apiFetch(`/api/farms/${farmId}/apply`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ rank: 1, confirmed: false }),
        });
        showToast('✅ 권고 적용 요청 완료');
        loadFarmRecommendations(farmId);
      } catch(e) { showToast('❌ 적용 실패: ' + e.message); }
    }
  );
}

// ── 농가 상세: 수확·매출 예측 ─────────────────────────────────────────────────
async function loadFarmHarvestRevenue(farmId) {
  const el = $('detail-harvest-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner" style="margin:40px auto;display:block"></div>';
  try {
    const [harv, rev] = await Promise.allSettled([
      apiFetch(`/api/farms/${farmId}/harvest`),
      apiFetch(`/api/farms/${farmId}/revenue`),
    ]);
    const h = harv.status === 'fulfilled' ? harv.value : null;
    const r = rev.status  === 'fulfilled' ? rev.value  : null;
    const fmt = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtKg = n => n != null ? Number(n).toFixed(1) : '—';

    const profit    = (r?.revenue_krw ?? 0) - (r?.cost_krw ?? 0);
    const profitCls = profit >= 0 ? 'positive' : 'negative';
    const profitSign= profit >= 0 ? '+' : '';

    el.innerHTML = `
      <div class="harvest-grid">
        <div class="harvest-kpi">
          <div class="hk-label">예상 수확량</div>
          <div class="hk-val">${fmtKg(h?.yield_kg_forecast)} <span style="font-size:13px;color:var(--muted)">kg</span></div>
        </div>
        <div class="harvest-kpi">
          <div class="hk-label">80% 신뢰구간</div>
          <div class="hk-val" style="font-size:14px">${h?.yield_q10 != null ? `${fmtKg(h.yield_q10)}–${fmtKg(h.yield_q90)} kg` : '—'}</div>
        </div>
        <div class="harvest-kpi">
          <div class="hk-label">잔여 재배일</div>
          <div class="hk-val">${h?.days_to_harvest ?? '—'} <span style="font-size:13px;color:var(--muted)">일</span></div>
        </div>
        <div class="harvest-kpi">
          <div class="hk-label">예상 매출</div>
          <div class="hk-val">${fmt(r?.revenue_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div>
        </div>
        <div class="harvest-kpi">
          <div class="hk-label">예상 비용</div>
          <div class="hk-val">${fmt(r?.cost_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div>
        </div>
        <div class="harvest-kpi">
          <div class="hk-label">예상 순이익</div>
          <div class="hk-val ${profitCls}">${profitSign}${fmt(profit)} <span style="font-size:11px">원</span></div>
        </div>
      </div>
      <div class="harvest-note">
        ${_esc(r?.crop_ko || '')} · 시세 ${r?.price_krw_kg != null ? Math.round(r.price_krw_kg).toLocaleString('ko-KR')+'원/kg' : '—'}
        ${r?.price_source === 'kamis_live' ? ' 🟢실시간' : ' 📊평균'}
        · 면적 ${h?.area_m2 != null ? h.area_m2.toLocaleString('ko-KR')+' m²' : '—'}
      </div>
      ${h?.confidence_grade ? (() => {
        const grade = h.confidence_grade;
        const isHigh = grade.startsWith('높음');
        const isMid  = grade.startsWith('보통');
        const badgeColor = isHigh ? '#22c55e' : isMid ? '#f59e0b' : '#94a3b8';
        const badgeBg    = isHigh ? 'rgba(34,197,94,.12)' : isMid ? 'rgba(245,158,11,.12)' : 'rgba(148,163,184,.10)';
        return `<div style="margin-top:6px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="background:${badgeBg};color:${badgeColor};border:1px solid ${badgeColor}33;border-radius:4px;padding:2px 7px;font-size:10px;font-weight:600">모델 신뢰도: ${_esc(grade)}</span>
          ${h.mape_note ? `<span style="font-size:10px;color:var(--muted)">${_esc(h.mape_note)}</span>` : ''}
        </div>`;
      })() : ''}`;
    // ── null 값 원인 분석 ──────────────────────────────────────────────────
    const nullReasons = [];
    if (!h) nullReasons.push(['수확 예측', '수확량 모델 API 응답 없음 — 서버 상태 확인 필요']);
    else if (h.yield_kg_forecast == null) nullReasons.push(['예상 수확량', '해당 작목의 M2 모델이 미학습 상태이거나 환경 센서 데이터 부족']);
    else if (h.confidence_grade?.startsWith('낮음')) nullReasons.push(['수확량 신뢰도', `현재 예측 오차 ≥ 45% — 데이터 수집 기간이 짧거나 센서 편차 큼`]);
    if (!r) nullReasons.push(['수익 분석', '매출·비용 API 응답 없음 — 농가 등록 완료 여부 확인']);
    else if (r.revenue_krw == null) nullReasons.push(['예상 매출', '도매가 정보 없음 — KAMIS API 키 또는 작목별 기본 시세 확인']);
    if (nullReasons.length) {
      const existing = el.innerHTML;
      el.innerHTML = existing + _nullReasonHtml(nullReasons);
    }
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '수확·수익 예측 조회 실패');
  }
}

// ── 농가 상세: 병해 위험 ──────────────────────────────────────────────────────
async function loadFarmDiseaseRisk(farmId) {
  const el = $('detail-disease-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner" style="margin:40px auto;display:block"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/disease-risk`);
    // API는 단일 DiseaseRiskResponse (flat) 또는 배열 형태 모두 처리
    let risks = d.risks || d.diseases || null;
    if (!risks) {
      // flat 단일 객체 → 배열 변환
      if (d.disease) {
        risks = [{
          disease_ko:  d.disease_ko  || d.disease,
          disease:     d.disease,
          risk_score:  d.score       ?? 0,
          risk_level:  d.risk_level,
          note:        (d.reasons || []).join(' ') || d.action_ko || '',
        }];
      } else {
        risks = [];
      }
    }
    if (!risks.length) {
      el.innerHTML = '<div style="text-align:center;color:var(--muted);padding:40px 0">병해 위험 데이터가 없습니다</div>';
      return;
    }
    const cards = risks.map(r => {
      const pct   = Math.round((r.risk_score ?? r.score ?? r.risk ?? 0) * 100);
      const lvl   = pct < 30 ? 'low' : pct < 60 ? 'med' : 'high';
      const lvlTxt= pct < 30 ? '낮음' : pct < 60 ? '중간' : '높음';
      const badge = pct < 30 ? 'ok' : pct < 60 ? 'warn' : 'fail';
      return `<div class="disease-card">
        <div class="disease-name">${_esc(r.disease_ko || r.disease || '—')}
          <span class="badge ${badge}" style="float:right">${lvlTxt}</span>
        </div>
        <div class="disease-risk-bar">
          <div class="disease-risk-fill disease-risk-${lvl}" style="width:${pct}%"></div>
        </div>
        <div class="disease-pct">${pct}% · ${_esc(r.note || r.description || r.action_ko || '')}</div>
      </div>`;
    }).join('');
    // env_snapshot 표시
    const snap = d.env_snapshot;
    const snapFmt = v => v != null && !isNaN(Number(v)) ? Number(v).toFixed(1) : '—';
    const snapHtml = snap ? `<div style="font-size:10px;color:var(--muted);margin-top:8px">
      판단근거: 온도 ${snapFmt(snap.temp_internal)}°C / 습도 ${snapFmt(snap.humidity_int)}% / CO₂ ${snapFmt(snap.co2_ppm)}ppm</div>` : '';
    // 조치 권고
    const actionHtml = d.action_ko ? `<div style="font-size:11px;color:var(--accent);margin-top:6px">💊 ${_esc(d.action_ko)}</div>` : '';
    el.innerHTML = `<div class="disease-grid">${cards}</div>${snapHtml}${actionHtml}`;
  } catch(e) {
    el.innerHTML = `<div style="color:var(--red);padding:12px">병해 조회 실패: ${_esc(e.message)}</div>`;
  }
}

// ── KAMIS 실시간 시세 스트립 ──────────────────────────────────────────────────
async function loadPricesLatest() {
  if (!_token) return;
  try {
    const d = await apiFetch('/api/admin/prices/latest');
    const prices = d.prices || d.items || [];
    if (!prices.length) return;
    const strip = $('price-strip');
    const chips = $('price-chips');
    if (!strip || !chips) return;
    chips.innerHTML = prices.map(p => {
      const fmtPrice = Math.round(p.price_krw_kg ?? p.price ?? 0).toLocaleString('ko-KR');
      const chgVal   = p.change_pct ?? p.chg_pct;
      const chgHtml  = chgVal != null
        ? `<span class="pc-chg ${chgVal >= 0 ? 'up' : 'down'}">${chgVal >= 0 ? '▲' : '▼'}${Math.abs(chgVal).toFixed(1)}%</span>`
        : '';
      const srcCls   = p.source === 'kamis_live' ? 'live' : 'avg';
      const srcTxt   = p.source === 'kamis_live' ? '실시간' : '평균';
      return `<span class="price-chip">
        <span class="pc-crop">${_esc(p.crop_ko || p.crop || '—')}</span>
        <span class="pc-val">${fmtPrice}원/kg</span>
        ${chgHtml}
        <span class="pc-src ${srcCls}">${srcTxt}</span>
      </span>`;
    }).join('');
    strip.style.display = 'flex';
  } catch(e) { console.warn('[prices-strip] 조회 실패:', e.message); }
}

// ── WebSocket 실시간 센서 ──────────────────────────────────────────────────────
let _ws = null, _wsActive = false, _wsRetryDelay = 2000, _wsRetryTimer = null;
let _wsPingTimer = null;   // ping setInterval 핸들 (wsConnect 재호출 시 누수 방지)
let _currentFarm = 'farm_001';

const SENSOR_RANGE = {
  temp_internal: [-5,  55],
  humidity_int:  [0,  100],
  co2_ppm:       [200,5000],
  soil_temp:     [-5,  50],
  ec_dsm:        [0,   10],
};

function wsBadge(state) {
  const badge = $('ws-badge'), label = $('ws-label');
  badge.className = `ws-badge ${state}`;
  const dot = badge.querySelector('.ws-dot');
  if (state === 'connected') { label.textContent='실시간 연결'; dot?.classList.add('pulse'); }
  else if (state === 'reconnecting') { label.textContent='재연결 중…'; dot?.classList.remove('pulse'); }
  else { label.textContent='연결 안 됨'; dot?.classList.remove('pulse'); }
}

function wsConnect(farmId) {
  if (farmId) _currentFarm = farmId;
  if (_ws) { _ws.onclose=null; _ws.close(); }
  clearTimeout(_wsRetryTimer);
  wsBadge('reconnecting');
  _wsActive = false;
  const url = `${_apiBase.replace(/^http/,'ws')}/ws/farms/${_currentFarm}/sensors`;
  try { _ws = new WebSocket(url); } catch { scheduleWsRetry(); return; }
  _ws.onopen    = () => { wsBadge('connected'); _wsActive=true; _wsRetryDelay=2000; };
  _ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type==='env')  applyEnvMessage(msg);
      if (msg.type==='ping') _ws.send(JSON.stringify({type:'pong'}));
    } catch {}
  };
  _ws.onerror = () => {};
  _ws.onclose = () => { wsBadge('disconnected'); _wsActive=false; scheduleWsRetry(); };
  // 기존 ping 타이머 해제 후 새로 등록 (wsConnect 재호출 시 누수 방지)
  if (_wsPingTimer) clearInterval(_wsPingTimer);
  _wsPingTimer = setInterval(() => { if(_ws?.readyState===1) _ws.send(JSON.stringify({type:'ping'})); }, 30_000);
}

function scheduleWsRetry() {
  _wsRetryTimer = setTimeout(() => wsConnect(), _wsRetryDelay);
  _wsRetryDelay = Math.min(_wsRetryDelay*2, 30_000);
}

function switchFarm(farmId) {
  _currentFarm = farmId;
  ['temp','humi','co2','solar','soil','ec'].forEach(k => { const el=$(`sv-${k}`); if(el) el.textContent='—'; });
  $('sensor-ts').textContent = '마지막 수신: —';
  _wsRetryDelay = 2000;
  wsConnect(farmId);
}

function applyEnvMessage(msg) {
  const sv = (id, v) => { const el=$(id); if(el) el.textContent = v!=null?Number(v).toFixed(1):'—'; };
  sv('sv-temp',  msg.temp_internal);
  sv('sv-humi',  msg.humidity_int);
  sv('sv-co2',   msg.co2_ppm);
  sv('sv-solar', msg.solar_rad);
  sv('sv-soil',  msg.soil_temp);
  sv('sv-ec',    msg.ec_dsm);
  const ts = msg.ts ? new Date(msg.ts).toLocaleTimeString('ko-KR') : new Date().toLocaleTimeString('ko-KR');
  $('sensor-ts').textContent = `마지막 수신: ${ts}`;
  ['temp','humi','co2','solar','soil','ec'].forEach(k => $(`sc-${k}`)?.classList.remove('anomaly'));
  if (msg._anomaly) showAnomalyToast(msg);
}

function showAnomalyToast(msg) {
  const toast = $('anomaly-toast');
  toast.textContent = `🚨 ${msg.farm_id} 이상값 감지`;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 5000);
}

// 일반 토스트 — 성공(✅)/실패(❌)/경고(⚠️) 메시지용
let _toastTimer = null;
function showToast(msg, durationMs = 3000) {
  let el = $('general-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'general-toast';
    el.style.cssText = [
      'position:fixed', 'bottom:80px', 'left:50%', 'transform:translateX(-50%)',
      'background:rgba(30,35,50,.96)', 'color:#fff', 'padding:10px 20px',
      'border-radius:10px', 'font-size:13px', 'font-weight:600',
      'z-index:500', 'box-shadow:0 4px 16px rgba(0,0,0,.4)',
      'opacity:0', 'transition:opacity .2s', 'pointer-events:none',
      'max-width:320px', 'text-align:center',
    ].join(';');
    document.body.appendChild(el);
  }
  const isOk  = msg.startsWith('✅');
  const isErr = msg.startsWith('❌');
  el.style.borderLeft = isOk ? '3px solid var(--green)' : isErr ? '3px solid var(--red)' : '3px solid var(--accent)';
  el.textContent = msg;
  el.style.opacity = '1';
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.opacity = '0'; }, durationMs);
}

// HTTP 폴백 30초 polling (백그라운드 탭·미로그인 시 스킵)
setInterval(async () => {
  if (_wsActive || !_token || document.hidden) return;
  try {
    const d = await apiFetch(`/api/sensors/${_currentFarm}/latest`);
    if (d?.messages?.length) applyEnvMessage(d.messages[d.messages.length-1]);
  } catch(e) { console.debug('[ws-fallback] 폴링 실패:', e.message); }
}, 30_000);

// 60초 자동 전체 갱신

// ── 재배 권고 이력 ─────────────────────────────────────────────────────────────
let _advisoryEntries = [];

async function loadAdvisoryHistory() {
  if (!_token) return;
  const limit = $('adv-filter-limit') ? $('adv-filter-limit').value : 50;
  try {
    const data = await apiFetch(`/api/admin/advisor/history?limit=${limit}`);
    _advisoryEntries = data.entries || [];
    renderAdvisoryFeed();
  } catch(e) {
    console.warn('[advisor] 이력 조회 실패:', e);
    const feed = $('advisory-feed');
    if (feed) feed.innerHTML = `<div class="data-err-box">권고 이력 조회 실패<span class="data-err-reason">${_esc(e.message)}</span></div>`;
  }
}

function renderAdvisoryFeed() {
  const feed   = $('advisory-feed');
  const empty  = $('adv-empty');
  const filter = ($('adv-filter-farm') ? $('adv-filter-farm').value.trim().toLowerCase() : '');

  const entries = filter
    ? _advisoryEntries.filter(e => e.farm_id.toLowerCase().includes(filter))
    : _advisoryEntries;

  if (!entries.length) {
    feed.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  const FIELD_LABELS = {
    temp_internal: '내부온도', humidity_int: '내부습도', co2_ppm: 'CO₂',
    soil_temp: '지온', ec_dsm: 'EC',
  };
  const CH_LABEL = { email:'이메일', sms:'SMS', kakao:'카카오', dry_run:'DRY-RUN', error:'오류' };

  feed.innerHTML = entries.map(entry => {
    const ts      = entry.ts ? new Date(entry.ts).toLocaleString('ko-KR') : '—';
    const topSide = entry.advices.length ? entry.advices[0].side : 'both';
    const sideClass = topSide === 'high' ? 'side-high' : topSide === 'low' ? 'side-low' : '';

    const itemsHtml = entry.advices.map(a => {
      const fname = FIELD_LABELS[a.field] || a.field;
      const optStr = `최적 ${a.optimal[0]}–${a.optimal[1]}`;
      const arrow  = a.side === 'high' ? '↑' : a.side === 'low' ? '↓' : '↕';
      return `<div class="adv-item">
        <span class="adv-field">${arrow} ${_esc(fname)}</span>
        <span class="adv-action">${_esc(a.action)}</span>
        <span class="adv-val">(현재 ${_esc(String(a.value??''))} / ${_esc(optStr)})</span>
      </div>`;
    }).join('');

    const chHtml = (entry.channels || []).map(ch =>
      `<span class="adv-ch-badge ${_esc(ch)}">${_esc(CH_LABEL[ch] || ch)}</span>`
    ).join('');

    return `<div class="adv-entry ${sideClass}">
      <div class="adv-entry-hdr">
        <div style="display:flex;gap:6px;align-items:center">
          <span class="adv-farm-tag">${_esc(entry.farm_id)}</span>
          <span class="adv-crop-tag">${_esc(entry.crop_ko)}</span>
        </div>
        <span class="adv-ts">${ts}</span>
      </div>
      <div class="adv-items">${itemsHtml}</div>
      <div class="adv-channels">${chHtml}</div>
    </div>`;
  }).join('');
}

// 권고 이력 30초 자동갱신

// ── 손익 예측 (Phase 26) ────────────────────────────────────────────────────
async function loadProfitForecast() {
  if (!_token) return;
  const sel    = $('profit-farm-sel');
  const farmId = (sel ? sel.value : '') || _defaultFarm();
  const body   = $('profit-body');
  if (!farmId) return;

  body.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/admin/farms/${farmId}/profit-forecast`);
    const fmt = n => n != null && !isNaN(n) ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtKg = n => n != null ? Number(n).toFixed(1) : '—';
    const profit = d.profit_krw ?? (( d.revenue_krw ?? 0) - (d.cost_krw ?? 0));
    const profitClass = profit >= 0 ? 'positive' : 'negative';
    const sign = profit >= 0 ? '+' : '';
    const marginPct = d.profit_margin_pct != null ? d.profit_margin_pct.toFixed(1) : '—';
    body.innerHTML = `
      <div class="profit-grid">
        <div class="profit-kpi"><div class="pk-label">예상 수확량</div>
          <div class="pk-val">${fmtKg(d.yield_kg_forecast)} <span style="font-size:11px;color:var(--muted)">kg</span></div></div>
        <div class="profit-kpi"><div class="pk-label">시세 (${d.price_source === 'kamis_live' ? '🟢실시간' : '📊평균'})</div>
          <div class="pk-val">${fmt(d.price_krw_kg)} <span style="font-size:11px;color:var(--muted)">원/kg</span></div></div>
        <div class="profit-kpi"><div class="pk-label">재배 면적</div>
          <div class="pk-val">${fmt(d.plant_area_m2)} <span style="font-size:11px;color:var(--muted)">m²</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 매출</div>
          <div class="pk-val">${fmt(d.revenue_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 비용</div>
          <div class="pk-val">${fmt(d.cost_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 순이익</div>
          <div class="pk-val ${profitClass}">${sign}${fmt(profit)} <span style="font-size:11px">원</span></div></div>
      </div>
      <div class="profit-note">${_esc(d.crop_ko || '')} · ${d.season_months || '—'}개월 시즌 · 이익률 ${marginPct}% · ${_esc(d.note || '')}</div>
    `;
  } catch(e) {
    body.innerHTML = `<div style="color:var(--muted);font-size:12px;padding:8px">조회 실패: ${_esc(e.message)}</div>`;
  }
}

// ── 권고 빈도 히트맵 (Phase 27) ──────────────────────────────────────────────
const FIELD_SHORT = {
  temp_internal:'내부온도', humidity_int:'내부습도',
  co2_ppm:'CO₂', soil_temp:'지온', ec_dsm:'EC',
};

async function loadAdvisorySummary() {
  if (!_token) return;
  const days = $('heatmap-days-sel') ? $('heatmap-days-sel').value : 30;
  try {
    const d = await apiFetch(`/api/admin/advisor/summary?days=${days}`);
    renderHeatmap(d);
  } catch(e) {
    console.warn('[heatmap] 조회 실패:', e);
    const tbody = $('heatmap-tbody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="10" style="color:var(--red);padding:8px">${_esc(e.message)}</td></tr>`;
  }
}

function renderHeatmap(d) {
  const empty  = $('heatmap-empty');
  const thead  = $('heatmap-thead');
  const tbody  = $('heatmap-tbody');

  if (!d.by_farm_field || d.by_farm_field.length === 0) {
    if (empty) empty.style.display = 'block';
    thead.innerHTML = ''; tbody.innerHTML = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  // 필드 목록 (열)
  const fields = [...new Set(d.by_farm_field.map(e => e.field))].sort();
  // 농장 목록 (행) — 상위 15개
  const farms  = [...new Set(d.by_farm_field.map(e => e.farm_id))].slice(0, 15);

  // lookup: farm+field → count
  const lookup = {};
  d.by_farm_field.forEach(e => { lookup[`${e.farm_id}||${e.field}`] = e.count; });

  // 최대값
  const maxCount = Math.max(...d.by_farm_field.map(e => e.count), 1);

  function hmClass(n) {
    if (!n) return 'hm-0';
    const ratio = n / maxCount;
    if (ratio < 0.2) return 'hm-1';
    if (ratio < 0.4) return 'hm-2';
    if (ratio < 0.6) return 'hm-3';
    if (ratio < 0.8) return 'hm-4';
    return 'hm-5';
  }

  thead.innerHTML = '<th>농장</th>' +
    fields.map(f => `<th>${_esc(FIELD_SHORT[f] || f)}</th>`).join('') +
    '<th>합계</th>';

  tbody.innerHTML = farms.map(fid => {
    const total = fields.reduce((s, f) => s + (lookup[`${fid}||${f}`] || 0), 0);
    const cells = fields.map(f => {
      const n = lookup[`${fid}||${f}`] || 0;
      return `<td><span class="hm-cell ${hmClass(n)}">${n || ''}</span></td>`;
    }).join('');
    return `<tr><td style="font-size:11px;white-space:nowrap">${_esc(fid)}</td>${cells}<td style="font-weight:600">${total}</td></tr>`;
  }).join('');
}

// ── 섹션 내비게이션 ─────────────────────────────────────────────────────────

/** 현재 로그인 농가 ID.
 *  우선순위: ① _farmsData에 내 farm_id가 있으면 반환
 *           ② _farmsData 첫 번째 농가 (admin/manager)
 *           ③ _myFarmId 직접 반환 (farmer이지만 _farmsData 아직 미적재)
 *  admin/manager 계정은 farm_id='' 이므로 항상 첫 번째 농가 반환 */
function _defaultFarm() {
  if (_myFarmId && _farmsData.some(f => f.farm_id === _myFarmId)) {
    return _myFarmId;
  }
  if (_farmsData.length) return _farmsData[0].farm_id;
  // _farmsData 미적재 시에도 본인 농장 ID로 직접 API 호출 허용
  return _myFarmId || '';
}

/** select 요소를 farmId로 지정하고, 아직 값이 없을 때만 적용 */
function _autoSel(selId, farmId) {
  const sel = $(selId);
  if (sel && !sel.value && farmId) sel.value = farmId;
}

const SECTION_LOADERS = {
  dashboard: () => {
    // _farmsData가 없으면 loadFarmsOverview 후 Hero 재시도
    if (!_farmsData.length) {
      loadFarmsOverview().then(() => {
        populateAllFarmSels();
        const fid2 = _defaultFarm();
        if (fid2) { _autoSel('hero-farm-sel', fid2); loadHeroDashboard(fid2); }
      });
    } else {
      loadFarmsOverview(); // 백그라운드 갱신
    }
    populateAllFarmSels();
    const fid = _defaultFarm();
    if (fid) {
      _autoSel('hero-farm-sel', fid);
      loadHeroDashboard(fid);
    }
  },

  environ: () => {
    const _doLoadEnviron = () => {
      populateAllFarmSels();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('env-view-farm',    fid);
        _autoSel('env-anomaly-farm', fid);
        _autoSel('weather-farm-sel', fid);
        _autoSel('env-manual-farm',  fid);
        _autoSel('led-farm-sel',     fid);
        loadCurrentEnv();
        loadWeatherForecast();   // 기상예보 자동 로드
        loadEnvAnomalies();      // 이상감지 자동 로드
        loadLEDSpectrum();       // LED 스펙트럼 권장 자동 로드
      }
    };
    if (!_farmsData.length) {
      // _farmsData 미적재 시 먼저 농장 목록 로드 후 환경탭 채우기
      loadFarmsOverview().then(_doLoadEnviron).catch(_doLoadEnviron);
    } else {
      _doLoadEnviron();
    }
    if (_myFarmId) tierGuard(_myFarmId, 'environ');
  },

  control: () => {
    const _doLoadControl = () => {
      populateAllFarmSels();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('ctrl-farm-sel', fid);
        loadCtrlRecommendations();   // AI 권고 자동 로드
        loadDiseaseDetect(fid);      // G5 헤더 KPI 업데이트
      }
      loadAdvisoryHistory();
      loadAdvisorySummary();
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadControl).catch(_doLoadControl);
    } else { _doLoadControl(); }
    if (_myFarmId) tierGuard(_myFarmId, 'control');
  },

  irrigation: () => {
    const _doLoadIrrigation = () => {
      populateAllFarmSels();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('irr-sched-farm', fid);
        _autoSel('priva-farm-sel', fid);
        _autoSel('irri-farm-sel2', fid);
        loadIrrigationAnalysis(fid);
        loadIrrigationSchedule();
        loadPrivaSchedule();
      }
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadIrrigation).catch(_doLoadIrrigation);
    } else { _doLoadIrrigation(); }
    if (_myFarmId) tierGuard(_myFarmId, 'irrigation');
  },

  growth: () => {
    const _doLoadGrowth = () => {
      loadCropModels();
      populateGrowthSel();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('growth-farm-sel',  fid);
        _autoSel('whatif-farm-sel',  fid);
        _autoSel('sfrop-farm-sel',   fid);
        loadGrowthHarvestRevenue();
        loadSfropScenarios();    // SFROP 4개 시나리오 자동 로드
      }
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadGrowth).catch(_doLoadGrowth);
    } else { _doLoadGrowth(); }
    if (_myFarmId) tierGuard(_myFarmId, 'growth');
  },

  market: () => {
    const _doLoadMarket = () => {
      populateAllFarmSels();
      loadMarketPrices();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('market-harvest-farm', fid);
        const sel = $('price-hist-crop');
        if (sel && !sel.value) sel.value = '딸기';
        loadPriceHistory();
        loadMarketHarvest();     // 출하예측 자동 로드
      }
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadMarket).catch(_doLoadMarket);
    } else { _doLoadMarket(); }
    if (_myFarmId) tierGuard(_myFarmId, 'market');
  },

  energy: () => {
    loadPricesLatest();
    const _doLoadEnergy = () => {
      populateAllFarmSels();
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('erp-farm-sel',     fid);
        _autoSel('cost-farm-sel',    fid);
        _autoSel('profit-farm-sel',  fid);
        _autoSel('cost-manual-farm', fid);
        loadERPRealtime();       // ERP 실시간 원가·마진 자동 로드
        loadProfitForecast();
        loadCostBreakdown();     // 비용내역 자동 로드
      }
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadEnergy).catch(_doLoadEnergy);
    } else { _doLoadEnergy(); }
    if (_myFarmId) tierGuard(_myFarmId, 'energy');
  },

  system: () => {
    loadPipelineState(); loadEtlStatus(); loadRetrainHistory();
    loadModelPerformance(); loadApiStatus();
    loadDiseaseDetect(); loadWholesaleMarket();
  },
};

function showSection(name) {
  // 유효하지 않은 섹션명 보호 — 대시보드로 폴백
  const secEl = document.getElementById(`sec-${name}`);
  if (!secEl) { console.warn('[showSection] 섹션 없음:', name); name = 'dashboard'; }

  // nav 활성화
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll(`[onclick="showSection('${name}')"]`).forEach(b => b.classList.add('active'));
  // 하단 탭 바 활성화 동기화
  document.querySelectorAll('.bn-tab[data-sec]').forEach(t => t.classList.remove('active'));
  const bnTab = document.querySelector(`.bn-tab[data-sec="${name}"]`);
  if (bnTab) bnTab.classList.add('active');
  // 모바일 드로어 자동 닫기
  closeDrawer();

  // 모든 섹션 숨기기 (inline style + class 이중 처리 — CSS 의존성 제거)
  document.querySelectorAll('.sec').forEach(s => {
    s.classList.remove('active');
    s.style.display = 'none';
  });

  // 대상 섹션 표시
  const target = document.getElementById(`sec-${name}`);
  if (target) {
    target.classList.add('active');
    target.style.display = 'flex';
  }

  // 섹션 전환 시 스크롤 맨 위로 초기화
  const _ca = document.getElementById('content-area');
  if (_ca) _ca.scrollTop = 0;
  if (target) target.scrollTop = 0;

  const runLoader = () => { if (SECTION_LOADERS[name]) SECTION_LOADERS[name](); };

  // _farmsData가 아직 로드 안 됐으면 먼저 로드 후 섹션 로더 실행
  if (!_farmsData.length && name !== 'system') {
    loadFarmsOverview().then(runLoader).catch(runLoader);
  } else {
    runLoader();
  }
}

// ── 농장 선택지 일괄 채우기 헬퍼 ────────────────────────────────────────────
function populateSelectWithFarms(selId, current = '') {
  const sel = $(selId);
  if (!sel) return;
  if (!_farmsData.length) {
    // 농장 없음 상태 표시 (빈 select 대신 명시적 안내)
    sel.innerHTML = '<option value="">등록된 농장 없음</option>';
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  // 기존 선택값 보존 (명시적으로 current가 전달되지 않은 경우)
  const prevVal = current || sel.value;
  const defaultFid = prevVal || _myFarmId || (_farmsData[0]?.farm_id) || '';
  sel.innerHTML = '<option value="">선택…</option>' +
    _farmsData.map(f =>
      `<option value="${_esc(f.farm_id)}" ${f.farm_id === defaultFid ? 'selected' : ''}>${_esc(f.farm_id)} (${_esc(f.crop_ko||'')})</option>`
    ).join('');
}

function populateAllFarmSels() {
  ['growth-farm-sel','whatif-farm-sel','sfrop-farm-sel',
   'cost-farm-sel','profit-farm-sel','erp-farm-sel',
   'ctrl-farm-sel','irri-farm-sel2',
   'irr-sched-farm','priva-farm-sel','market-harvest-farm',
   'env-view-farm','weather-farm-sel','env-manual-farm','env-anomaly-farm',
   'led-farm-sel','cost-manual-farm','chat-farm-sel',
   'hero-farm-sel'].forEach(id => populateSelectWithFarms(id));
  // sensor-farm-sel 동적 채우기
  const sfSel = $('sensor-farm-sel');
  if (sfSel && _farmsData.length) {
    const cur = sfSel.value;
    sfSel.innerHTML = _farmsData.map(f =>
      `<option value="${_esc(f.farm_id)}" ${f.farm_id === cur ? 'selected' : ''}>${_esc(f.farm_id)}</option>`
    ).join('');
  }
}

// populateProfitFarmSel 확장 (기존 함수 덮어쓰기)
function populateProfitFarmSel(farms) {
  _farmsData = farms && farms.length ? farms : _farmsData;
  populateAllFarmSels();
  // 손익 예측 자동 첫 농장 선택
  const sel = $('profit-farm-sel');
  if (sel && !sel.value && _farmsData.length) {
    sel.value = _farmsData[0].farm_id;
    loadProfitForecast();
  }
}

function populateGrowthSel() {
  populateAllFarmSels();
  const sel = $('growth-farm-sel');
  if (sel && !sel.value && _farmsData.length) {
    sel.value = _farmsData[0].farm_id;
    loadGrowthHarvestRevenue();
  }
}

// ── 생육 모델 세그먼트 컨트롤 ──────────────────────────────────────────────
let _growthModelType = 'kaasa'; // 'rda' | 'kaasa' | 'dynamic'

function setGrowthModel(type) {
  _growthModelType = type;
  // 버튼 active 상태 업데이트
  document.querySelectorAll('#model-seg-ctrl .seg-btn').forEach(btn => {
    btn.classList.toggle('seg-active', btn.dataset.model === type);
    // 색상: kaasa=green, dynamic=orange, rda=default(muted)
    btn.classList.remove('green', 'blue', 'orange');
    if (btn.dataset.model === type) {
      if (type === 'kaasa')   btn.classList.add('green');
      else if (type === 'dynamic') btn.classList.add('orange');
    }
  });
  // 모델 타입에 따른 설명 업데이트
  const hint = document.querySelector('#sec-growth .explain-box b');
  if (hint) {
    const labels = { rda: '농진청 표준', kaasa: 'KAASA AI', dynamic: '내 농장 동적' };
    hint.textContent = (labels[type] || 'AI') + ' 생육모델:';
  }
  // 재로드 (API가 model_type 파라미터를 지원하면 전달, 아니면 클라이언트 측 레이블만 변경)
  loadGrowthHarvestRevenue();
}

// ── 생육/재배: 수확량 + 매출·소득 예측 ──────────────────────────────────────
async function loadGrowthHarvestRevenue() {
  const farmId = $('growth-farm-sel')?.value || _defaultFarm();
  if (!farmId) return;
  // 동기화: whatif 농장도 맞춤
  if ($('whatif-farm-sel')) $('whatif-farm-sel').value = farmId;
  const hEl = $('growth-harvest-body'), rEl = $('growth-revenue-body');
  if (hEl) hEl.innerHTML = '<div class="spinner"></div>';
  if (rEl) rEl.innerHTML = '<div class="spinner"></div>';
  try {
    const [harv, rev] = await Promise.allSettled([
      apiFetch(`/api/farms/${farmId}/harvest`),
      apiFetch(`/api/farms/${farmId}/revenue`),
    ]);
    const h = harv.status === 'fulfilled' ? harv.value : null;
    const r = rev.status  === 'fulfilled' ? rev.value  : null;
    const fmt  = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    if (hEl) hEl.innerHTML = `
      <div class="harvest-grid">
        <div class="harvest-kpi"><div class="hk-label">예상 수확량</div>
          <div class="hk-val">${fmtF(h?.yield_kg_forecast)} <span style="font-size:12px;color:var(--muted)">kg</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">80% 신뢰구간</div>
          <div class="hk-val" style="font-size:14px">${h?.yield_q10!=null?`${fmtF(h.yield_q10)}–${fmtF(h.yield_q90)} kg`:'—'}</div></div>
        <div class="harvest-kpi"><div class="hk-label">잔여 재배일</div>
          <div class="hk-val">${h?.days_to_harvest ?? '—'} <span style="font-size:12px;color:var(--muted)">일</span></div></div>
      </div>
      <div class="harvest-note">${_esc(h?.crop_ko||'')} · 면적 ${h?.area_m2!=null?h.area_m2.toLocaleString('ko-KR')+' m²':'—'}</div>
      ${h?.confidence_grade ? (() => {
        const grade = h.confidence_grade;
        const isHigh = grade.startsWith('높음');
        const isMid  = grade.startsWith('보통');
        const badgeColor = isHigh ? '#22c55e' : isMid ? '#f59e0b' : '#94a3b8';
        const badgeBg    = isHigh ? 'rgba(34,197,94,.12)' : isMid ? 'rgba(245,158,11,.12)' : 'rgba(148,163,184,.10)';
        return `<div style="margin-top:5px;display:flex;align-items:center;gap:5px;flex-wrap:wrap">
          <span style="background:${badgeBg};color:${badgeColor};border:1px solid ${badgeColor}33;border-radius:4px;padding:2px 6px;font-size:10px;font-weight:600">모델 신뢰도: ${_esc(grade)}</span>
          ${h.mape_note ? `<span style="font-size:10px;color:var(--muted)">${_esc(h.mape_note)}</span>` : ''}
        </div>`;
      })() : ''}`;

    // ── 소득 예측 카드 (M2 수확량 × 시세 → 매출·비용·순이익) ─────────────────
    if (rEl) {
      if (!r) {
        rEl.innerHTML = `<div style="color:var(--muted);font-size:12px;padding:16px 0;text-align:center">소득 예측 조회 실패 — 잠시 후 다시 시도하세요</div>`;
      } else {
        const profit     = (r.revenue_krw ?? 0) - (r.cost_krw ?? 0);
        const pCls       = profit >= 0 ? 'positive' : 'negative';
        const confPct    = r.model_confidence != null ? Math.round(r.model_confidence * 100) : null;
        const confBar    = confPct != null
          ? `<div style="background:var(--border);border-radius:4px;height:4px;margin-top:2px">
               <div style="background:${confPct>=60?'#3ecf8e':confPct>=30?'#f5a623':'#f2645a'};width:${confPct}%;height:100%;border-radius:4px"></div>
             </div>`
          : '';
        const gateIcon   = r.model_gate_pass === true ? '✅' : r.model_gate_pass === false ? '⚠️' : '';
        const srcLabel   = r.revenue_source === 'ml_model' ? 'M3모델' : r.revenue_source === 'm2_yield_x_price' ? 'M2×시세' : '통계기반';
        const priceLabel = r.price_source === 'kamis_live' || r.price_source === 'kamis_cache' ? '🟢실시간' : '📊평균';
        const marginTxt  = r.profit_margin_pct != null ? ` · 이익률 ${r.profit_margin_pct}%` : '';
        rEl.innerHTML = `
          <div class="harvest-grid">
            <div class="harvest-kpi">
              <div class="hk-label">예상 수확량 ${gateIcon}</div>
              <div class="hk-val">${fmtF(r.yield_kg_forecast)} <span style="font-size:11px;color:var(--muted)">kg</span></div>
              ${confPct != null ? `<div style="font-size:9px;color:var(--muted);margin-top:1px">모델신뢰도 ${confPct}%</div>${confBar}` : ''}
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">시세 ${priceLabel}</div>
              <div class="hk-val">${fmt(r.price_krw_kg)} <span style="font-size:11px;color:var(--muted)">원/kg</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${_esc(r.crop_ko||'')} · ${r.area_m2!=null?r.area_m2.toLocaleString('ko-KR')+' m²':''}</div>
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">예상 매출</div>
              <div class="hk-val">${fmt(r.revenue_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${srcLabel}</div>
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">예상 비용</div>
              <div class="hk-val">${fmt(r.cost_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div>
            </div>
            <div class="harvest-kpi" style="grid-column:span 2">
              <div class="hk-label">예상 순이익</div>
              <div class="hk-val ${pCls}" style="font-size:20px">${profit>=0?'+':''}${fmt(profit)} <span style="font-size:11px">원</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${marginTxt}</div>
            </div>
          </div>
          ${r.model_gate_pass === false ? `<div style="background:rgba(242,100,90,.12);border:1px solid rgba(242,100,90,.3);border-radius:6px;padding:6px 10px;margin-top:8px;font-size:11px;color:#f2645a">⚠️ M2 수확량 모델 게이트 미통과 (MAPE ${r.model_confidence!=null?Math.round((1-r.model_confidence)*100):'-'}%대) — 통계 기준값과 블렌딩하여 표시 중. 모델 재학습 권장.</div>` : ''}`;
      }
    }
    // G4 헤더 KPI 업데이트 (실제 /harvest 응답 필드 사용)
    if (h) {
      // days_to_harvest: 남은 수확일 (있으면 표시, 없으면 planting 계산 시도)
      const daysLeft = h.days_to_harvest ?? null;
      const daysSince = h.days_since_planting ?? h.days_elapsed ?? null;
      if (daysSince != null) setText('growth-days-since', daysSince + '일');
      else if (daysLeft != null) setText('growth-days-since', 'D-' + daysLeft);
      // growth_stage: harvest 응답에 없으면 confidence_grade 기반으로 추정
      const stage = h.growth_stage_ko || h.growth_stage ||
        (h.confidence_grade ? (daysLeft != null && daysLeft < 14 ? '수확기' : '생육중') : null);
      if (stage) setText('growth-stage-label', stage);
      // ai_adjust: model_mape_pct 기반 정확도 표시
      const aiAdj = h.ai_adjust_pct ?? h.model_adjustment_pct ?? null;
      if (aiAdj != null) setText('growth-ai-adjust', (aiAdj >= 0 ? '+' : '') + aiAdj + '%');
      else setText('growth-ai-adjust', h.confidence_grade || '—'); // MAPE는 내부 지표 — 사용자에게 비노출
      if (h.yield_kg_forecast) { setText('harvest-quality-rate', '—'); const qEl=$('harvest-quality-rate'); if(qEl && !qEl.nextElementSibling?.classList.contains('kc-hint2')) { const hint=document.createElement('span'); hint.className='kc-hint kc-hint2'; hint.textContent='데이터 준비 중'; qEl.after(hint); } } // 상품과율 API 미지원
    }
    // 대시보드 hero 수확 KPI 보조 업데이트
    if (h?.yield_kg_forecast) {
      setText('harvest-7d-kg', Number(h.yield_kg_forecast).toFixed(1));
    }
  } catch(e) {
    if (hEl) hEl.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
    if (rEl) rEl.innerHTML = `<span style="color:var(--red);font-size:12px">소득 조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── What-if 시뮬레이션 ────────────────────────────────────────────────────────
function resetWhatIf() { $('whatif-result').innerHTML = ''; }

async function runWhatIf() {
  const farmId = $('whatif-farm-sel')?.value;
  if (!farmId) {
    const el = $('whatif-result');
    if (el) el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하세요']]);
    return;
  }
  const el = $('whatif-result');
  el.innerHTML = '<div class="spinner"></div>';
  const body = {};
  if ($('wi-temp')?.value) body.temp_internal  = parseFloat($('wi-temp').value);
  if ($('wi-humi')?.value) body.humidity_int   = parseFloat($('wi-humi').value);
  if ($('wi-co2')?.value)  body.co2_ppm        = parseFloat($('wi-co2').value);
  if ($('wi-ec')?.value)   body.ec_dsm         = parseFloat($('wi-ec').value);
  try {
    const d = await apiFetch(`/api/farms/${farmId}/whatif`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const fmt = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF= n => n!=null ? Number(n).toFixed(1) : '—';
    const gain     = d.profit_gain_krw ?? d.revenue_gain_krw ?? 0;
    const gainCls  = gain >= 0 ? 'pos' : 'neg';
    const scenarios= d.scenarios || [];
    let scenHtml = '';
    if (scenarios.length) {
      scenHtml = '<div style="margin-top:10px"><div style="font-size:11px;color:var(--muted);margin-bottom:6px">시나리오 비교</div>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">' +
        scenarios.map(s => {
          const sg = s.profit_gain_krw ?? s.revenue_change ?? 0;
          const sCls = sg >= 0 ? 'pos' : 'neg';
          return `<div class="wi-result-item">
            <div class="wi-label">${_esc(s.label || JSON.stringify(s.env||{}))}</div>
            <div class="wi-val ${sCls}">${sg>=0?'+':''}${fmt(sg)} 원</div>
          </div>`;
        }).join('') + '</div></div>';
    }
    el.innerHTML = `
      <div class="wi-result-grid">
        <div class="wi-result-item"><div class="wi-label">예측 수확량</div>
          <div class="wi-val">${fmtF(d.yield_kg_forecast)} kg</div></div>
        <div class="wi-result-item"><div class="wi-label">예측 매출</div>
          <div class="wi-val">${fmt(d.revenue_krw)} 원</div></div>
        <div class="wi-result-item"><div class="wi-label">수익 변화</div>
          <div class="wi-val ${gainCls}">${gain>=0?'+':''}${fmt(gain)} 원</div></div>
      </div>
      ${scenHtml}`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">시뮬레이션 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 에너지/비용: 비용 내역 조회 ───────────────────────────────────────────────
async function loadCostBreakdown() {
  const farmId = $('cost-farm-sel')?.value || _defaultFarm();
  const el = $('cost-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/costs`);
    const fmt = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const items  = d.items || d.breakdown || [];
    const total  = d.total_cost_krw ?? d.total_krw ?? d.total ?? 0;
    const perM2  = d.cost_per_m2;
    const rows = items.map(it => {
      const label = it.label_ko || it.label || it.name || it.item || '—';
      const pct   = it.pct_of_total != null ? Math.round(it.pct_of_total * 100) : null;
      const manualBadge = it.is_manual ? ' <span style="font-size:9px;color:var(--accent);border:1px solid var(--accent);border-radius:3px;padding:0 3px">실제입력</span>' : '';
      const barHtml = pct != null
        ? `<div style="height:3px;background:var(--border);border-radius:2px;margin-top:3px">
            <div style="height:3px;background:var(--accent);border-radius:2px;width:${pct}%"></div></div>` : '';
      return `<div class="cost-row" style="flex-direction:column;align-items:stretch;gap:2px">
        <div style="display:flex;justify-content:space-between">
          <span>${_esc(label)}${manualBadge}</span>
          <span style="font-weight:600">${fmt(it.amount_krw??it.amount)} 원${pct!=null?` <span style="font-size:10px;color:var(--muted)">(${pct}%)</span>`:''}</span>
        </div>
        ${it.unit_label ? `<div style="font-size:10px;color:var(--muted)">${_esc(it.unit_label)}</div>` : ''}
        ${barHtml}
      </div>`;
    }).join('');
    const hasManualBadge = d.has_manual_input
      ? '<span style="font-size:10px;color:var(--accent);border:1px solid var(--accent);border-radius:4px;padding:1px 5px;margin-left:6px">일부 실제입력</span>' : '';
    el.innerHTML = `
      <div class="cost-section">
        <div class="cost-section-title">월간 비용 분석 ${hasManualBadge}</div>
        ${rows}
        <div class="cost-row" style="margin-top:6px;border-top:1px solid var(--border);padding-top:8px">
          <span style="font-weight:600">월간 합계</span>
          <span class="cost-total">${fmt(total)} 원</span>
        </div>
        ${perM2 != null ? `<div style="font-size:11px;color:var(--muted);text-align:right;margin-top:4px">㎡당 ${Number(perM2).toFixed(1)}원</div>` : ''}
      </div>
      ${d.electricity_kwh_month != null ? `<div style="font-size:10px;color:var(--muted);margin-top:4px">전기 ${Math.round(d.electricity_kwh_month).toLocaleString('ko-KR')} kWh / 용수 ${Math.round(d.water_m3_month||0).toLocaleString('ko-KR')} m³</div>` : ''}`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 에너지/비용: 수동 비용 입력 / 삭제 ──────────────────────────────────────
function loadCostManualForm() {
  // 농장 선택 변경 시 기존 입력값 불러오기 (cost 조회 후 manual_input 필드 채우기)
  if (!_token) return; // 로그인 전 호출 방지
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) return;
  apiFetch(`/api/farms/${farmId}/costs`).then(d => {
    const mi = d.manual_input || {};
    const set = (id, key) => { const el=$(id); if(el && mi[key]!=null) el.value=mi[key]; else if(el) el.value=''; };
    set('mc-elec-kwh', 'electricity_kwh_month');
    set('mc-elec-rate','electricity_rate');
    set('mc-water-m3', 'water_m3_month');
    set('mc-water-rate','water_rate');
    set('mc-heat-kwh', 'heating_kwh_month');
    set('mc-heat-rate','heating_rate');
    set('mc-labor-hrs','labor_hours_month');
    set('mc-labor-rate','labor_rate');
    set('mc-nutr',     'nutrients_krw_month');
    set('mc-pest',     'pesticides_krw_month');
  }).catch(e => console.warn('[cost-manual-form] 기존 입력값 로드 실패:', e.message));
}

async function submitManualCost() {
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) { _setResult('cost-manual-result', 'warn', '농장을 선택하세요'); return; }
  // 구조화된 비용 입력 (ManualCostInput 스키마)
  const f = (id) => { const v = $(id)?.value; return v !== '' && v != null ? parseFloat(v) : undefined; };
  const body = {};
  const fields = [
    ['mc-elec-kwh', 'electricity_kwh_month'],
    ['mc-elec-rate','electricity_rate'],
    ['mc-water-m3', 'water_m3_month'],
    ['mc-water-rate','water_rate'],
    ['mc-heat-kwh', 'heating_kwh_month'],
    ['mc-heat-rate','heating_rate'],
    ['mc-labor-hrs','labor_hours_month'],
    ['mc-labor-rate','labor_rate'],
    ['mc-nutr',     'nutrients_krw_month'],
    ['mc-pest',     'pesticides_krw_month'],
  ];
  fields.forEach(([id, key]) => { const v = f(id); if (v !== undefined && !isNaN(v)) body[key] = v; });
  if (!Object.keys(body).length) { _setResult('cost-manual-result', 'warn', '하나 이상의 비용을 입력하세요'); return; }
  try {
    const r = await apiFetch(`/api/farms/${farmId}/costs/manual`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    _setResult('cost-manual-result', 'ok', r.message_ko || '저장 완료');
    if ($('cost-farm-sel')?.value === farmId) loadCostBreakdown();
  } catch(e) {
    _setResult('cost-manual-result', 'err', '저장 실패: ' + e.message);
  }
}

function deleteManualCost() {
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) { _setResult('cost-manual-result', 'warn', '농장을 선택하세요'); return; }
  BottomSheet.open(
    '수동 비용 항목 삭제',
    `<p style="line-height:1.7;font-size:13px"><b>${_esc(farmId)}</b> 농장의 수동 비용 항목을 <b style="color:var(--red)">모두 삭제</b>합니다.<br>이 작업은 되돌릴 수 없습니다.</p>`,
    '삭제 확인',
    async () => {
      try {
        await apiFetch(`/api/farms/${farmId}/costs/manual`, { method: 'DELETE' });
        _setResult('cost-manual-result', 'ok', '삭제 완료');
        loadCostBreakdown();
      } catch(e) { _setResult('cost-manual-result', 'err', '삭제 실패: ' + e.message); }
    }
  );
}

// ── 제어최적화: AI 권고 조회 ─────────────────────────────────────────────────
async function loadCtrlRecommendations() {
  const farmId = $('ctrl-farm-sel')?.value || _defaultFarm();
  const el = $('ctrl-reco-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/recommendations`);
    const items = d.recommendations || d.items || [];
    if (!items.length) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">현재 권고 사항이 없습니다 ✅</div>';
      return;
    }
    const { listHtml, gainHtml } = _renderRecoItems(items, farmId);
    el.innerHTML = `<div class="reco-list">${listHtml}</div>
      ${gainHtml}
      <button class="reco-apply-btn" style="margin-top:10px" data-farmid="${_esc(farmId)}" onclick="applyCtrlRecommendations(this.dataset.farmid)">✅ 권고 적용</button>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

function applyCtrlRecommendations(farmId) {
  BottomSheet.open(
    '권고 자동 제어 적용',
    `<p style="line-height:1.7;font-size:13px"><b>${_esc(farmId)}</b> 농장에 AI 권고를 적용합니다.<br>이 작업은 <b>자동 제어 명령을 발송</b>합니다.</p>`,
    '권고 적용',
    async () => {
      const btn = document.querySelector(`.reco-apply-btn[data-farmid="${farmId}"]`);
      if (btn) btn.disabled = true;
      try {
        await apiFetch(`/api/farms/${farmId}/apply`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ rank: 1, confirmed: false }),
        });
        showToast('✅ 권고 적용 요청 완료');
        loadCtrlRecommendations();
      } catch(e) {
        showToast('❌ 적용 실패: ' + e.message);
      } finally {
        if (btn) btn.disabled = false;
      }
    }
  );
}

// ── 제어최적화: 관수 데이터 입력 ─────────────────────────────────────────────
async function submitIrrigation() {
  const farmId = $('irri-farm-sel2')?.value || $('irri-farm-sel')?.value;
  if (!farmId) { const el = $('irri-result'); if(el) el.innerHTML = _nullReasonHtml([['농장 미선택','위 드롭다운에서 농장을 선택하세요']]); return; }
  const el = $('irri-result');
  const body = {
    amount_l: parseFloat($('irri-amount')?.value||'0'),
    ec_dsm:   parseFloat($('irri-ec')?.value||'0'),
    ph:       parseFloat($('irri-ph')?.value||'0'),
  };
  try {
    await apiFetch(`/api/farms/${farmId}/irrigation`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    if (el) el.innerHTML = `<span style="color:var(--green)">관수 데이터 전송 완료 (${body.amount_l}L)</span>`;
    ['irri-amount','irri-ec','irri-ph'].forEach(id => { const inp=$(id); if(inp) inp.value=''; });
  } catch(e) {
    if (el) el.innerHTML = `<span style="color:var(--red)">전송 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경설정: 현재 환경값 조회 ───────────────────────────────────────────────
async function loadCurrentEnv() {
  const farmId = $('env-view-farm')?.value || _defaultFarm();
  const el = $('env-current-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment`);
    const fmtF = (n,d=1) => n!=null ? Number(n).toFixed(d) : '—';
    const items = [
      { label:'내부온도',    val:fmtF(d.temp_internal),  unit:'°C' },
      { label:'내부습도',    val:fmtF(d.humidity_int),   unit:'%'  },
      { label:'CO₂',         val:fmtF(d.co2_ppm,0),      unit:'ppm'},
      { label:'지온',        val:fmtF(d.soil_temp),       unit:'°C' },
      { label:'EC',          val:fmtF(d.ec_dsm,2),        unit:'dS/m'},
      { label:'pH',          val:fmtF(d.ph,1),            unit:''   },
    ];
    const ts = d.timestamp ? new Date(d.timestamp).toLocaleString('ko-KR') : '';
    el.innerHTML = `
      <div class="env-kpi-grid">
        ${items.map(it=>`<div class="env-kpi-item">
          <div class="ek-label">${it.label}</div>
          <div class="ek-val">${it.val} <span style="font-size:10px;color:var(--muted)">${it.unit}</span></div>
        </div>`).join('')}
      </div>
      ${ts?`<div style="font-size:10px;color:var(--muted);margin-top:6px;text-align:right">측정시각: ${ts}</div>`:''}`;

    // G2 헤더 KPI 업데이트 (fmtF는 위에서 선언됨)
    setText('env-kpi-temp', fmtF(d.temp_internal));
    // VPD 계산 (Magnus 공식 간략)
    if (d.temp_internal != null && d.humidity_int != null) {
      const t = d.temp_internal; const rh = d.humidity_int;
      const svp = 0.6108 * Math.exp(17.27 * t / (t + 237.3));
      const vpd = svp * (1 - rh / 100);
      setText('env-kpi-vpd', vpd.toFixed(2));
    }
    setText('env-kpi-co2', fmtF(d.co2_ppm, 0));
    const solarVal = d.solar_rad ?? d.solar_radiation ?? d.solar_rad_est ?? null;
    const dli = solarVal != null ? (solarVal * 3600 / 1e6 * 8).toFixed(1) : '—';
    setText('env-kpi-dli', dli);
    // 에너지 KPI: ERP 엔드포인트에서 비동기 업데이트
    apiFetch(`/api/farms/${farmId}/erp/realtime`).then(erp => {
      const energyW = erp?.cost_breakdown?.energy_per_m2;
      setText('env-kpi-energy', energyW != null ? Math.round(energyW) + 'W/m²' : '—');
      // 피크 여부 힌트
      const hint = $('env-kpi-energy-hint');
      if (hint && erp?.peak_status) hint.textContent = erp.peak_status;
    }).catch(() => setText('env-kpi-energy', '—'));

    // 운영모드 pill 동적 업데이트 — data-mode 속성으로 해당 pill 강조
    if (d.control_mode) {
      const modeColorMap = { full_auto: 'orange', approval: 'green', advisory: '', manual: '' };
      document.querySelectorAll('#env-mode-bar [data-mode]').forEach(el => {
        const active = el.dataset.mode === d.control_mode;
        el.className = 'pill-tag' + (active ? ' ' + (modeColorMap[d.control_mode] || 'blue') : '');
        el.style.fontWeight = active ? '700' : '';
        el.style.opacity    = active ? '1'   : '0.45';
      });
    }
    // Fail-safe 상태 업데이트
    const fsEl = $('env-failsafe-pill');
    if (fsEl) {
      const fsOk = d.failsafe_status === 'ok' || d.failsafe_status == null;
      fsEl.textContent = fsOk ? 'Fail-safe 정상' : 'Fail-safe 이상';
      fsEl.className   = 'pill-tag ' + (fsOk ? 'green' : 'danger');
      fsEl.style.opacity = '1';
    }

  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경설정: 7일 기상 예보 ──────────────────────────────────────────────────
async function loadWeatherForecast() {
  const farmId = $('weather-farm-sel')?.value || _defaultFarm();
  const el = $('weather-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  // ET₀ 예보 병렬 로드
  loadWeatherEt0(farmId);
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment/weather`);
    // API 응답 구조: forecast가 배열이거나 {days:[...]} 형태이거나 d.days 배열
    const _fc = d.forecast;
    const days = Array.isArray(_fc) ? _fc
               : (_fc && Array.isArray(_fc.days) ? _fc.days
               : (Array.isArray(d.days) ? d.days : []));
    if (!days.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">예보 데이터 없음</div>'; return; }
    const rows = days.map(day => {
      // 날짜: ISO 형식 또는 YYYYMMDD 형식 처리
      let dtStr = '—';
      if (day.date) {
        const raw = String(day.date);
        // YYYYMMDD → YYYY-MM-DD 변환
        const normalized = raw.length === 8 ? `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}` : raw;
        try { dtStr = new Date(normalized).toLocaleDateString('ko-KR',{month:'numeric',day:'numeric',weekday:'short'}); }
        catch(e) { dtStr = _esc(raw); }
      }
      const sky = day.sky || day.sky_label || '';
      const icon = sky.includes('맑') ? '☀️' : sky.includes('구름') ? '⛅' : '🌧️';
      const windSpd = day.wind_spd ?? day.wind_speed;
      const fmtNum = v => v != null && !isNaN(Number(v)) ? Number(v) : null;
      const tMin = fmtNum(day.temp_min), tMax = fmtNum(day.temp_max), pProb = fmtNum(day.precip_prob);
      return `<tr>
        <td>${dtStr}</td><td>${icon} ${_esc(sky||'—')}</td>
        <td>${tMin!=null?tMin+'°':''} / ${tMax!=null?tMax+'°':'—'}</td>
        <td>${pProb!=null?pProb+'%':'—'}</td>
        <td>${windSpd!=null?Number(windSpd).toFixed(1)+' m/s':'—'}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="weather-tbl-wrap"><table class="weather-tbl">
      <thead><tr><th>날짜</th><th>날씨</th><th>기온</th><th>강수확률</th><th>풍속</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">예보 조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경: ET₀ 예보 추가 로드 ──────────────────────────────────────────────────
async function loadWeatherEt0(farmId) {
  const el = $('weather-et0-body');
  if (!el || !farmId) return;
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment/weather/forecast?days=7`);
    const et0 = d.et0_forecast_mm || [];
    if (!et0.length) { el.innerHTML = ''; return; }
    const bars = et0.map((v, i) => {
      const val = v != null ? Number(v).toFixed(1) : '?';
      const pct = Math.min(100, (Number(v) / 8) * 100);
      return `<div style="text-align:center;flex:1;min-width:36px">
        <div style="font-size:10px;color:var(--muted);margin-bottom:2px">D+${i+1}</div>
        <div style="background:rgba(79,142,247,.15);border-radius:4px;overflow:hidden;height:40px;display:flex;align-items:flex-end">
          <div style="width:100%;height:${pct}%;background:var(--accent);border-radius:4px 4px 0 0;min-height:2px"></div>
        </div>
        <div style="font-size:11px;font-weight:700;margin-top:3px;color:var(--accent)">${val}</div>
      </div>`;
    }).join('');
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <span style="font-size:11px;font-weight:700;color:var(--green)">💧 ET₀ 예보 (mm/일)</span>
        <span style="font-size:10px;color:var(--muted)">Hargreaves · ${_esc(d.source || 'open_meteo')}</span>
      </div>
      <div style="display:flex;gap:4px;align-items:flex-end">${bars}</div>`;
  } catch(e) { el.innerHTML = ''; }
}

// ── 관수: Priva ET₀ 스케줄 ────────────────────────────────────────────────────
async function loadPrivaSchedule() {
  const farmId = $('priva-farm-sel')?.value || _defaultFarm();
  const stage  = $('priva-stage-sel')?.value || 'mid';
  const size   = parseFloat($('priva-size')?.value || '100');
  const el = $('priva-sched-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(
      `/api/farms/${farmId}/irrigation/schedule/priva?growth_stage=${stage}&plant_size_pct=${size}`
    );
    const fmt1 = n => n != null ? Number(n).toFixed(1) : '—';
    const fmt0 = n => n != null ? Math.round(n) : '—';
    const phaseColors = ['#4f8ef7','#3ecf8e','#f5c842'];
    const phaseList = d.phases || [];
    const phases = phaseList.length ? phaseList.map((ph, i) => `
      <div style="background:rgba(${i===0?'79,142,247':i===1?'62,207,142':'245,200,66'},.1);border-radius:8px;padding:10px;border:1px solid rgba(${i===0?'79,142,247':i===1?'62,207,142':'245,200,66'},.3)">
        <div style="font-size:11px;font-weight:700;color:${phaseColors[i]||'var(--accent)'};margin-bottom:6px">${_esc(ph?.name_ko || 'Phase'+(i+1))} <span style="color:var(--muted);font-weight:400">${_esc(ph?.start_hhmm??'')}~${_esc(ph?.end_hhmm??'')}</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px">
          <div style="color:var(--muted)">횟수</div><div style="font-weight:700">${ph?.n_max ?? '—'}회</div>
          <div style="color:var(--muted)">회당공급</div><div style="font-weight:700">${fmt0(ph?.supply_ml)} ml</div>
          <div style="color:var(--muted)">배액목표</div><div style="font-weight:700">${fmt1(ph?.drain_target_pct)}%</div>
        </div>
      </div>`).join('')
    : '<div style="color:var(--muted);font-size:12px;padding:8px">페이즈 정보 없음</div>';
    el.innerHTML = `
      <div class="form-4col" style="gap:8px;margin-bottom:12px">
        <div class="irr-kpi"><div class="ik-label">총 관수</div><div class="ik-val">${d.n_irrigations ?? '—'}</div><div class="ik-unit">회/일</div></div>
        <div class="irr-kpi"><div class="ik-label">총 공급량</div><div class="ik-val">${fmt0(d.supply_total_ml)}</div><div class="ik-unit">ml/slab</div></div>
        <div class="irr-kpi"><div class="ik-label">ET₀</div><div class="ik-val">${fmt1(d.et0_mm)}</div><div class="ik-unit">mm</div></div>
        <div class="irr-kpi"><div class="ik-label">ETc (Kc=${fmt1(d.kc)})</div><div class="ik-val">${fmt1(d.etc_mm)}</div><div class="ik-unit">mm</div></div>
      </div>
      <div class="form-3col" style="gap:8px;margin-bottom:12px">${phases}</div>
      <div class="form-3col" style="gap:8px;font-size:11px">
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">배액 목표</div>
          <div style="font-weight:700;color:var(--green)">${fmt1(d.drain_target_pct)}%</div>
        </div>
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">P/I 교정</div>
          <div style="font-weight:700;color:${(d.pi_correction_lm2||0)>0?'var(--green)':'var(--yellow)'}">
            ${d.pi_correction_lm2 != null ? (Number(d.pi_correction_lm2)>=0?'+':'')+Number(d.pi_correction_lm2).toFixed(3)+' L/m²' : '미적용'}
          </div>
        </div>
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">증산량</div>
          <div style="font-weight:700;color:var(--accent)">${fmt1(d.transpiration_mm)} mm</div>
        </div>
      </div>
      <div style="margin-top:8px;font-size:10px;color:var(--muted)">
        🌱 ${_esc(d.crop_ko || '')} · ${_esc(d.growth_stage || stage)} · 작물크기 ${d.plant_size_pct || size}%
        ${d.note ? '· ' + _esc(d.note.slice(0,80)) : ''}
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 시스템: 모델 성능 매트릭스 ───────────────────────────────────────────────
async function loadModelPerformance() {
  const el = $('model-perf-body');
  if (!el) return;
  try {
    const farmId = _myFarmId || (_farmsData[0]?.farm_id);
    if (!farmId) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px">농장 정보 로드 후 자동 표시</div>'; return; }
    const d = await apiFetch(`/api/farms/${farmId}/system/model-performance`);

    const gradeColor = g => g === '⭐⭐⭐' ? 'var(--green)' : g === '⭐⭐' ? 'var(--yellow)' : 'var(--muted)';
    const mapeColor  = v => v <= 15 ? 'var(--green)' : v <= 30 ? 'var(--yellow)' : v <= 35 ? 'var(--orange,#f97316)' : 'var(--red)';
    const r2Color    = v => v >= 0.90 ? 'var(--green)' : v >= 0.75 ? 'var(--yellow)' : v >= 0.50 ? 'var(--orange,#f97316)' : 'var(--muted)';
    const gateIcon   = ok => ok ? '<span style="color:var(--green);font-weight:700">✓</span>' : '<span style="color:var(--red)">✗</span>';

    /* ── M1 생육 모델 — 상위 12개 ── */
    const m1 = (d.m1_growth || []).slice(0, 12);
    const m1rows = m1.map(r => `
      <tr>
        <td>${_esc(r.crop)}</td>
        <td style="font-size:11px;color:var(--muted)">${_esc(r.target||'')}</td>
        <td style="color:${r2Color(r.r2||0)}">${(r.r2||0).toFixed(3)}</td>
        <td style="color:var(--muted);font-size:11px">${r.mae!=null?r.mae:'—'}</td>
        <td>${gateIcon(r.gate_pass)}</td>
        <td style="color:${gradeColor(r.grade)}">${_esc(r.grade||'⭐')}</td>
      </tr>`).join('');

    /* ── M2 수확량 모델 ── */
    const m2 = d.m2_yield || [];
    const m2rows = m2.map(r => `
      <tr>
        <td>${_esc(r.crop)}</td>
        <td style="color:${mapeColor(r.mape_pct)};font-weight:600">${r.mape_pct}%</td>
        <td style="color:${r2Color(r.cv_r2||0)}">${(r.cv_r2||0).toFixed(3)}</td>
        <td style="color:var(--muted);font-size:11px">${r.n_samples||'?'}건</td>
        <td>${gateIcon(r.gate_pass != null ? r.gate_pass : r.mape_pct <= 35)}</td>
        <td style="color:${gradeColor(r.grade)}">${_esc(r.grade||'⭐')}</td>
      </tr>`).join('');

    /* ── M3 수익 모델 ── */
    const m3 = d.m3_revenue || [];
    const m3rows = m3.map(r => `
      <tr>
        <td>${_esc(r.crop)}</td>
        <td style="color:${mapeColor(r.mape_pct)};font-weight:600">${r.mape_pct}%</td>
        <td>${gateIcon(r.mape_pct <= 35)}</td>
        <td style="color:${gradeColor(r.grade)}">${_esc(r.grade||'⭐')}</td>
      </tr>`).join('');

    /* ── API 연결 수 ── */
    const apiTotal = Object.keys(d.api_connections||{}).length;
    const apiOk    = Object.values(d.api_connections||{}).filter(v=>v==='connected').length;

    el.innerHTML = `
      <!-- M1 성장 모델 -->
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M1 생육 모델 (R² 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: R² ≥ 0.75 ⭐⭐ / ≥ 0.90 ⭐⭐⭐</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:14px">
        <thead><tr><th>작목</th><th>지표</th><th>R²</th><th>MAE</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m1rows || '<tr><td colspan="6" style="color:var(--muted);font-size:11px;text-align:center">m1_meta.json 없음</td></tr>'}</tbody>
      </table></div>

      <!-- M2 수확량 모델 -->
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M2 수확량 예측 (MAPE 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: MAPE ≤ 15% ⭐⭐⭐ / ≤ 30% ⭐⭐ / ≤ 35% Gate통과</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:14px">
        <thead><tr><th>작목</th><th>MAPE</th><th>CV R²</th><th>샘플</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m2rows || '<tr><td colspan="6" style="color:var(--muted);font-size:11px;text-align:center">데이터 없음</td></tr>'}</tbody>
      </table></div>

      <!-- M3 수익 모델 -->
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M3 수익 예측 (MAPE 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: MAPE ≤ 15% ⭐⭐⭐ / ≤ 20% ⭐⭐</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:12px">
        <thead><tr><th>작목</th><th>MAPE</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m3rows || '<tr><td colspan="4" style="color:var(--muted);font-size:11px;text-align:center">데이터 없음</td></tr>'}</tbody>
      </table></div>

      <!-- 부가 상태 -->
      <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-top:4px">
        <span>M4 원가: 파라미터 기반 ✅</span>
        <span>M5 질병: ${_esc(d.m5_disease?.status || 'stub모드')}</span>
        <span>API 연결: ${apiOk}/${apiTotal}개</span>
        <span>생성: ${d.generated_at ? new Date(d.generated_at).toLocaleString('ko-KR') : '—'}</span>
      </div>`;

    /* ── C6 헤더 KPI 업데이트 ── */
    if (m2.length) {
      const avgR2 = m2.reduce((s, r) => s + (r.cv_r2 || 0), 0) / m2.length;
      setText('ml-avg-r2', avgR2.toFixed(3));
      const totalSamples = m2.reduce((s, r) => s + (r.n_samples || 0), 0);
      setText('ml-train-rows', totalSamples >= 1000 ? Math.round(totalSamples/1000) + 'K' : String(totalSamples));
      const gatePassCount = m2.filter(r => r.gate_pass != null ? r.gate_pass : r.mape_pct <= 35).length;
      setText('ml-data-quality', Math.round(gatePassCount / m2.length * 100) + '%');
    }
    if (d.generated_at) {
      const daysAgo = Math.round((Date.now() - new Date(d.generated_at).getTime()) / 86400000);
      setText('ml-last-train', 'D-' + daysAgo);
    } else {
      setText('ml-last-train', '—');
    }

    /* ── 대시보드 hero KPI 및 학습 상태 바 ── */
    const r2Vals = m2.map(r => r.cv_r2 || 0).filter(v => v > 0);
    if (r2Vals.length) {
      const avgR2 = r2Vals.reduce((a,b)=>a+b,0) / r2Vals.length;
      setText('kpi-r2', avgR2.toFixed(3));
      setBar('bar-learning', Math.min(100, Math.round(Math.max(0, avgR2) * 100)), 'bv-learning');
    }

  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 시스템: API 연결 상태 ─────────────────────────────────────────────────────
async function loadApiStatus() {
  const el = $('api-status-body');
  if (!el) return;
  try {
    const farmId = _myFarmId || (_farmsData[0]?.farm_id);
    if (!farmId) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px">농장 정보 로드 후 자동 표시</div>'; return; }
    const d = await apiFetch(`/api/farms/${farmId}/system/api-status`);

    // 연결 상태 테이블 (apis 객체)
    const apis = d.apis || d.api_connections || {};
    const rows = Object.entries(apis).map(([name, info]) => {
      const st = (info?.status || info || '').toString();
      const isOk = st === 'connected' || st === 'available';
      const isFallback = st === 'fallback_active';
      const isMissing = st === 'MISSING' || st.startsWith('MISSING —');
      const color = isOk ? 'var(--green)' : isFallback ? 'var(--yellow)' : isMissing ? 'var(--red)' : 'var(--yellow)';
      const icon  = isOk ? '✅' : isFallback ? '⚠️' : isMissing ? '❌' : '⚠️';
      const stLabel = isOk ? (st === 'available' ? '사용 가능' : '연결됨') : isFallback ? '폴백 동작 중' : '미설정';
      const note = info?.note ? `<br><span style="font-size:10px;color:var(--muted)">${_esc(info.note)}</span>` : '';
      const usedFor = info?.used_for ? `<br><span style="font-size:10px;color:var(--muted)">${_esc(info.used_for)}</span>` : '';
      return `<tr>
        <td>${_esc(name)}${usedFor}</td>
        <td style="color:${color};font-size:11px">${icon} ${stLabel}${note}</td>
      </tr>`;
    }).join('');

    // 미설정 API 키 발급 안내
    const missing = d.missing_keys || {};
    const _safeUrl = u => (u && /^https?:\/\//.test(u)) ? _esc(u) : '#';
    const missRows = Object.entries(missing).map(([k, v]) =>
      `<tr>
        <td style="color:var(--yellow);font-size:11px">⚠️ ${_esc(v.service)}</td>
        <td style="font-size:10px">${_esc(v.used_for)}</td>
        <td><a href="${_safeUrl(v.get_key_url)}" target="_blank" style="color:var(--accent);font-size:10px">${_esc(v.cost || '발급')}</a></td>
      </tr>`
    ).join('');

    // MCP 서버 안내
    const mcp = d.mcp_servers || {};
    const mcpRows = Object.entries(mcp).slice(0,4).map(([k, v]) =>
      `<tr><td style="font-size:11px">${_esc(v.name)}</td><td style="font-size:10px;color:var(--muted)">${_esc(v.description)}</td><td style="font-size:10px;color:${v.status==='ACTIVE'?'var(--green)':'var(--muted)'}">${_esc(v.status||'미연결')}</td></tr>`
    ).join('');

    el.innerHTML = `
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px">연결 현황</div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:10px">
        <thead><tr><th>API / 서비스</th><th>상태</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      ${missRows ? `
      <div style="font-size:11px;font-weight:700;color:var(--yellow);margin:8px 0 4px">⚠️ 미설정 API — 성능 향상 가능</div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:10px">
        <thead><tr><th>서비스</th><th>용도</th><th>발급</th></tr></thead>
        <tbody>${missRows}</tbody>
      </table></div>` : ''}
      ${mcpRows ? `
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin:8px 0 4px">🔌 MCP 서버</div>
      <div class="table-scroll-wrap"><table class="weather-tbl">
        <thead><tr><th>서버</th><th>설명</th><th>상태</th></tr></thead>
        <tbody>${mcpRows}</tbody>
      </table></div>` : ''}
      <div style="margin-top:8px;font-size:10px;color:var(--muted)">
        ✅ 무료 API (Open-Meteo·EPPO·FAO·PlantNet)는 키 없이 자동 사용 중
      </div>`;

    // C8 헤더 KPI 업데이트
    const allApis = Object.values(apis);
    const connectedCount = allApis.filter(a => {
      const s = (a?.status || a || '').toString();
      return s === 'connected' || s === 'available' || s === 'fallback_active';
    }).length;
    const fullCount = allApis.filter(a => {
      const s = (a?.status || a || '').toString();
      return s === 'connected' || s === 'available';
    }).length;
    const totalCount = allApis.length || 1;
    const connPct = Math.round(fullCount / totalCount * 100);
    setText('sys-api-conn', connPct + '%');
    setText('sys-api-hint', `${fullCount}/${totalCount} 연결 (폴백포함 ${connectedCount}개)`);
    setText('sys-ctrl-success', connPct + '%');
    const wsStatus = _wsActive ? '연결됨' : '—';
    setText('sys-sensor-conn', wsStatus);
    // 제어기 연결 상태 — API 연결률에서 추정
    setText('sys-ctrl-conn', fullCount > 0 ? '연결됨' : '—');
    setText('sys-ctrl-hint', fullCount > 0 ? `${fullCount}개 API` : '확인 필요');

  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 병해 탐지 — Plant.id + NCPMS + M5 규칙기반 ────────────────────────────────
async function loadDiseaseDetect(farmId) {
  const el = $('disease-detect-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const fid = farmId || _myFarmId || (_farmsData[0]?.farm_id);
    if (!fid) { el.innerHTML = _nullReasonHtml([['농장 미선택', '위에서 농장을 선택하면 병해 탐지 결과가 표시됩니다']]); return; }
    const d = await apiFetch(`/api/farms/${fid}/disease/detect`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:'{}' });
    const risk = d.risk_level || 'none';
    const riskColor = risk==='high'?'var(--red)':risk==='medium'?'var(--yellow)':'var(--green)';
    const riskTxt   = {high:'🔴 높음',medium:'🟡 중간',low:'🟢 낮음',none:'✅ 정상'}[risk] || '—';
    const srcBadges = (d.source_chain||[]).map(s=>`<span class="badge badge-info" style="font-size:9px">${_esc(s)}</span>`).join(' ');
    const allRisks  = (d.all_risks||[]).slice(0,4).map(r=>`
      <div style="display:flex;justify-content:space-between;padding:3px 0;font-size:11px">
        <span>${_esc(r.disease_ko || r.disease || '—')}</span>
        <span style="color:${r.risk_level==='high'?'var(--red)':r.risk_level==='medium'?'var(--yellow)':'var(--green)'}">${r.score != null ? (r.score*100).toFixed(0) : '—'}%</span>
      </div>`).join('');
    const ncpms = (d.ncpms_forecast||[]).slice(0,3).map(f=>`<div style="font-size:10px;color:var(--muted)">${_esc(f.date)} ${_esc(f.pest_ko)} ${_esc(f.level)}</div>`).join('');
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <div style="font-size:22px;font-weight:700;color:${riskColor}">${riskTxt}</div>
        <div>
          <div style="font-weight:600">${_esc(d.disease_ko||'이상 없음')}</div>
          <div style="font-size:11px;color:var(--muted)">${_esc(d.action_ko||'')}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
        ${(d.reasons||[]).map(r=>`• ${_esc(r)}`).join('<br>')}
      </div>
      ${allRisks ? `<div style="border-top:1px solid var(--border);padding-top:6px;margin-bottom:6px">${allRisks}</div>` : ''}
      ${ncpms ? `<div style="border-top:1px solid var(--border);padding-top:6px"><div style="font-size:10px;font-weight:700;color:var(--muted);margin-bottom:3px">NCPMS 발생예보</div>${ncpms}</div>` : ''}
      <div style="margin-top:8px">${srcBadges}</div>`;

    // G5 헤더 KPI 업데이트
    const riskLabel = {high:'🔴 높음', medium:'🟡 중간', low:'🟢 낮음', none:'✅ 정상'};
    setText('g5-disease-risk', riskLabel[risk] || '—');
    const topPest = (d.all_risks||[]).find(r => r.category === '해충' || r.disease_ko?.includes('응애') || r.disease_ko?.includes('진딧물'));
    setText('g5-pest-risk', topPest ? '🟡 ' + (topPest.disease_ko||'주의') : '✅ 정상');
    setText('g5-quality-risk', '보통');
    const g5hint = (d.reasons||[]).slice(0,1).join('') || 'AI 탐지 결과';
    setText('g5-disease-hint', g5hint.slice(0, 20));

  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 도매시장 가격 + 수확량 기준 ──────────────────────────────────────────────
async function loadWholesaleMarket(farmId) {
  const el = $('wholesale-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const fid = farmId || _myFarmId || (_farmsData[0]?.farm_id);
    if (!fid) { el.innerHTML = _nullReasonHtml([['농장 미선택', '농장을 선택하면 도매가격 기준이 표시됩니다']]); return; }
    const d = await apiFetch(`/api/farms/${fid}/market/wholesale`);
    const price = d.price_krw_kg ? `${Number(d.price_krw_kg).toLocaleString()}원/kg` : '—';
    const faoRef = d.fao_ref_price_krw_kg ? `FAO 기준: ${Number(d.fao_ref_price_krw_kg).toLocaleString()}원/kg` : '';
    const corr = d.m3_correction_factor ? `보정계수 ×${d.m3_correction_factor}` : '';
    const bounds = d.yield_bounds;
    const boundsHtml = bounds ? `
      <div style="background:var(--card-soft);border:1px solid var(--border);border-radius:6px;padding:8px;margin-top:8px;font-size:11px">
        <div style="font-weight:700;color:var(--muted);margin-bottom:4px">📊 수확량 합리적 범위 (M2 클리핑)</div>
        <div>${_esc(d.crop)}: <span style="color:var(--green)">${bounds.lower_kg_m2}~${bounds.upper_kg_m2} kg/m²/시즌</span></div>
        <div style="color:var(--muted);font-size:10px">${_esc(bounds.reference)} · ${_esc(d.yield_clipping_note||'')}</div>
      </div>` : '';
    const srcBadges = (d.source_chain||[]).map(s=>`<span class="badge badge-info" style="font-size:9px">${_esc(s)}</span>`).join(' ');
    el.innerHTML = `
      <div style="font-size:20px;font-weight:700;color:var(--green)">${price}</div>
      <div style="font-size:11px;color:var(--muted);margin:4px 0">${faoRef}${faoRef&&corr?' · ':''}${corr}</div>
      ${boundsHtml}
      <div style="margin-top:8px">${srcBadges}</div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경설정: 수동 환경값 입력 ───────────────────────────────────────────────
async function submitManualEnv() {
  const farmId = $('env-manual-farm')?.value;
  if (!farmId) { _setResult('env-manual-result', 'warn', '농장을 선택하세요'); return; }
  const body = {};
  const pairs = [['em-temp','temp_internal'],['em-humi','humidity_int'],
                 ['em-co2','co2_ppm'],['em-ec','ec_dsm'],['em-ph','ph'],
                 ['em-soil','soil_temp']];
  pairs.forEach(([id, key]) => { const v = $(id)?.value; if (v !== '' && v != null) body[key] = parseFloat(v); });
  if (!Object.keys(body).length) { _setResult('env-manual-result', 'warn', '입력값이 없습니다'); return; }
  try {
    await apiFetch(`/api/farms/${farmId}/environment/manual`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    _setResult('env-manual-result', 'ok', `저장 완료 (${farmId})`);
    loadCurrentEnv();
  } catch(e) {
    _setResult('env-manual-result', 'err', '저장 실패: ' + e.message);
  }
}

// ── 관수관리: 스케줄 예측 ─────────────────────────────────────────────────────
async function loadIrrigationSchedule() {
  const farmId  = $('irr-sched-farm')?.value || _defaultFarm();
  const trigger = parseFloat($('irr-trigger-mj')?.value || '2.0');
  const el = $('irr-sched-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation/schedule?trigger_mj_m2=${trigger}`);
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    // G3 헤더 KPI — 관수횟수
    if (d.n_irrigations != null) setText('irr-count-today', d.n_irrigations);
    el.innerHTML = `
      <div class="irr-sched-grid">
        <div class="irr-kpi"><div class="ik-label">관수 횟수</div>
          <div class="ik-val">${d.n_irrigations ?? '—'}</div><div class="ik-unit">회/일</div></div>
        <div class="irr-kpi"><div class="ik-label">총 공급량</div>
          <div class="ik-val">${d.total_supply_ml != null ? Math.round(d.total_supply_ml) : '—'}</div><div class="ik-unit">ml/slab</div></div>
        <div class="irr-kpi"><div class="ik-label">GSR (전일)</div>
          <div class="ik-val">${fmtF(d.daily_gsr_mj_m2)}</div><div class="ik-unit">MJ/m²</div></div>
      </div>
      <div class="irr-timeline" style="margin-top:12px">
        <div class="irr-time-dot"></div>
        <span style="font-weight:700">첫 관수</span>
        <span style="color:var(--accent);font-size:16px;font-weight:700">${_esc(d.first_irrigation ?? '—')}</span>
        <span style="color:var(--muted)">→</span>
        <span style="font-weight:700">마지막 관수</span>
        <span style="color:var(--accent);font-size:16px;font-weight:700">${_esc(d.last_irrigation ?? '—')}</span>
      </div>
      <div style="margin-top:8px;font-size:11px;color:var(--muted)">
        📡 ${d.source === 'kma_asos_yesterday' ? 'ASOS 전일 실측 기반' : '계절 평균 기반'} — ${_esc(d.note ?? '')}
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function submitIrrigationP4() {
  const farmId    = $('irri-farm-sel2')?.value;
  const supply    = parseFloat($('irri-supply')?.value || '0');
  const drain     = parseFloat($('irri-drain')?.value || '0');
  const ec        = parseFloat($('irri-ec2')?.value || '0');
  const maxWt     = parseFloat($('irri-maxwt')?.value || '0');
  const sunsetWt  = parseFloat($('irri-sunsetwt')?.value || '0');
  const uptake    = parseFloat($('irri-uptake')?.value || '0');
  if (!farmId) { _setResult('irri-result2', 'warn', '농장을 선택하세요'); return; }
  if (!supply) { _setResult('irri-result2', 'warn', '공급량을 입력하세요'); return; }

  const dateVal = $('irri-date')?.value || new Date().toISOString().slice(0,10);
  // API에 맞게 periods 형식 구성 (단일 구간으로 요약)
  const body = {
    crop: _farmsData.find(f=>f.farm_id===farmId)?.crop_ko || '알 수 없음',
    date: dateVal,
    slab_vol_l: 15.0,
    max_wt_kg:    maxWt   || null,
    sunset_wt_kg: sunsetWt || null,
    periods: [{ period: 2, supply_ml: supply, drain_ml: drain, ec: ec||null, slab_wt_kg: null }],
  };
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    const s = d.summary || {};
    const drPct = s.dr_pct_mean != null ? s.dr_pct_mean.toFixed(1) : '—';
    const wcMean= s.wc_mean != null ? s.wc_mean.toFixed(1) : '—';
    _setResult('irri-result2', 'ok', `저장 완료 — 배액률 ${drPct}%, 함수율 ${wcMean}%`);
    // 저장 후 서버 분석 결과 자동 로드 (GET /irrigation/analysis)
    loadIrrigationAnalysis(farmId);
  } catch(e) {
    _setResult('irri-result2', 'err', '저장 실패: ' + e.message);
  }
}

function renderIrrigationAnomalies(metrics) {
  const el = $('irr-anomaly-body');
  if (!el) return;
  const alerts = [];
  const checks = [
    { key:'dr_pct_mean',  label:'배액률',  unit:'%',    norm:[20,40], crit:[10,55] },
    { key:'nl_pct',       label:'야간소실률', unit:'%',  norm:[3,7],  crit:[1,10]  },
    { key:'uptake_efficiency_ml_j', label:'흡수효율', unit:'ml/J', norm:[1.0,2.5], crit:[0.7,3.0] },
  ];
  checks.forEach(c => {
    const v = metrics[c.key];
    if (v == null || isNaN(v)) return;
    let sev = null, dir = '';
    if (v < c.crit[0] || v > c.crit[1]) { sev = 'critical'; dir = v < c.crit[0] ? '너무 낮음' : '너무 높음'; }
    else if (v < c.norm[0] || v > c.norm[1]) { sev = 'major'; dir = v < c.norm[0] ? '낮음' : '높음'; }
    if (sev) alerts.push({ sev, label: c.label, val: v.toFixed(2), unit: c.unit,
      range: `정상 ${c.norm[0]}~${c.norm[1]}${c.unit}`, dir });
  });
  if (!alerts.length) {
    el.innerHTML = '<div style="color:var(--green);font-size:12px;padding:12px 0;text-align:center">✅ 관수 지표 정상 범위</div>';
    return;
  }
  el.innerHTML = '<div class="irr-anomaly-list">' + alerts.map(a =>
    `<div class="irr-alert-row ${a.sev}">
      <span>${a.sev==='critical'?'🔴':'🟡'}</span>
      <div><strong>${a.label}</strong> ${a.val}${a.unit} — ${a.range} <span style="color:var(--muted)">${a.dir}</span></div>
    </div>`
  ).join('') + '</div>';
}

function checkIrrigationAnomalies() {
  // 선택된 농장이 있으면 서버 분석 우선, 없으면 로컬 계산
  const farmId = $('irri-farm-sel2')?.value;
  if (farmId) { loadIrrigationAnalysis(farmId); return; }
  const s = parseFloat($('irri-supply')?.value||'0');
  const d = parseFloat($('irri-drain')?.value||'0');
  const m = parseFloat($('irri-maxwt')?.value||'0');
  const sw= parseFloat($('irri-sunsetwt')?.value||'0');
  renderIrrigationAnomalies({
    dr_pct_mean: s>0 ? d/s*100 : null,
    nl_pct: m>0&&sw>0 ? (m-sw)/m*100 : null,
  });
}

async function loadIrrigationAnalysis(farmId) {
  const el = $('irr-anomaly-body');
  if (!el || !farmId) return;
  el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px 0">분석 중…</div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation/analysis?days=7`);
    if (!d.data_days) {
      el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px 0;text-align:center">저장된 관수 데이터 없음</div>';
      return;
    }
    // 알림 표시
    if (d.alerts && d.alerts.length) {
      el.innerHTML = '<div class="irr-anomaly-list">' + d.alerts.map(a =>
        `<div class="irr-alert-row ${a.severity === 'major' ? 'major' : 'minor'}">
          <span>${a.severity === 'major' ? '🟡' : 'ℹ️'}</span>
          <div><strong>${_esc(a.label_ko)}</strong> — ${_esc(a.message_ko)}</div>
        </div>`
      ).join('') + '</div>';
    } else {
      el.innerHTML = '<div style="color:var(--green);font-size:12px;padding:8px 0;text-align:center">✅ 최근 7일 관수 지표 정상</div>';
    }
    // 요약 지표 표
    const sm = d.summary || {};
    const rows = ['wc_mean','dr_pct_mean','ec_drain','nl_pct'].map(k => {
      const v = sm[k];
      if (!v) return '';
      const statusColor = v.status === 'normal' ? 'var(--green)' : v.status === 'high' ? 'var(--red)' : 'var(--yellow)';
      return `<tr>
        <td style="color:var(--muted)">${_esc(v.label_ko)}</td>
        <td style="text-align:right;font-weight:600;color:${statusColor}">${_esc(String(v.latest))}${_esc(v.unit)}</td>
        <td style="text-align:right;color:var(--muted);font-size:10px">${_esc(String(v.avg))}${_esc(v.unit)} (7일평균)</td>
      </tr>`;
    }).filter(Boolean).join('');
    if (rows) {
      el.innerHTML += `<div class="table-scroll-wrap"><table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px">${rows}</table></div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">데이터: ${d.data_days}일 (${_esc(d.start||'')}~${_esc(d.end||'')})</div>`;
    }
    // G3 헤더 KPI 업데이트
    if (d.data_days)    setText('irr-count-today', d.avg_daily_count != null ? d.avg_daily_count : (d.total_count != null ? Math.round(d.total_count / d.data_days) : '—'));
    if (sm.dr_pct_mean) setText('irr-drain-rate', (sm.dr_pct_mean.latest||'—') + '%');
    if (sm.ec_drain)    setText('irr-drain-ec',   (sm.ec_drain.latest||'—') + ' dS/m');
    if (sm.ph_supply)   setText('irr-supply-ph',  sm.ph_supply.latest||'—');
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '관수 이상 감지 조회 실패');
  }
}

// ── 환경: 이상 감지 조회 ──────────────────────────────────────────────────────
async function loadEnvAnomalies() {
  const farmId = $('env-anomaly-farm')?.value || _defaultFarm();
  const el = $('env-anomaly-body');
  if (!el) return;
  if (!farmId) {
    el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하면 알림·권고 내역이 표시됩니다']]);
    return;
  }
  // select에 option이 아직 없으면 fallback으로 채우기
  const sel = $('env-anomaly-farm');
  if (sel && !sel.value && farmId) {
    const opt = document.createElement('option');
    opt.value = farmId; opt.text = farmId; opt.selected = true;
    sel.appendChild(opt);
  }
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment`);
    // environment API는 flat 구조: temp_internal, humidity_int 등 직접 포함
    const alerts = d.alerts || d.anomalies || [];

    // 환경 값 자체가 없으면 이유 표시 (flat 구조 기준: temp_internal 존재 여부로 판단)
    const noEnvData = d.temp_internal == null && d.humidity_int == null;

    if (!alerts.length) {
      if (noEnvData) {
        el.innerHTML = _nullReasonHtml([
          ['환경 센서 수치', 'IoT 센서가 미연결이거나 최근 데이터가 수집되지 않았습니다'],
          ['알림 내역', 'IoT 환경 데이터가 없으면 이상 감지 알고리즘이 동작하지 않습니다'],
        ]);
      } else {
        el.innerHTML = '<div style="display:flex;align-items:center;gap:8px;padding:14px 0;font-size:12px">' +
          '<span class="status-badge good">✅ 정상</span>' +
          '<span style="color:var(--muted)">모든 환경 지표 이상 없음</span></div>';
      }
      return;
    }
    el.innerHTML = '<div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">' +
      alerts.map(a => {
        const sev = a.severity || 'minor';
        const cls  = sev === 'critical' ? 'var(--red)' : sev === 'major' ? 'var(--yellow)' : 'var(--accent)';
        const badgeCls = sev === 'critical' ? 'danger' : sev === 'major' ? 'warn' : 'info';
        const badgeTxt = sev === 'critical' ? '🚨 위험' : sev === 'major' ? '⚠️ 주의' : '💡 참고';
        const valStr = a.current_value != null ? (Number(a.current_value) % 1 === 0 ? Number(a.current_value) : Number(a.current_value).toFixed(2)) : '—';
        return `<div style="padding:8px 12px;border-radius:7px;border-left:3px solid ${cls};background:var(--card-soft);font-size:12px">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
            <span class="status-badge ${badgeCls}">${badgeTxt}</span>
            <span style="font-weight:600">${_esc(a.variable_ko || a.variable)}</span>
            <span style="color:${cls};font-weight:700">${_esc(valStr)}${_esc(a.unit||'')}</span>
          </div>
          <div style="color:var(--muted)">${_esc(a.message_ko || '')}</div></div>`;
      }).join('') + '</div>';
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '환경 이상감지 조회 실패');
  }
}

// ── ERP 실시간 원가·마진 (SFROP v2.0 혁신④) ──────────────────────────────────
// ── C3 통합 홈 — Hero 배너 + To-do + AI 3유형 바 로드 ─────────────────────────
async function loadHeroDashboard(farmId) {
  if (!farmId) return;
  const fmt = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
  const fmtF = n => n != null ? Number(n).toFixed(1) : '—';

  // ERP → Hero KPI 배너
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const mc = (d.margin_per_kg ?? 0) > 0 ? '#22c55e' : '#ef4444';
    setText('hero-cost',   fmt(d.cost_per_kg));
    setText('hero-cost-hint', `원/kg${d.growth_stage ? ' · '+d.growth_stage : ''}`);
    setText('hero-margin', fmt(d.margin_per_kg));
    const marginHint = d.harvest_timing?.diff > 300 ? '내일 출하 유리 ↑' : '오늘 출하 기준';
    setText('hero-margin-hint', marginHint);
    const incRate = fmtF(d.income_rate_pct);
    setText('hero-income', incRate !== '—' ? incRate + '%' : '—');
    const el = $('hero-income');
    if (el) el.style.color = (d.income_rate_pct ?? 0) >= 50 ? '#22c55e' : (d.income_rate_pct ?? 0) >= 30 ? '#f59e0b' : '#ef4444';

    // C5 헤더 KPI 동시 업데이트
    setText('c5-cost-kg',   fmt(d.cost_per_kg));
    setText('c5-margin-kg', fmt(d.margin_per_kg));
    setText('c5-income-rate', incRate !== '—' ? incRate + '%' : '—');
    setText('c5-breakeven',  fmt(d.breakeven_kg));
    setText('c5-cost-hint',   d.growth_stage || '원/kg');

    // 공동출하 비교표 — ERP 물류비 우선, 없으면 기본값
    const ht = d.harvest_timing || {};
    const mktP    = d.market_price_per_kg ?? 0;
    const poolFac = d.pool_price_factor   ?? 1.083; // API가 계수를 내려주면 사용
    const indLog  = d.logistics_cost_ind  ?? 320;
    const poolLog = d.logistics_cost_pool ?? 210;
    const costKg  = d.cost_per_kg ?? 0;
    const poolPrice = Math.round(mktP * poolFac);
    setText('c5-ind-price',      fmt(mktP));
    setText('c5-pool-price',     fmt(poolPrice));
    setText('c5-ind-logistics',  indLog  + '원');
    setText('c5-pool-logistics', poolLog + '원');
    const indMgn  = Math.round(mktP    - costKg - indLog);
    const poolMgn = Math.round(poolPrice - costKg - poolLog);
    // 마진: 음수도 표시 (개별 대비 비교 정보가 필요하므로)
    setText('c5-ind-margin',  indMgn  !== 0 ? fmt(indMgn)  + '원' : '0원');
    setText('c5-pool-margin', poolMgn !== 0 ? fmt(poolMgn) + '원' : '0원');
    const effect = poolMgn - indMgn;
    setText('c5-pool-effect', effect !== 0 ? (effect > 0 ? '+' : '') + fmt(effect) + '원/kg' : '동일');

    // 원가 구조 바 (ERP 비용구성 기반)
    const cb = d.cost_breakdown || {};
    const total = cb.total_per_m2 || 1;
    const ePct  = Math.round((cb.energy_per_m2  || 0) / total * 100);
    const lPct  = Math.round((cb.labor_per_m2   || 0) / total * 100);
    const nPct  = Math.round((cb.nutrient_per_m2|| 0) / total * 100);
    const lgPct = Math.max(0, 100 - ePct - lPct - nPct);
    setBar('cost-bar-energy',    ePct,  'cost-pct-energy');
    setBar('cost-bar-labor',     lPct,  'cost-pct-labor');
    setBar('cost-bar-material',  nPct,  'cost-pct-material');
    setBar('cost-bar-logistics', lgPct, 'cost-pct-logistics');

    // G6 수확 KPI (7일 예측 사용)
    if (d.harvest_7d_kg != null) {
      setText('harvest-7d-kg', fmt(d.harvest_7d_kg));
      // poolMgn은 위 공동출하 비교표 블록에서 이미 계산됨
      setText('harvest-pool-margin', poolMgn !== 0 ? fmt(poolMgn) + '원/kg' : '—');
    }

    // 헤더 모드 pill 업데이트
    const modeEl = $('hero-mode-pill');
    if (modeEl && d.control_mode) {
      const heroModeMap = { manual:'수동보조', advisory:'권고형', approval:'승인형 자동제어', full_auto:'완전자동' };
      modeEl.textContent = heroModeMap[d.control_mode] || d.control_mode;
    }

  } catch(e) { /* hero는 선택적 — 실패해도 계속 */ }

  // AI 권고 → To-do 목록 + AI 3유형 바
  try {
    const r = await apiFetch(`/api/farms/${farmId}/recommendations`);
    const recs = r.recommendations || r.items || r || [];
    if (!Array.isArray(recs) || !recs.length) return;

    // To-do 목록 구성
    // RecommendationItem 필드: rank, action_ko, profit_delta, confidence, tier_action, canonical_changes
    const TIER_BTN  = { auto: '', approval_required: 'orange', checklist: 'blue' };
    const TIER_LABEL= { auto: '적용', approval_required: '승인', checklist: '확인' };
    const colors = ['','blue','orange','red'];
    const todoHtml = recs.slice(0, 5).map((rec, i) => {
      const cls      = colors[i % colors.length];
      const tierKey  = rec.tier_action || 'checklist';
      const act      = TIER_BTN[tierKey]  || 'blue';
      const btnLabel = TIER_LABEL[tierKey] || '확인';
      const profit   = rec.profit_delta != null ? `+${Math.round(rec.profit_delta).toLocaleString('ko-KR')}원` : '';
      const destSection = tierKey === 'auto' ? 'environ' : 'control';
      return `<div class="todo-item">
        <div class="todo-num ${cls}">${i+1}</div>
        <div class="todo-text"><b>${_esc(rec.action_ko || '권고')}</b><span>${profit}</span></div>
        <button class="todo-action ${act}" onclick="showSection('${destSection}')">${btnLabel}</button>
      </div>`;
    }).join('');
    const tb = $('todo-body');
    if (tb) tb.innerHTML = todoHtml;
    setText('todo-meta', `AI 생성 ${recs.length}건`);

    // AI 3유형 바 계산 (tier_action 기반)
    // immediate → auto, growth → checklist(생육관련), profit → approval_required or 수익관련
    const immediate = recs.filter(r => r.tier_action === 'auto').length;
    const growth    = recs.filter(r => r.tier_action === 'checklist').length;
    const profit    = recs.filter(r => r.tier_action === 'approval_required').length;
    const maxN = Math.max(immediate, growth, profit, 1);
    const iPct = Math.round(immediate / maxN * 100);
    const gPct = Math.round(growth    / maxN * 100);
    const pPct = Math.round(profit    / maxN * 100);
    setBar('bar-immediate', iPct, 'bv-immediate', immediate+'건');
    setBar('bar-growth-s',  gPct, 'bv-growth',   growth+'건');
    setBar('bar-profit',    pPct, 'bv-profit',   profit+'건');

    const topRec = recs[0];
    setText('ai-reco-explain', '');
    const exEl = $('ai-reco-explain');
    if (exEl && topRec) exEl.innerHTML = `<b>추천:</b> ${_esc(topRec.action_ko || '')}`;
  } catch(e) {
    // AI 권고 없어도 Hero는 표시됨
    const tb = $('todo-body');
    if (tb) tb.innerHTML = `<div class="todo-item"><div class="todo-num">!</div><div class="todo-text"><b>AI 권고 조회 실패</b><span>${_esc(e.message)||'서버 연결 확인'}</span></div><button class="todo-action gray">재시도</button></div>`;
  }
}

function setText(id, val) { const el = $(id); if (el) el.textContent = val; }
function setBar(barId, pct, valId, label) {
  const b = $(barId); if (b) b.style.width = Math.min(100, pct) + '%';
  if (valId) { const v = $(valId); if (v) v.textContent = label != null ? label : pct + '%'; }
}

async function loadERPRealtime() {
  const farmId = $('erp-farm-sel')?.value || _defaultFarm();
  const el = $('erp-realtime-body');
  if (!el) return;
  if (!farmId) {
    el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하면 실시간 원가·마진이 표시됩니다']]);
    return;
  }
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const fmt  = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    const cb   = d.cost_breakdown || {};
    const ht   = d.harvest_timing || {};
    const incomeColor = (d.income_rate_pct ?? 0) >= 40 ? 'var(--green)' : (d.income_rate_pct ?? 0) >= 20 ? 'var(--yellow)' : 'var(--red)';
    const marginColor = (d.margin_per_kg ?? 0) > 0 ? 'var(--green)' : 'var(--red)';
    const adviceColor = (ht.diff ?? 0) > 300 ? 'var(--green)' : (ht.diff ?? 0) < -200 ? 'var(--yellow)' : 'var(--muted)';

    // 손익분기 달성률 (월 예상 수확량 기준)
    const beKg = d.breakeven_kg ?? 0;
    // ERP가 월 예상 수확량을 내려주면 사용, 없으면 면적 × 기본 수율로 추정
    const _DEFAULT_YIELD_KG_M2_MONTH = 3.0;
    const estKg = d.yield_kg_month ?? ((d.area_m2 ?? 0) * _DEFAULT_YIELD_KG_M2_MONTH);
    const bePct = beKg > 0 && estKg > 0 ? Math.min(100, Math.round(estKg / beKg * 100)) : 0;
    const barFilled = Math.round(bePct / 10);
    const barHtml = '■'.repeat(barFilled) + '□'.repeat(10 - barFilled);

    const led = d.led_spectrum || {};
    const stageHtml = d.growth_stage
      ? `<span style="font-size:11px;color:var(--accent);border:1px solid var(--accent);border-radius:4px;padding:2px 8px;margin-left:8px">${_esc(d.growth_stage)}</span>`
      : '';

    // ── null 값 원인 분석 ──────────────────────────────────────────────────
    const nullReasons = [];
    if (d.market_price_per_kg == null || d.market_price_per_kg === 0)
      nullReasons.push(['KAMIS 도매가', 'KAMIS API 키 미설정 — 작목별 연평균 기본가 사용 중']);
    if (d.cost_per_kg == null || d.cost_per_kg === 0)
      nullReasons.push(['kg당 원가', '수확량이 0이거나 작목별 기본 원가 미적용 상태']);
    if (!d.growth_stage)
      nullReasons.push(['작기단계', '정식일 미등록 — 농가 메타 설정에서 정식월을 입력하세요']);

    el.innerHTML = `
      <div class="form-3col" style="gap:10px;margin-bottom:12px">
        <div class="profit-kpi">
          <div class="pk-label">kg당 원가</div>
          <div class="pk-val">${fmt(d.cost_per_kg)} <span style="font-size:11px">원</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">KAMIS 도매가</div>
          <div class="pk-val">${fmt(d.market_price_per_kg)} <span style="font-size:11px">원</span></div>
          ${d.market_price_per_kg > 0 ? '' : '<div class="data-ok-hint">기본 평균가 적용 중</div>'}
        </div>
        <div class="profit-kpi">
          <div class="pk-label">kg당 마진</div>
          <div class="pk-val" style="color:${marginColor}">${fmt(d.margin_per_kg)} <span style="font-size:11px">원</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">소득률</div>
          <div class="pk-val" style="color:${incomeColor}">${fmtF(d.income_rate_pct)}<span style="font-size:13px">%</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">손익분기점</div>
          <div class="pk-val">${fmt(beKg)} <span style="font-size:11px">kg</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">달성률 추정</div>
          <div class="pk-val" style="font-size:14px">${bePct}%</div>
          <div style="font-size:10px;color:var(--accent);letter-spacing:1px;margin-top:2px">${barHtml}</div>
        </div>
      </div>
      <div style="border-top:1px solid var(--border);padding-top:10px;margin-bottom:8px">
        <div style="font-size:11px;color:var(--muted);margin-bottom:6px">원가 구성 (원/m²/월)</div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
          <span>⚡ 에너지 <strong>${fmt(cb.energy_per_m2)}</strong></span>
          <span>🌿 양액·자재 <strong>${fmt(cb.nutrient_per_m2)}</strong></span>
          <span>👷 노동 <strong>${fmt(cb.labor_per_m2)}</strong></span>
          <span>🌱 종묘 <strong>${fmt(cb.seed_per_m2)}</strong></span>
          <span style="color:var(--accent)">합계 <strong>${fmt(cb.total_per_m2)}</strong></span>
        </div>
      </div>
      <div style="background:var(--green-soft);border-radius:8px;padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="font-size:13px">💡 출하 타이밍</span>
        ${stageHtml}
        <span style="color:${adviceColor};font-weight:600;font-size:13px">${_esc(ht.advice || '—')}</span>
        <span style="font-size:11px;color:var(--muted);margin-left:auto">오늘 ${fmt(ht.today_margin)}원 → 내일 ${fmt(ht.tomorrow_margin_est)}원</span>
      </div>
      ${led.ratio_str ? `<div style="margin-top:8px;font-size:11px;color:var(--muted)">💡 LED 권장 (${_esc(d.growth_stage)}): <strong style="color:var(--accent)">${_esc(led.ratio_str)}</strong> — ${_esc(led.effect || '')}</div>` : ''}
      ${_nullReasonHtml(nullReasons)}
    `;
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, 'ERP 원가·마진 조회 실패');
  }
}

// ── LED 스펙트럼 동적 강조 (SFROP v2.0 혁신③) ────────────────────────────────
async function loadLEDSpectrum() {
  const farmId = $('led-farm-sel')?.value || _defaultFarm();
  const el = $('led-current-stage');
  if (!farmId || !el) return;
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const stage = d.growth_stage || '';
    const led   = d.led_spectrum || {};
    if (!stage) { el.innerHTML = ''; return; }

    const stageRow = {
      '발아·정식기': 0, '영양생장기': 1, '착화·착과기': 2, '성숙·수확기': 3,
    };
    // 테이블 행 강조 초기화
    const tbody = document.querySelectorAll('#led-spectrum-body tbody tr');
    tbody.forEach((row, i) => {
      row.style.background = i === stageRow[stage]
        ? 'rgba(79,142,247,0.12)' : (i % 2 === 1 ? 'var(--card-soft)' : '');
      row.style.outline = i === stageRow[stage] ? '1px solid rgba(79,142,247,0.4)' : '';
    });

    el.innerHTML = `
      <div style="background:rgba(79,142,247,0.1);border:1px solid rgba(79,142,247,0.35);border-radius:8px;padding:10px 14px;margin-top:4px">
        <div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:4px">📍 현재 단계: ${_esc(stage)}</div>
        <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:12px">
          <span>🔴 적색 <strong>${led.red ?? '—'}%</strong></span>
          <span>🔵 청색 <strong>${led.blue ?? '—'}%</strong></span>
          <span>🟣 UV <strong>${led.uv ?? '—'}%</strong></span>
          <span style="color:var(--muted)">비율: <strong>${_esc(led.ratio_str || '—')}</strong></span>
        </div>
        <div style="font-size:11px;color:var(--green);margin-top:4px">✅ ${_esc(led.effect || '')}</div>
        ${led.note ? `<div style="font-size:10px;color:var(--muted);margin-top:2px">${_esc(led.note)}</div>` : ''}
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:11px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── SFROP v2.0 — 4개 시나리오 비교 ──────────────────────────────────────────
async function loadSfropScenarios() {
  const farmId = $('sfrop-farm-sel')?.value || _defaultFarm();
  const el = $('sfrop-scenario-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    // ERP 실시간 데이터를 기반으로 4개 시나리오 로컬 계산
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const base = {
      name: '현재기준',
      energy_idx: 100, brix: 9.2, yield_idx: 100,
      income: d.income_rate_pct ?? 50,
      cost_per_kg: d.cost_per_kg ?? 0,
      margin_per_kg: d.margin_per_kg ?? 0,
    };
    const scenarios = [
      { ...base },
      {
        name: '생육최적화', icon: '🌱',
        energy_idx: 95, brix: 9.8, yield_idx: 116,
        income: Math.min(99, base.income * 1.12),
        cost_per_kg: Math.round(base.cost_per_kg * 0.96),
        margin_per_kg: Math.round(base.margin_per_kg * 1.12),
        tip: 'LED 스펙트럼 최적화 + CO₂ 800ppm 유지',
      },
      {
        name: '에너지최적화', icon: '⚡',
        energy_idx: 65, brix: 9.1, yield_idx: 97,
        income: Math.min(99, base.income * 1.08),
        cost_per_kg: Math.round(base.cost_per_kg * 0.82),
        margin_per_kg: Math.round(base.margin_per_kg * 1.08),
        tip: '야간 보온 강화 + 인버터 제어 최적화',
      },
      {
        name: 'AI통합최적화', icon: '🤖',
        energy_idx: 63, brix: 10.1, yield_idx: 119,
        income: Math.min(99, base.income * 1.21),
        cost_per_kg: Math.round(base.cost_per_kg * 0.80),
        margin_per_kg: Math.round(base.margin_per_kg * 1.21),
        tip: 'SFROP v2.0 전체 권고 적용 시 최적 상태',
      },
    ];
    const fmtN = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';

    const cols = scenarios.map((s, i) => {
      const isBase = i === 0;
      const isBest = i === 3;
      const border = isBest ? '2px solid var(--accent)' : '1px solid var(--border)';
      const bg     = isBest ? 'var(--green-soft)' : 'var(--card-soft)';
      const gainM  = s.margin_per_kg - base.margin_per_kg;
      const gainI  = s.income - base.income;
      const gainColor = gainM > 0 ? 'var(--green)' : gainM < 0 ? 'var(--red)' : 'var(--muted)';
      return `
        <div style="border:${border};border-radius:10px;background:${bg};padding:14px;text-align:center">
          <div style="font-size:13px;font-weight:700;margin-bottom:10px;color:${isBest?'var(--accent)':'var(--text)'}">${s.icon||'📊'} ${s.name}</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">에너지 지수</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.energy_idx}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">당도 (Brix)</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.brix}</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">수확량 지수</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.yield_idx}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">소득률</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${fmtF(s.income)}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">kg당 마진</div>
          <div style="font-size:15px;font-weight:700;color:${gainColor};margin-bottom:8px">
            ${fmtN(s.margin_per_kg)} 원
            ${!isBase ? `<div style="font-size:11px">(${gainM>=0?'+':''}${fmtN(gainM)})</div>` : ''}
          </div>
          ${s.tip ? `<div style="font-size:10px;color:var(--muted);margin-top:4px;padding:6px;border-top:1px solid var(--border)">${s.tip}</div>` : ''}
        </div>`;
    }).join('');

    el.innerHTML = `
      <div class="form-4col" style="gap:10px;margin-top:4px">
        ${cols}
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:8px;text-align:right">
        * 시나리오 수치는 RDA 2022 실태조사 기반 추정값 · ERP 실시간 데이터 반영
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">시나리오 계산 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 생산/유통: KAMIS 가격 현황 ───────────────────────────────────────────────
async function loadMarketPrices() {
  const el = $('market-prices-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch('/api/admin/prices/latest');
    const prices = d.prices || d.data || (Array.isArray(d) ? d : []);
    if (!prices.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:16px">가격 데이터 없음</div>'; return; }
    const rows = prices.map(p => {
      const chg = p.change_pct ?? p.change_rate ?? null;
      const chgHtml = chg != null
        ? `<span class="${chg>=0?'price-up':'price-down'}">${chg>=0?'+':''}${Number(chg).toFixed(1)}%</span>` : '—';
      const priceVal = p.price_krw_kg ?? p.price_krw ?? p.price;
      const dateVal  = p.regday || p.base_date || p.date || p.updated_at;
      return `<tr>
        <td>${_esc(p.crop_ko || p.crop || '—')}</td>
        <td>${priceVal != null ? Math.round(priceVal).toLocaleString('ko-KR') : '—'} 원/kg</td>
        <td>${chgHtml}</td>
        <td style="color:var(--muted)">${dateVal ? dateVal.substring(0,10) : '—'}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="table-scroll-wrap"><table class="price-hist-table">
      <thead><tr><th>작목</th><th>시세</th><th>전일비</th><th>기준일</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
    // C12 공동출하 헤더 KPI 업데이트 (KAMIS 가격 기반 추정)
    const poolPrices = prices.filter(p => p.price_krw_kg != null);
    if (poolPrices.length) {
      const avgP = Math.round(poolPrices.reduce((s,p)=>s+(p.price_krw_kg||0),0)/poolPrices.length);
      setText('pool-avg-price', avgP.toLocaleString('ko-KR')+'원/kg');
      setText('pool-volume-7d', '—');           // 실측 집계 데이터 없음 — API 연동 시 업데이트
      setText('pool-quality-rate', '특·상 —%'); // 품위 비율: 출하 실적 연동 예정
      setText('pool-farm-count', _farmsData.length || '—');
      setText('pool-farm-approved', '등록 '+(_farmsData.length||'—')+'개');
      // pool-margin-vs-ind: 전주 가격 대비 현재가 변화율 계산
      const curAvg  = poolPrices.reduce((s,p)=>s+(p.price_krw_kg||0),0) / poolPrices.length;
      const prevAvg = poolPrices.reduce((s,p)=>s+(p.prev_price_krw_kg || p.price_krw_kg || 0),0) / poolPrices.length;
      const marginPct = prevAvg > 0 ? ((curAvg - prevAvg) / prevAvg * 100) : null;
      setText('pool-margin-vs-ind', marginPct != null ? (marginPct >= 0 ? '+' : '') + marginPct.toFixed(1) + '%' : '—');
      // pool-price-change: 전주 대비 가격 변화 금액
      const priceDiff = Math.round(curAvg - prevAvg);
      setText('pool-price-change', prevAvg > 0 ? (priceDiff >= 0 ? '+' : '') + priceDiff.toLocaleString('ko-KR') + '원' : '전주 대비');
      // pool-table-body 샘플 데이터
      const tbEl = $('pool-table-body');
      if (tbEl && tbEl.innerHTML.includes('갱신 중')) {
        tbEl.innerHTML = poolPrices.slice(0,5).map(p=>`
          <tr>
            <td>${_esc(p.crop_ko||'—')}</td>
            <td style="text-align:center;color:var(--muted)">금주</td>
            <td style="text-align:right">${p.supply_volume != null ? Math.round(p.supply_volume).toLocaleString('ko-KR') + 'kg' : '—'}</td>
            <td style="text-align:center"><span class="pill-tag">${p.change_pct != null ? (p.change_pct >= 0 ? '모집중' : '완료') : '—'}</span></td>
          </tr>`).join('');
      }
    }
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadPriceHistory() {
  const cropKo = $('price-hist-crop')?.value;
  const el = $('price-hist-body');
  if (!el) return;
  if (!cropKo) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px 0;text-align:center">작목을 선택하세요</div>'; return; }

  // farm_id: 내 농장 우선, 없으면 첫 번째 농장
  const farmId = _myFarmId || _farmsData[0]?.farm_id;
  if (!farmId) { el.innerHTML = '<div style="color:var(--muted);font-size:12px">농장 정보 로딩 중…</div>'; return; }

  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/market/price-history?days=30&crop_ko=${encodeURIComponent(cropKo)}`);
    const items = d.history || [];
    if (!items.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:12px">이력 없음</div>'; return; }

    const stats = d.stats || {};
    const trendIcon = {up:'↑', down:'↓', flat:'→'}[d.trend] || '→';
    const trendColor= {up:'var(--red)', down:'var(--accent)', flat:'var(--muted)'}[d.trend] || 'var(--muted)';
    const src = d.source === 'kamis_cache' ? 'KAMIS 실시간' : d.source === 'rda_static_estimated' ? '통계 추정' : '통계 기반';

    // SVG 스파크라인
    const prices = items.map(i => i.price_krw_kg);
    const minP = Math.min(...prices), maxP = Math.max(...prices);
    const W = 340, H = 60, pad = 4;
    const toX = i => prices.length > 1 ? pad + (i / (prices.length - 1)) * (W - 2*pad) : W / 2;
    const toY = p => H - pad - ((p - minP) / (maxP - minP + 1)) * (H - 2*pad);
    const pts = prices.map((p, i) => `${toX(i).toFixed(1)},${toY(p).toFixed(1)}`).join(' ');
    const sparkline = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:60px;display:block;margin:8px 0">
      <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round"/>
      <circle cx="${toX(prices.length-1)}" cy="${toY(prices[prices.length-1])}" r="3" fill="var(--accent)"/>
    </svg>`;

    // 최근 14행 표
    const rows = items.slice(-14).reverse().map((it, i, arr) => {
      const prev = arr[i+1];
      const chg  = prev ? ((it.price_krw_kg - prev.price_krw_kg) / prev.price_krw_kg * 100) : null;
      const chgHtml = chg != null
        ? `<span class="${chg>=0?'price-up':'price-down'}">${chg>=0?'+':''}${chg.toFixed(1)}%</span>` : '—';
      return `<tr>
        <td style="color:var(--muted)">${_esc(it.date)}</td>
        <td style="text-align:right;font-weight:600">${it.price_krw_kg.toLocaleString('ko-KR')}원</td>
        <td style="text-align:right">${chgHtml}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <span style="font-size:12px;font-weight:700">${cropKo} 도매가 추세</span>
        <span style="font-size:11px;color:${trendColor};font-weight:700">${trendIcon} ${d.trend === 'up' ? '상승세' : d.trend === 'down' ? '하락세' : '보합세'}</span>
      </div>
      ${sparkline}
      <div class="form-4col" style="gap:6px;margin-bottom:10px">
        ${[['최신가',stats.latest],['평균',stats.avg],['최고',stats.max],['최저',stats.min]].map(([l,v])=>
          `<div style="background:var(--card-soft);border:1px solid var(--border);border-radius:6px;padding:6px 8px;text-align:center">
            <div style="font-size:9px;color:var(--muted)">${l}</div>
            <div style="font-size:13px;font-weight:700;color:var(--text)">${v!=null?v.toLocaleString('ko-KR'):'—'}</div>
          </div>`).join('')}
      </div>
      <div class="table-scroll-wrap"><table class="price-hist-table">
        <thead><tr><th>날짜</th><th style="text-align:right">시세(원/kg)</th><th style="text-align:right">전일비</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div style="font-size:10px;color:var(--muted);margin-top:6px;text-align:right">출처: ${src}</div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadMarketHarvest() {
  const farmId = $('market-harvest-farm')?.value || _defaultFarm();
  const el = $('market-harvest-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const [harv, rev] = await Promise.allSettled([
      apiFetch(`/api/farms/${farmId}/harvest`),
      apiFetch(`/api/farms/${farmId}/revenue`),
    ]);
    const h = harv.status==='fulfilled' ? harv.value : null;
    const r = rev.status ==='fulfilled' ? rev.value  : null;
    const fmtF = n => n!=null ? Number(n).toFixed(1) : '—';
    const fmt  = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    el.innerHTML = `
      <div class="advisor-opt-grid">
        <div class="advisor-opt-item"><div class="ao-var">예상 수확량</div>
          <div class="ao-val">${fmtF(h?.yield_kg_forecast)} kg</div>
          <div class="ao-range">잔여 ${h?.days_to_harvest??'—'}일</div></div>
        <div class="advisor-opt-item"><div class="ao-var">예상 매출</div>
          <div class="ao-val" style="font-size:13px">${fmt(r?.revenue_krw)} 원</div>
          <div class="ao-range">${r?.price_krw_kg!=null?Math.round(r.price_krw_kg).toLocaleString('ko-KR')+'원/kg':''}</div></div>
        <div class="advisor-opt-item"><div class="ao-var">예상 순이익</div>
          <div class="ao-val ${(r?.revenue_krw??0)-(r?.cost_krw??0)>=0?'positive':'negative'}" style="font-size:13px">
            ${fmt((r?.revenue_krw??0)-(r?.cost_krw??0))} 원</div>
          <div class="ao-range">${r?.price_source==='kamis_live'?'🟢실시간 시세':'📊 평균 시세'}</div></div>
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadAdvisorOptimal() {
  const cropKo = $('advisor-crop-sel')?.value;
  const el = $('advisor-opt-body');
  if (!cropKo || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/admin/advisor/optimal/${encodeURIComponent(cropKo)}`);
    // API 응답 구조: { crop_ko, ranges: [{field, optimal_lo, optimal_hi, ...}] }
    // 또는 구버전: { optimal_env: {temp_internal, ...} }
    const LABELS = { temp_internal:'온도', humidity_int:'습도', co2_ppm:'CO₂', ec_dsm:'EC', solar_rad:'일사량' };
    const UNITS  = { temp_internal:'°C',  humidity_int:'%',   co2_ppm:'ppm', ec_dsm:'dS/m', solar_rad:'W/m²' };
    let items = [];
    if (d.ranges && d.ranges.length) {
      // 신규 구조: ranges[]
      items = d.ranges.map(r => ({
        label: LABELS[r.field] || r.field,
        unit:  UNITS[r.field]  || '',
        val:   null,  // 중앙값 없음
        lo:    r.optimal_lo,
        hi:    r.optimal_hi,
        action_high: r.high_action,
        action_low:  r.low_action,
      }));
    } else {
      // 구버전 flat 구조
      const opt = d.optimal_env || d.optimal || d;
      items = Object.keys(LABELS).map(k => ({
        label: LABELS[k], unit: UNITS[k],
        val:   opt[k] ?? null,
        lo:    opt[`${k}_min`] ?? opt[`${k}_p25`] ?? null,
        hi:    opt[`${k}_max`] ?? opt[`${k}_p75`] ?? null,
      }));
    }
    el.innerHTML = '<div class="advisor-opt-grid">' +
      items.map(it => {
        const mid = it.val != null ? Number(it.val).toFixed(1) :
                    (it.lo != null && it.hi != null ? ((it.lo+it.hi)/2).toFixed(1) : '—');
        const range = (it.lo != null && it.hi != null)
          ? `${Number(it.lo).toFixed(1)}~${Number(it.hi).toFixed(1)}` : '—';
        return `<div class="advisor-opt-item">
          <div class="ao-var">${_esc(it.label)}</div>
          <div class="ao-val">${_esc(mid)} <span style="font-size:10px;color:var(--muted)">${_esc(it.unit)}</span></div>
          <div class="ao-range">최적 ${_esc(range)}</div>
        </div>`;
      }).join('') + '</div>' +
      (d.note ? `<div style="font-size:11px;color:var(--muted);margin-top:8px">${_esc(d.note)}</div>` : '');
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── AI 상담 플로팅 ──────────────────────────────────────────────────────────
function toggleChat() {
  const panel = $('chat-panel');
  if (!panel) return;
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) {
    populateSelectWithFarms('chat-farm-sel');
    $('chat-input')?.focus();
  }
}

function clearChat() {
  _chatHistory = [];
  _chatFarmId  = '';
  const msgs = $('chat-messages');
  if (msgs) {
    msgs.innerHTML = `<div class="chat-msg ai">
      <div class="chat-who">SMART FARM AI</div>
      안녕하세요! 재배 환경, 수확량 예측, 관수 관리에 대해 무엇이든 물어보세요.
    </div>`;
  }
}

async function sendChat() {
  const input  = $('chat-input');
  const sendBtn= $('chat-send');
  const msgs   = $('chat-messages');
  const farmId = $('chat-farm-sel')?.value || '';
  const text   = input?.value.trim();
  if (!text || !msgs) return;

  // 농장 변경 시 대화 이력 초기화
  const target = farmId || (_farmsData[0]?.farm_id || 'farm_001');
  if (target !== _chatFarmId) {
    _chatHistory = [];
    _chatFarmId  = target;
  }

  // 사용자 메시지 표시
  const userDiv = document.createElement('div');
  userDiv.className = 'chat-msg user';
  userDiv.textContent = text;
  msgs.appendChild(userDiv);
  msgs.scrollTop = msgs.scrollHeight;

  input.value = '';
  if (sendBtn) sendBtn.disabled = true;

  // 로딩 표시
  const loadDiv = document.createElement('div');
  loadDiv.className = 'chat-msg ai';
  loadDiv.innerHTML = '<div class="chat-who">SMART FARM AI</div><div class="spinner" style="width:18px;height:18px;border-width:2px"></div>';
  msgs.appendChild(loadDiv);
  msgs.scrollTop = msgs.scrollHeight;

  // 대화 이력에 사용자 메시지 추가 (최근 10개 유지)
  _chatHistory.push({ role: 'user', content: text });
  if (_chatHistory.length > 20) _chatHistory = _chatHistory.slice(-20);

  try {
    const d = await apiFetch(`/api/farms/${target}/chat`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: text, history: _chatHistory.slice(0, -1) }),
    });
    const reply = d.reply || d.message || d.response || JSON.stringify(d);
    // 대화 이력에 AI 응답 추가
    _chatHistory.push({ role: 'assistant', content: reply });

    // 응답 표시 (텍스트 노드로 안전하게 처리)
    const whoDiv = document.createElement('div');
    whoDiv.className = 'chat-who';
    whoDiv.textContent = 'SMART FARM AI';
    const replyDiv = document.createElement('div');
    replyDiv.style.whiteSpace = 'pre-wrap';
    replyDiv.textContent = reply;
    loadDiv.innerHTML = '';
    loadDiv.appendChild(whoDiv);
    loadDiv.appendChild(replyDiv);

    // 메타 뱃지 (model_used, referenced_data)
    if (d.model_used && d.model_used !== 'stub-v1' && d.model_used !== 'rule_based') {
      const metaSpan = document.createElement('div');
      metaSpan.style.cssText = 'font-size:9px;color:var(--muted);margin-top:4px';
      metaSpan.textContent = '모델: ' + d.model_used;
      loadDiv.appendChild(metaSpan);
    }
    if (d.referenced_data && d.referenced_data.length) {
      const refSpan = document.createElement('div');
      refSpan.style.cssText = 'font-size:9px;color:var(--muted)';
      refSpan.textContent = '참조: ' + d.referenced_data.join(', ');
      loadDiv.appendChild(refSpan);
    }
    // suggestions 칩 — 클릭 시 해당 질문을 자동 입력
    const suggs = d.suggestions || [];
    if (suggs.length) {
      const suggsWrap = document.createElement('div');
      suggsWrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-top:6px';
      suggs.forEach(s => {
        const btn = document.createElement('button');
        btn.className = 'chat-sugg-chip';
        btn.textContent = s;
        btn.addEventListener('click', () => {
          const inp = $('chat-input');
          if (inp) { inp.value = s; inp.focus(); }
        });
        suggsWrap.appendChild(btn);
      });
      loadDiv.appendChild(suggsWrap);
    }
    _refreshChatQuota();
  } catch(e) {
    loadDiv.innerHTML = `<div class="chat-who">SMART FARM AI</div><span style="color:var(--red)">오류: ${_esc(e.message)}</span>`;
    // 실패 시 대화 이력에서 사용자 메시지 제거
    if (_chatHistory.length && _chatHistory[_chatHistory.length-1].role === 'user') {
      _chatHistory.pop();
    }
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    msgs.scrollTop = msgs.scrollHeight;
    input?.focus();
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// 빌링 / 티어 접근제어 함수
// ══════════════════════════════════════════════════════════════════════════════

// ── 플랜 뱃지 로드 ────────────────────────────────────────────────────────────
async function loadPlanBadge(farmId) {
  if (!farmId || !_token) return;
  try {
    const plan = await apiFetch(`/api/farms/${farmId}/billing/plan`);
    _planCache = plan;
    _myTier    = plan.tier;
    const dot   = $('plan-dot');
    const name  = $('plan-name');
    const quota = $('plan-chat-quota');
    if (dot)   dot.style.background = plan.color || '#8892a4';
    if (name)  name.textContent     = plan.tier_name_ko || plan.tier;
    if (quota) {
      const q = plan.chat_quota;
      if (!q || q.max === 0)  quota.textContent = 'AI 불가';
      else if (q.max === -1)  quota.textContent = 'AI 무제한';
      else quota.textContent = `AI ${q.remaining ?? q.max}/${q.max}`;
    }
    const badge = document.querySelector('.plan-badge');
    if (badge) badge.style.borderColor = (plan.color || '#8892a4') + '55';
  } catch(e) {
    console.warn('[loadPlanBadge]', e.message);
  }
}

// ── Tier Guard — 섹션 잠금 오버레이 ──────────────────────────────────────────
async function tierGuard(farmId, sectionName) {
  if (!farmId || !_token) return;
  try {
    const d = await apiFetch(`/api/farms/${farmId}/billing/features?section=${sectionName}`);
    _featCache[sectionName] = d.features || [];
    const locked = (d.features || []).filter(f => !f.allowed);
    _applyLockBanner(sectionName, locked);
  } catch(e) {
    console.warn('[tierGuard]', sectionName, e.message);
  }
}

function _applyLockBanner(section, lockedFeatures) {
  const secEl = $(`sec-${section}`);
  if (!secEl) return;
  // 기존 배너 제거
  secEl.querySelectorAll('.tier-lock-banner').forEach(el => el.remove());
  if (!lockedFeatures.length) return;

  // 가장 낮은 min_tier 찾기
  const minTier = lockedFeatures.reduce((best, f) =>
    _tierRankClient(f.min_tier) < _tierRankClient(best) ? f.min_tier : best,
    lockedFeatures[0].min_tier
  );
  const color  = _tierColor(minTier);
  const labels = lockedFeatures.map(f => f.label_ko || f.feature_code).join(' · ');

  const banner = document.createElement('div');
  banner.className = 'tier-lock-banner';
  banner.style.cssText = 'margin-bottom:14px';
  banner.innerHTML = `
    <div style="background:${color}18;border:1px solid ${color}44;border-radius:10px;
                padding:12px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px">
      <div>
        <span style="font-size:13px;font-weight:700;color:${color}">🔒 ${_esc(_tierNameKo(minTier))} 플랜 이상 필요</span>
        <div style="font-size:11px;color:var(--muted);margin-top:3px">${_esc(labels)}</div>
      </div>
      <button onclick="openUpgradeModal()"
              style="flex-shrink:0;padding:7px 16px;background:${color};border:none;
                     border-radius:7px;color:#fff;font-size:12px;font-weight:700;cursor:pointer;
                     white-space:nowrap">
        업그레이드 ↑
      </button>
    </div>`;
  secEl.prepend(banner);
}

// 클라이언트 측 티어 유틸
function _tierRankClient(tier) {
  return {basic:1, smart:2, pro:3, enterprise:4}[tier] || 0;
}
function _tierColor(tier) {
  return {basic:'#8892a4', smart:'#4f8ef7', pro:'#a78bfa', enterprise:'#f9a825'}[tier] || '#8892a4';
}
function _tierNameKo(tier) {
  return {basic:'기본', smart:'스마트', pro:'프로', enterprise:'엔터프라이즈'}[tier] || tier;
}

// ── 업그레이드 모달 ───────────────────────────────────────────────────────────
function openUpgradeModal() {
  const bg = $('upgrade-modal-bg');
  if (!bg) return;
  _renderUpgradeCards();
  bg.style.display = 'flex';
}

function closeUpgradeModal() {
  const bg = $('upgrade-modal-bg');
  if (bg) bg.style.display = 'none';
  const res = $('upgrade-result');
  if (res) { res.textContent = ''; res.style.color = ''; }
}

function _renderUpgradeCards() {
  const wrap = $('upgrade-tier-list');
  if (!wrap) return;
  // planCache가 있으면 실제 upgrade_options 사용, 없으면 기본값
  const opts = (_planCache?.upgrade_options?.length)
    ? _planCache.upgrade_options
    : [
        {tier:'smart',      name_ko:'스마트',       price_krw_month:79000,  color:'#4f8ef7'},
        {tier:'pro',        name_ko:'프로',         price_krw_month:199000, color:'#a78bfa'},
        {tier:'enterprise', name_ko:'엔터프라이즈', price_krw_month:499000, color:'#f9a825'},
      ];

  const _safeColor = c => (c && /^#[0-9a-fA-F]{3,8}$/.test(c)) ? c : '#8892a4';
  wrap.innerHTML = opts.map((o, idx) => {
    const clr = _safeColor(o.color);
    return `
    <label class="upgrade-tier-card" style="--tc:${clr}">
      <input type="radio" name="upgrade-tier-sel" value="${_esc(o.tier)}" ${idx === 0 ? 'checked' : ''}>
      <div class="upgrade-tier-card-inner">
        <div style="font-size:16px;font-weight:700;color:${clr}">${_esc(o.name_ko)}</div>
        <div style="font-size:24px;font-weight:800;margin:8px 0">
          ₩${Math.round(o.price_krw_month/1000)}K
          <span style="font-size:11px;font-weight:400;color:var(--muted)">/월</span>
        </div>
        <div style="font-size:11px;color:var(--muted);line-height:1.5">${_tierFeatureHint(o.tier)}</div>
      </div>
    </label>`;
  }).join('');

  // 현재 플랜 표시
  const cur = $('upgrade-current-plan');
  if (cur) cur.textContent = `현재 플랜: ${_tierNameKo(_myTier)}`;
}

function _tierFeatureHint(tier) {
  return {
    smart:      'IoT 센서 실시간 · 기본 AI 채팅 30회/월 · 환경·관수 자동화',
    pro:        'ML 수확·매출 예측 · AI 채팅 200회/월 · VPD 재배기술 · 시나리오 분석',
    enterprise: '자동 제어 추천 · AI 무제한 · 전 기능 해제 · 전담 지원',
  }[tier] || '';
}

async function submitUpgrade() {
  const farmId = _myFarmId;
  if (!farmId) {
    showToast('농장 정보를 불러오는 중입니다. 잠시 후 다시 시도해 주세요.');
    return;
  }
  const tierRadio = document.querySelector('input[name="upgrade-tier-sel"]:checked');
  if (!tierRadio) { showToast('업그레이드할 플랜을 선택해 주세요.'); return; }
  const pgRadio = document.querySelector('input[name="pg-channel"]:checked');
  const pg = pgRadio ? pgRadio.value : 'manual';

  const btn = $('upgrade-submit-btn');
  const res = $('upgrade-result');
  if (btn) { btn.disabled = true; btn.textContent = '처리 중…'; }
  if (res) { res.textContent = ''; res.style.color = ''; }

  try {
    const d = await apiFetch(`/api/farms/${farmId}/billing/upgrade`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ target_tier: tierRadio.value, pg_channel: pg }),
    });
    if (res) {
      res.textContent = d.message_ko || '업그레이드 완료';
      res.style.color = 'var(--green)';
    }
    if (d.status === 'approved') {
      // 즉시 플랜 갱신 후 모달 닫기
      _planCache = null;
      _featCache = {};
      setTimeout(async () => {
        await loadPlanBadge(farmId);
        closeUpgradeModal();
        // 현재 섹션 잠금 배너도 갱신
        const activeSec = document.querySelector('.sec.active');
        if (activeSec) {
          const secName = activeSec.id.replace('sec-', '');
          if (SECTION_LOADERS[secName]) tierGuard(farmId, secName);
        }
      }, 1400);
    } else if (d.redirect_url && /^https?:\/\//.test(d.redirect_url)) {
      if (res) res.textContent += '\n결제 페이지로 이동합니다…';
      setTimeout(() => window.open(d.redirect_url, '_blank'), 1200);
    }
  } catch(e) {
    if (res) { res.textContent = '오류: ' + e.message; res.style.color = 'var(--red)'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '업그레이드 신청'; }
  }
}

// ── AI 채팅 — /chat 엔드포인트 쿼터 소진 처리 (서버측 consume은 farmer.py에서) ──
// sendChat() 이후 쿼터 UI 갱신만 수행
function _refreshChatQuota() {
  if (_myFarmId) {
    apiFetch(`/api/farms/${_myFarmId}/billing/quota`).then(q => {
      const quota = $('plan-chat-quota');
      if (!quota) return;
      if (q.max === -1) quota.textContent = 'AI 무제한';
      else if (q.max === 0) quota.textContent = 'AI 불가';
      else quota.textContent = `AI ${q.remaining}/${q.max}`;
    }).catch(() => {});
  }
}

// 자동갱신 타이머 (doLogout 시 해제)
const _TIMERS = [
  setInterval(() => { if (_token && !document.hidden) loadAdvisorySummary(); }, 30_000),
  setInterval(() => { if (_token && !document.hidden) loadAdvisoryHistory(); }, 30_000),
  setInterval(() => { if (_token && !document.hidden) refreshAll(); }, 60_000),
];

// ── Phase 1~3 — 모바일 유틸리티 (드로어 / 하단 탭 / Bottom Sheet / Accordion) ──
function toggleDrawer() {
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('sidebar-overlay');
  if (!sb) return;
  const isOpen = sb.classList.contains('drawer-open');
  if (isOpen) {
    closeDrawer();
  } else {
    sb.classList.add('drawer-open');
    if (ov) ov.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
}

function closeDrawer() {
  const sb = document.getElementById('sidebar');
  const ov = document.getElementById('sidebar-overlay');
  if (sb) sb.classList.remove('drawer-open');
  if (ov) ov.classList.remove('open');
  document.body.style.overflow = '';
}

// Accordion toggle
function toggleAccordion(btn) {
  btn.classList.toggle('open');
  const body = btn.nextElementSibling;
  if (body && body.classList.contains('accordion-body')) {
    body.classList.toggle('open');
  }
}

// Bottom Sheet API
const BottomSheet = {
  open(title, bodyHtml, confirmText, onConfirm) {
    const bs  = document.getElementById('bottom-sheet');
    const bso = document.getElementById('bs-overlay');
    const bst = document.getElementById('bs-title');
    const bsb = document.getElementById('bs-body');
    const bsc = document.getElementById('bs-confirm-btn');
    if (!bs) return;
    if (bst) bst.textContent = title || '';
    if (bsb) bsb.innerHTML = bodyHtml || '';
    if (bsc) {
      bsc.textContent = confirmText || '확인';
      bsc.onclick = () => { if (onConfirm) onConfirm(); BottomSheet.close(); };
    }
    bs.classList.add('open');
    if (bso) { bso.classList.add('open'); bso.onclick = () => BottomSheet.close(); }
    document.body.style.overflow = 'hidden';
  },
  close() {
    const bs  = document.getElementById('bottom-sheet');
    const bso = document.getElementById('bs-overlay');
    if (bs)  bs.classList.remove('open');
    if (bso) { bso.classList.remove('open'); bso.onclick = null; }
    document.body.style.overflow = '';
  }
};
