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
        loadCurrentEnv();
        loadWeatherForecast();
        loadEnvAnomalies();
        loadLEDSpectrum();
      }
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
        loadSfropScenarios();
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
    loadModelPerformance(); loadApiStatus();
    loadDiseaseDetect(); loadWholesaleMarket();
  },
};

// ── 섹션 전환 ────────────────────────────────────────────────────────────────
function showSection(name) {
  const secEl = document.getElementById(`sec-${name}`);
  if (!secEl) { console.warn('[showSection] 섹션 없음:', name); name = 'dashboard'; }

  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  document.querySelectorAll(`[onclick="showSection('${name}')"]`).forEach(b => b.classList.add('active'));
  document.querySelectorAll('.bn-tab[data-sec]').forEach(t => t.classList.remove('active'));
  const bnTab = document.querySelector(`.bn-tab[data-sec="${name}"]`);
  if (bnTab) bnTab.classList.add('active');
  closeDrawer();

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
   'hero-farm-sel'].forEach(id => populateSelectWithFarms(id));
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

// ── 초기화 (토큰이 있으면 즉시 대시보드 진입) ─────────────────────────────
if (_token) {
  $('login-overlay').classList.add('hidden');
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
