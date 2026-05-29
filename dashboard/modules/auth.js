// ── 인증 탭 전환 ──────────────────────────────────────────────────────────────
function switchAuthTab(tab) {
  ['login','reg'].forEach(t => {
    $(`tab-${t}`).classList.toggle('active', t === tab);
    $(`panel-${t}`).classList.toggle('active', t === tab);
  });
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
  _startTimers();
  if (data.onboarding_required) {
    startOnboarding();
  } else {
    refreshAll();
    if (_myFarmId) loadPlanBadge(_myFarmId);
    const _VALID = ['dashboard','environ','control','irrigation','growth','market','energy','system'];
    const h = location.hash.slice(1);
    if (h && _VALID.includes(h) && h !== 'dashboard') {
      setTimeout(() => showSection(h), 400);
    }
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

// ── 로그아웃 ──────────────────────────────────────────────────────────────────
function doLogout() {
  _token = ''; _myFarmId = ''; _myTier = 'basic';
  _farmsData = []; _planCache = null; _featCache = {};
  _chatHistory = []; _chatFarmId = '';
  _TIMERS.forEach(t => clearInterval(t));
  _TIMERS = [];
  ['sf_token','sf_api','sf_farm_id','sf_tier'].forEach(k => sessionStorage.removeItem(k));
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

// ── 플랜 배지 ─────────────────────────────────────────────────────────────────
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

// ── Tier Guard ────────────────────────────────────────────────────────────────
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
  secEl.querySelectorAll('.tier-lock-banner').forEach(el => el.remove());
  if (!lockedFeatures.length) return;

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
      _planCache = null;
      _featCache = {};
      setTimeout(async () => {
        await loadPlanBadge(farmId);
        closeUpgradeModal();
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

// ── AI 채팅 쿼터 UI 갱신 ──────────────────────────────────────────────────────
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

// ── 자동갱신 타이머 (doLogout 시 해제, 재로그인 시 재시작) ───────────────────
let _TIMERS = [];
function _startTimers() {
  _TIMERS.forEach(t => clearInterval(t));
  _TIMERS = [
    setInterval(() => { if (_token && !document.hidden) loadAdvisorySummary(); }, 30_000),
    setInterval(() => { if (_token && !document.hidden) loadAdvisoryHistory(); }, 30_000),
    setInterval(() => { if (_token && !document.hidden) refreshAll(); }, 60_000),
  ];
}
_startTimers();
