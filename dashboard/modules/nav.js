// ── 오늘 날짜 자동 세팅 헬퍼 ─────────────────────────────────────────────────
function _setTodayDate(...ids) {
  const today = new Date().toISOString().slice(0, 10);
  ids.forEach(id => {
    const el = $(id);
    if (el && !el.value) el.value = today;
  });
}

// ── 기본 농장 선택 헬퍼 ─────────────────────────────────────────────────────
function _defaultFarm() {
  if (_myFarmId && _farmsData.some(f => f.farm_id === _myFarmId)) {
    return _myFarmId;
  }
  if (_farmsData.length) return _farmsData[0].farm_id;
  return _myFarmId || '';
}

function _autoSel(selId, farmId) {
  const sel = $(selId);
  if (sel && !sel.value && farmId) sel.value = farmId;
}

// ── 섹션 로더 맵 ─────────────────────────────────────────────────────────────
const SECTION_LOADERS = {
  dashboard: () => {
    if (!_farmsData.length) {
      loadFarmsOverview().then(() => {
        populateAllFarmSels();
        const fid2 = _defaultFarm();
        if (fid2) { _autoSel('hero-farm-sel', fid2); loadHeroDashboard(fid2); }
      });
    } else {
      loadFarmsOverview();
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
      }
      // 각 함수가 내부적으로 farmId 미선택 처리하므로 fid 여부와 무관하게 항상 호출
      loadCurrentEnv();
      loadWeatherForecast();
      loadEnvAnomalies();
      loadLEDSpectrum();
      if (fid) loadEnvHistory(fid);
    };
    if (!_farmsData.length) {
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
        loadCtrlRecommendations();
        loadDiseaseDetect(fid);
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
      _setTodayDate('irri-date');
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('irr-sched-farm', fid);
        _autoSel('priva-farm-sel', fid);
        _autoSel('irri-farm-sel2', fid);
        loadIrrigationAnalysis(fid);
        loadIrrigationSchedule();
        loadPrivaSchedule();
        loadIrrigationHistory(fid);
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
      _setTodayDate('gr-date', 'hv-date');
      const fid = _defaultFarm();
      if (fid) {
        _autoSel('growth-farm-sel',  fid);
        _autoSel('whatif-farm-sel',  fid);
        _autoSel('sfrop-farm-sel',   fid);
        _autoSel('gr-farm', fid);
        _autoSel('hv-farm', fid);
        loadGrowthHarvestRevenue();
        loadSfropScenarios();
        loadGrowthHistory(fid);
        loadHarvestHistory(fid);
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
        loadMarketHarvest();
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
        loadERPRealtime();
        loadProfitForecast();
        loadCostBreakdown();
      }
    };
    if (!_farmsData.length) {
      loadFarmsOverview().then(_doLoadEnergy).catch(_doLoadEnergy);
    } else { _doLoadEnergy(); }
    if (_myFarmId) tierGuard(_myFarmId, 'energy');
  },

  system: () => {
    loadPipelineState(); loadEtlStatus(); loadRetrainHistory();
    loadModelPerformance(); loadModelDrift(); loadApiStatus();
    loadDiseaseDetect(); loadWholesaleMarket();
  },
};

// ── 섹션 전환 ────────────────────────────────────────────────────────────────
// ── 섹션 이름 맵 (헤더 레이블) ──────────────────────────────────────────────
const _SEC_LABELS = {
  dashboard: '통합 홈', environ: '환경·기후', control: '병해·AI 진단',
  irrigation: '관수·양액', growth: '생육·재배력',
  market: '공동출하', energy: '수익성·ERP', system: '연동·모델',
};

function showSection(name) {
  const secEl = document.getElementById(`sec-${name}`);
  if (!secEl) { console.warn('[showSection] 섹션 없음:', name); name = 'dashboard'; }

  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll(`[onclick="showSection('${name}')"]`).forEach(b => b.classList.add('active'));
  document.querySelectorAll('.bn-tab[data-sec]').forEach(t => t.classList.remove('active'));
  const bnTab = document.querySelector(`.bn-tab[data-sec="${name}"]`);
  if (bnTab) bnTab.classList.add('active');
  closeDrawer();

  // 헤더 섹션 레이블 업데이트 (데스크탑: 홈이면 숨김, 나머지 표시)
  const _lbl = document.getElementById('hdr-sec-label');
  if (_lbl) {
    if (name === 'dashboard') { _lbl.style.display = 'none'; }
    else { _lbl.textContent = _SEC_LABELS[name] || name; _lbl.style.display = ''; }
  }

  document.querySelectorAll('.sec').forEach(s => {
    s.classList.remove('active');
    s.style.display = 'none';
  });

  const target = document.getElementById(`sec-${name}`);
  if (target) {
    target.classList.add('active');
    target.style.display = 'flex';
  }

  const _ca = document.getElementById('content-area');
  if (_ca) _ca.scrollTop = 0;
  if (target) target.scrollTop = 0;

  // Sticky Action Bar 표시 제어 (작업지시서 §10.2)
  const _SAB_SECTIONS = ['dashboard', 'market'];
  document.querySelectorAll('.sticky-action-bar').forEach(bar => {
    bar.style.display = _SAB_SECTIONS.includes(name) && bar.id === `sab-${name}` ? '' : 'none';
  });

  const runLoader = () => { if (SECTION_LOADERS[name]) SECTION_LOADERS[name](); };

  if (!_farmsData.length && name !== 'system') {
    loadFarmsOverview().then(runLoader).catch(runLoader);
  } else {
    runLoader();
  }
}

// ── 전체 새로고침 ─────────────────────────────────────────────────────────────
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
  populateAllFarmSels();
  const _activeSec = document.querySelector('.sec.active');
  const _activeName = _activeSec?.id?.replace('sec-', '');
  if (_activeName === 'dashboard') {
    const heroFid = $('hero-farm-sel')?.value || _defaultFarm();
    if (heroFid) {
      _autoSel('hero-farm-sel', heroFid);
      loadHeroDashboard(heroFid);
    }
  }
}

// ── 농장 선택지 채우기 ────────────────────────────────────────────────────────
function populateSelectWithFarms(selId, current = '') {
  const sel = $(selId);
  if (!sel) return;
  if (!_farmsData.length) {
    sel.innerHTML = '<option value="">등록된 농장 없음</option>';
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
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
   'hero-farm-sel','gr-farm','hv-farm'].forEach(id => populateSelectWithFarms(id));
  const sfSel = $('sensor-farm-sel');
  if (sfSel && _farmsData.length) {
    const cur = sfSel.value;
    sfSel.innerHTML = _farmsData.map(f =>
      `<option value="${_esc(f.farm_id)}" ${f.farm_id === cur ? 'selected' : ''}>${_esc(f.farm_id)}</option>`
    ).join('');
  }
}

function populateProfitFarmSel(farms) {
  _farmsData = farms && farms.length ? farms : _farmsData;
  populateAllFarmSels();
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

// ── 모바일: 드로어 / Accordion / Bottom Sheet ──────────────────────────────
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

function toggleAccordion(btn) {
  btn.classList.toggle('open');
  const body = btn.nextElementSibling;
  if (body && body.classList.contains('accordion-body')) {
    body.classList.toggle('open');
  }
}

// 카드 접기/펼치기 — 새 폼 카드용 (bodyEl, arrowEl 직접 전달)
function toggleCard(bodyEl, arrowEl) {
  if (!bodyEl) return;
  const open = bodyEl.style.display !== 'none';
  bodyEl.style.display = open ? 'none' : 'block';
  if (arrowEl) arrowEl.style.transform = open ? '' : 'rotate(180deg)';
}

// ── C3 To-do 전체 확인 (Sticky Action Bar) ──
function markAllTodoDone() {
  const items = document.querySelectorAll('#todo-body .todo-item');
  if (!items.length) { showToast('확인할 To-do 항목이 없습니다.'); return; }
  items.forEach(item => {
    const btn = item.querySelector('.todo-action');
    if (btn && !btn.classList.contains('gray')) {
      btn.classList.remove('blue','orange','red');
      btn.classList.add('gray');
      btn.textContent = '✓ 완료';
    }
  });
  showToast('✅ 오늘 To-do를 모두 확인했습니다.');
}

// ── G2 환경제어 탭 전환 (작업지시서 §10.4) ──
function switchEnvTab(tabName, btn) {
  // 탭 버튼 활성화
  document.querySelectorAll('.env-seg-ctrl .seg-btn').forEach(b => {
    b.classList.remove('active');
    b.setAttribute('aria-selected', 'false');
  });
  btn.classList.add('active');
  btn.setAttribute('aria-selected', 'true');

  // 패널 표시/숨김
  document.querySelectorAll('#sec-environ .env-panel').forEach(panel => {
    const show = panel.dataset.envpanel === tabName;
    panel.style.display = show ? '' : 'none';
    // row row-2는 flex 복원
    if (show && panel.classList.contains('row')) panel.style.display = 'grid';
  });

  // 이력 탭 진입 시 자동 로드
  if (tabName === 'history') {
    const farmId = document.getElementById('env-manual-farm')?.value || _defaultFarm();
    if (farmId && typeof loadEnvHistory === 'function') loadEnvHistory(farmId);
  }
}

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

// ── 오프라인 감지 배너 ────────────────────────────────────────────────────────
(function _initOfflineBanner() {
  const BANNER_ID = 'offline-banner';
  function _getOrCreate() {
    let el = document.getElementById(BANNER_ID);
    if (!el) {
      el = document.createElement('div');
      el.id = BANNER_ID;
      el.style.cssText = [
        'position:fixed','top:0','left:0','right:0','z-index:9000',
        'background:#b91c1c','color:#fff','text-align:center',
        'padding:7px 16px','font-size:13px','font-weight:600',
        'display:none','align-items:center','justify-content:center','gap:8px',
        'box-shadow:0 2px 8px rgba(0,0,0,.4)',
      ].join(';');
      document.body.appendChild(el);
    }
    return el;
  }
  function _update() {
    const el = _getOrCreate();
    if (!navigator.onLine) {
      el.innerHTML = '🔴 오프라인 — 인터넷 연결을 확인하세요. 마지막 데이터를 표시 중입니다.';
      el.style.display = 'flex';
    } else {
      el.style.display = 'none';
    }
  }
  window.addEventListener('online',  _update);
  window.addEventListener('offline', _update);
  _update();
})();

// ── 자동 새로고침 (30초, 화면 표시 중일 때만) ─────────────────────────────
(function _initAutoRefresh() {
  const INTERVAL_MS = 30_000;
  const REFRESH_MAP = {
    dashboard: () => { const fid = _defaultFarm(); if (fid) loadHeroDashboard(fid); },
    environ:   () => { if (_defaultFarm()) { loadCurrentEnv(); loadWeatherForecast(); } },
  };
  setInterval(() => {
    if (document.hidden) return;
    const active = document.querySelector('.sec.active, .sec[style*="flex"]');
    const secId  = active?.id?.replace('sec-', '');
    const fn     = secId && REFRESH_MAP[secId];
    if (fn) fn();
  }, INTERVAL_MS);
})();

// ── 초기화 (토큰이 있으면 즉시 대시보드 진입) ─────────────────────────────
if (_token) {
  $('login-overlay')?.classList.add('hidden');
  if (!_myFarmId) {
    const claims = _decodeJwt(_token);
    _myFarmId = claims.farm_id || '';
    _myTier   = claims.tier    || 'basic';
  }
  refreshAll();
  if (_myFarmId) loadPlanBadge(_myFarmId);
  const _initHash = location.hash.slice(1);
  const _VALID_SECTIONS = ['dashboard','environ','control','irrigation','growth','market','energy','system'];
  if (_initHash && _VALID_SECTIONS.includes(_initHash)) {
    setTimeout(() => showSection(_initHash), 300);
  }
  if (!window._hashListenerRegistered) {
    window._hashListenerRegistered = true;
    window.addEventListener('hashchange', () => {
      const h = location.hash.slice(1);
      if (_VALID_SECTIONS.includes(h)) showSection(h);
    });
  }
}
