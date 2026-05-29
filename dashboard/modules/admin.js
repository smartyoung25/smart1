// ── 멀티 농장 비교 — 전역 상태 ───────────────────────────────────────────────
let _farmsData    = [];
let _farmsSortKey = 'farm_id';
let _farmsSortAsc = true;

// ── 차트 패널 — 전역 상태 ────────────────────────────────────────────────────
let _chartInstance = null;
let _chartFarmId   = null;
let _chartMetric   = 'temp_internal';
let _detailTab     = 'env';

const METRIC_CFG = {
  temp_internal: { label:'내부온도 (°C)',   color:'#f2645a', yLabel:'°C'  },
  humidity_int:  { label:'내부습도 (%)',     color:'#4f8ef7', yLabel:'%'   },
  co2_ppm:       { label:'CO₂ (ppm)',        color:'#3ecf8e', yLabel:'ppm' },
  soil_temp:     { label:'지온 (°C)',        color:'#f5c842', yLabel:'°C'  },
};

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

// ── 수동 재학습 트리거 ────────────────────────────────────────────────────────
function triggerRetrainManual() {
  const resEl = $('retrain-trigger-result');
  const btn   = $('retrain-trigger-btn');
  BottomSheet.open(
    '⚠️ 전체 모델 재학습',
    '<p style="line-height:1.7;font-size:13px">전체 작목 AI 모델 재학습을 시작합니다.<br>약 <b>10~30분</b> 소요될 수 있습니다.</p>',
    '재학습 시작',
    async () => {
      if (btn) btn.disabled = true;
      _setResult('retrain-trigger-result', 'warn', '재학습 요청 중…');
      try {
        const d = await apiFetch('/api/admin/pipeline/trigger', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: '대시보드 수동 트리거', confirm: true }),
        });
        _setResult('retrain-trigger-result', 'ok', `재학습 시작됨 (run_id: ${d.run_id || '—'})`);
        setTimeout(() => { loadRetrainHistory(); loadPipelineState(); }, 10_000);
      } catch(e) {
        _setResult('retrain-trigger-result', 'err', '실패: ' + e.message);
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
    setText('kpi-done', d.done_files ?? '—');
    if (d.last_modified) $('etl-mtime').textContent = d.last_modified.slice(0,19).replace('T',' ');
    const lines = (d.log_tail||[]).map(l => {
      const cls = l.includes('ERROR') ? 'log-error' : l.includes('WARN') ? 'log-warn' : '';
      return `<div class="log-line ${cls}">${_esc(l)}</div>`;
    }).join('');
    el.innerHTML = `<div class="log-box">${lines||'<span style="color:var(--muted)">로그 없음</span>'}</div>`;
    el.scrollTop = 9999;
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
    const poolReady = _farmsData.filter(f => f.online && !f.anomaly).length;
    setText('kpi-pool-ready', poolReady + '개');
    if (d.total > 0) {
      const onlinePct = Math.round(d.online / d.total * 100);
      setText('kpi-iot-status', onlinePct + '%');
    }
  } catch(e) {
    const tb = $('farms-tbody');
    if (tb) tb.innerHTML = `<tr><td colspan="10" style="color:var(--muted);text-align:center;font-size:12px">내 농장 데이터 로드 중…</td></tr>`;
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
      } catch(_) {}
    }
  }
}

setInterval(() => { if (_token && !document.hidden) loadFarmsOverview(); }, 30_000);

function sortFarms(key) {
  if (_farmsSortKey === key) _farmsSortAsc = !_farmsSortAsc;
  else { _farmsSortKey = key; _farmsSortAsc = true; }
  renderFarmsTable();
}

function renderFarmsTable() {
  const search     = ($('farm-search')?.value     || '').toLowerCase();
  const cropFilter = $('farm-crop-filter')?.value  || '';
  const statFilter = $('farm-status-filter')?.value || '';

  // 기본 필터 없고 검색도 없으면 → 오프라인 자동 숨김 (의미 있는 농장만 표시)
  // statFilter==='all' 이면 강제 전체 표시
  const hideOffline = !statFilter && !search && !cropFilter;

  let rows = _farmsData.filter(f => {
    if (cropFilter && f.crop_ko !== cropFilter) return false;
    if (statFilter === 'online'  && (!f.online || f.anomaly)) return false;
    if (statFilter === 'anomaly' && !f.anomaly)  return false;
    if (statFilter === 'offline' && f.online)    return false;
    if (statFilter === 'all') { /* 전체 표시 — 아무 필터 없음 */ }
    else if (hideOffline && !f.online) return false;
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

  // 정렬 방향 표시기 업데이트
  document.querySelectorAll('#farms-table .sortable').forEach(th => {
    const k = th.getAttribute('onclick')?.match(/sortFarms\('(.+?)'\)/)?.[1];
    if (!k) return;
    th.textContent = th.textContent.replace(/[↑↓↕]/g, '').trim();
    th.textContent += ' ' + (k === _farmsSortKey ? (_farmsSortAsc ? '↑' : '↓') : '↕');
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

  tbody.innerHTML = rows.map(f => {
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

  // 오프라인 숨김 안내 (기본 필터일 때만)
  if (hideOffline) {
    const offCnt = _farmsData.filter(f => !f.online).length;
    if (offCnt > 0) {
      tbody.innerHTML += `<tr><td colspan="10" style="text-align:center;padding:10px 0;border-top:1px solid var(--border)">
        <span style="font-size:12px;color:var(--muted)">⚫ 오프라인 ${offCnt}개 숨김 (실시간 데이터 없음)</span>
        &nbsp;<button onclick="document.getElementById('farm-status-filter').value='offline';renderFarmsTable()"
          style="font-size:11px;color:var(--accent);background:none;border:1px solid var(--accent);border-radius:6px;padding:2px 8px;cursor:pointer">오프라인 보기</button>
        &nbsp;<button onclick="document.getElementById('farm-status-filter').value='all';renderFarmsTable()"
          style="font-size:11px;color:var(--muted);background:none;border:1px solid var(--border);border-radius:6px;padding:2px 8px;cursor:pointer">전체 보기</button>
      </td></tr>`;
    }
  }
}

// ── 센서 이력 차트 패널 ───────────────────────────────────────────────────────
function openChartPanel(farmId, rowEl) {
  document.querySelectorAll('#farms-tbody tr').forEach(r => r.classList.remove('selected'));
  rowEl.classList.add('selected');
  _chartFarmId = farmId;
  $('chart-farm-label').textContent = farmId;
  const farmInfo = _farmsData.find(f => f.farm_id === farmId);
  if ($('chart-farm-crop')) $('chart-farm-crop').textContent = farmInfo?.crop_ko || '';
  $('chart-panel').classList.add('open');
  if (_detailTab === 'env')          reloadChart();
  else if (_detailTab === 'reco')    loadFarmRecommendations(farmId);
  else if (_detailTab === 'harvest') loadFarmHarvestRevenue(farmId);
  else if (_detailTab === 'disease') loadFarmDiseaseRisk(farmId);
}

function setDetailTab(tab) {
  _detailTab = tab;
  document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
  const tabIdx = ['env','reco','harvest','disease'].indexOf(tab);
  document.querySelectorAll('.detail-tab')[tabIdx]?.classList.add('active');
  ['detail-env','detail-reco','detail-harvest','detail-disease'].forEach(id => {
    const el = $(id); if (el) el.classList.remove('active');
  });
  $(`detail-${tab}`)?.classList.add('active');
  if (!_chartFarmId) return;
  if (tab === 'env')          reloadChart();
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
  const idx = Object.keys(METRIC_CFG).indexOf(metric);
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
  el.innerHTML = '<div class="spinner spinner-center"></div>';
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
    el.innerHTML = `<div class="err-inline" style="padding:12px">권고 조회 실패: ${_esc(e.message)}</div>`;
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
  el.innerHTML = '<div class="spinner spinner-center"></div>';
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
        <div class="harvest-kpi"><div class="hk-label">예상 수확량</div>
          <div class="hk-val">${fmtKg(h?.yield_kg_forecast)} <span style="font-size:13px;color:var(--muted)">kg</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">80% 신뢰구간</div>
          <div class="hk-val" style="font-size:14px">${h?.yield_q10 != null ? `${fmtKg(h.yield_q10)}–${fmtKg(h.yield_q90)} kg` : '—'}</div></div>
        <div class="harvest-kpi"><div class="hk-label">잔여 재배일</div>
          <div class="hk-val">${h?.days_to_harvest ?? '—'} <span style="font-size:13px;color:var(--muted)">일</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">예상 매출</div>
          <div class="hk-val">${fmt(r?.revenue_krw)} <span class="unit-muted">원</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">예상 비용</div>
          <div class="hk-val">${fmt(r?.cost_krw)} <span class="unit-muted">원</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">예상 순이익</div>
          <div class="hk-val ${profitCls}">${profitSign}${fmt(profit)} <span style="font-size:11px">원</span></div></div>
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
    const nullReasons = [];
    if (!h) nullReasons.push(['수확 예측', '수확량 모델 API 응답 없음 — 서버 상태 확인 필요']);
    else if (h.yield_kg_forecast == null) nullReasons.push(['예상 수확량', '해당 작목의 M2 모델이 미학습 상태이거나 환경 센서 데이터 부족']);
    else if (h.confidence_grade?.startsWith('낮음')) nullReasons.push(['수확량 신뢰도', '현재 예측 오차 ≥ 45% — 데이터 수집 기간이 짧거나 센서 편차 큼']);
    if (!r) nullReasons.push(['수익 분석', '매출·비용 API 응답 없음 — 농가 등록 완료 여부 확인']);
    else if (r.revenue_krw == null) nullReasons.push(['예상 매출', '도매가 정보 없음 — KAMIS API 키 또는 작목별 기본 시세 확인']);
    if (nullReasons.length) el.innerHTML += _nullReasonHtml(nullReasons);
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '수확·수익 예측 조회 실패');
  }
}

// ── 농가 상세: 병해 위험 ──────────────────────────────────────────────────────
async function loadFarmDiseaseRisk(farmId) {
  const el = $('detail-disease-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner spinner-center"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/disease-risk`);
    let risks = d.risks || d.diseases || null;
    if (!risks) {
      if (d.disease) {
        risks = [{
          disease_ko:  d.disease_ko  || d.disease,
          disease:     d.disease,
          risk_score:  d.score       ?? 0,
          risk_level:  d.risk_level,
          note:        (d.reasons || []).join(' ') || d.action_ko || '',
        }];
      } else { risks = []; }
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
    const snap = d.env_snapshot;
    const snapFmt = v => v != null && !isNaN(Number(v)) ? Number(v).toFixed(1) : '—';
    const snapHtml = snap ? `<div style="font-size:10px;color:var(--muted);margin-top:8px">
      판단근거: 온도 ${snapFmt(snap.temp_internal)}°C / 습도 ${snapFmt(snap.humidity_int)}% / CO₂ ${snapFmt(snap.co2_ppm)}ppm</div>` : '';
    const actionHtml = d.action_ko ? `<div style="font-size:11px;color:var(--accent);margin-top:6px">💊 ${_esc(d.action_ko)}</div>` : '';
    el.innerHTML = `<div class="disease-grid">${cards}</div>${snapHtml}${actionHtml}`;
  } catch(e) {
    el.innerHTML = `<div class="err-inline" style="padding:12px">병해 조회 실패: ${_esc(e.message)}</div>`;
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

// ── 시스템: 모델 성능 ─────────────────────────────────────────────────────────
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

    const m3 = d.m3_revenue || [];
    const m3rows = m3.map(r => `
      <tr>
        <td>${_esc(r.crop)}</td>
        <td style="color:${mapeColor(r.mape_pct)};font-weight:600">${r.mape_pct}%</td>
        <td>${gateIcon(r.mape_pct <= 35)}</td>
        <td style="color:${gradeColor(r.grade)}">${_esc(r.grade||'⭐')}</td>
      </tr>`).join('');

    const apiTotal = Object.keys(d.api_connections||{}).length;
    const apiOk    = Object.values(d.api_connections||{}).filter(v=>v==='connected').length;

    el.innerHTML = `
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M1 생육 모델 (R² 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: R² ≥ 0.75 ⭐⭐ / ≥ 0.90 ⭐⭐⭐</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:14px">
        <thead><tr><th>작목</th><th>지표</th><th>R²</th><th>MAE</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m1rows || '<tr><td colspan="6" style="color:var(--muted);font-size:11px;text-align:center">m1_meta.json 없음</td></tr>'}</tbody>
      </table></div>
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M2 수확량 예측 (MAPE 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: MAPE ≤ 15% ⭐⭐⭐ / ≤ 30% ⭐⭐ / ≤ 35% Gate통과</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:14px">
        <thead><tr><th>작목</th><th>MAPE</th><th>CV R²</th><th>샘플</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m2rows || '<tr><td colspan="6" style="color:var(--muted);font-size:11px;text-align:center">데이터 없음</td></tr>'}</tbody>
      </table></div>
      <div style="font-size:11px;font-weight:700;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:8px">
        M3 수익 예측 (MAPE 기준)
        <span style="font-size:10px;font-weight:400;color:var(--muted)">임계치: MAPE ≤ 15% ⭐⭐⭐ / ≤ 20% ⭐⭐</span>
      </div>
      <div class="table-scroll-wrap"><table class="weather-tbl" style="margin-bottom:12px">
        <thead><tr><th>작목</th><th>MAPE</th><th>Gate</th><th>등급</th></tr></thead>
        <tbody>${m3rows || '<tr><td colspan="4" style="color:var(--muted);font-size:11px;text-align:center">데이터 없음</td></tr>'}</tbody>
      </table></div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:10px;color:var(--muted);margin-top:4px">
        <span>M4 원가: 파라미터 기반 ✅</span>
        <span>M5 질병: ${_esc(d.m5_disease?.status || 'stub모드')}</span>
        <span>API 연결: ${apiOk}/${apiTotal}개</span>
        <span>생성: ${d.generated_at ? new Date(d.generated_at).toLocaleString('ko-KR') : '—'}</span>
      </div>`;

    if (m2.length) {
      const avgR2 = m2.reduce((s, r) => s + (r.cv_r2 || 0), 0) / m2.length;
      setText('ml-avg-r2', avgR2.toFixed(3));
      const totalSamples = m2.reduce((s, r) => s + (r.n_samples || 0), 0);
      setText('ml-train-rows', totalSamples >= 1000 ? Math.round(totalSamples/1000) + 'K' : String(totalSamples));
      const gatePassCount = m2.filter(r => r.gate_pass != null ? r.gate_pass : r.mape_pct <= 35).length;
      setText('ml-data-quality', Math.round(gatePassCount / m2.length * 100) + '%');
    }
    if (d.generated_at) {
      setText('ml-last-train', 'D-' + Math.round((Date.now() - new Date(d.generated_at).getTime()) / 86400000));
    } else { setText('ml-last-train', '—'); }

    const r2Vals = m2.map(r => r.cv_r2 || 0).filter(v => v > 0);
    if (r2Vals.length) {
      const avgR2 = r2Vals.reduce((a,b)=>a+b,0) / r2Vals.length;
      setText('kpi-r2', avgR2.toFixed(3));
      setBar('bar-learning', Math.min(100, Math.round(Math.max(0, avgR2) * 100)), 'bv-learning');
    }
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
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

    const apis = d.apis || d.api_connections || {};
    const _safeUrl = u => (u && /^https?:\/\//.test(u)) ? _esc(u) : '#';
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

    const missing = d.missing_keys || {};
    const missRows = Object.entries(missing).map(([k, v]) =>
      `<tr>
        <td style="color:var(--yellow);font-size:11px">⚠️ ${_esc(v.service)}</td>
        <td style="font-size:10px">${_esc(v.used_for)}</td>
        <td><a href="${_safeUrl(v.get_key_url)}" target="_blank" style="color:var(--accent);font-size:10px">${_esc(v.cost || '발급')}</a></td>
      </tr>`
    ).join('');

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

    const allApis = Object.values(apis);
    const connectedCount = allApis.filter(a => { const s = (a?.status || a || '').toString(); return s === 'connected' || s === 'available' || s === 'fallback_active'; }).length;
    const fullCount = allApis.filter(a => { const s = (a?.status || a || '').toString(); return s === 'connected' || s === 'available'; }).length;
    const totalCount = allApis.length || 1;
    const connPct = Math.round(fullCount / totalCount * 100);
    setText('sys-api-conn', connPct + '%');
    setText('sys-api-hint', `${fullCount}/${totalCount} 연결 (폴백포함 ${connectedCount}개)`);
    setText('sys-ctrl-success', connPct + '%');
    setText('sys-sensor-conn', _wsActive ? '연결됨' : '—');
    setText('sys-ctrl-conn', fullCount > 0 ? '연결됨' : '—');
    setText('sys-ctrl-hint', fullCount > 0 ? `${fullCount}개 API` : '확인 필요');
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── M2 드리프트 모니터링 ────────────────────────────────────────────────────
async function loadModelDrift() {
  const el = $('drift-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch('/api/admin/models/drift');
    const crops = d.crops || {};
    const alertIcon = a => a === 'green' ? '🟢' : a === 'yellow' ? '🟡' : '🔴';
    const trendIcon = t => t === 'degrading' ? '↗ 악화' : t === 'improving' ? '↘ 개선' : '→ 안정';
    const mapeColor = v => isNaN(v) ? 'var(--muted)' : v <= 20 ? 'var(--green)' : v <= 35 ? 'var(--yellow)' : 'var(--red)';

    const overallAlert = d.overall_alert || 'yellow';
    const overallIcon  = alertIcon(overallAlert);
    const overallMsg   = overallAlert === 'green' ? '전 작목 예측 정확도 양호'
                       : overallAlert === 'red'   ? '일부 작목 재학습 권고'
                       : '일부 작목 모니터링 필요';

    const rows = Object.entries(crops).map(([crop, b]) => {
      const mape = b.mape != null && !isNaN(b.mape) ? b.mape.toFixed(1) + '%' : '데이터 부족';
      const trend = trendIcon(b.trend || 'stable');
      const bias  = b.bias != null && !isNaN(b.bias) ? (b.bias >= 0 ? '+' : '') + b.bias.toFixed(1) + '%' : '—';
      const last  = b.last_harvest ? b.last_harvest.slice(0, 10) : '—';
      return `<tr>
        <td>${_esc(crop)}</td>
        <td style="font-weight:700;color:${mapeColor(b.mape)}">${mape}</td>
        <td style="font-size:11px;color:var(--muted)">${bias}</td>
        <td style="font-size:11px">${trend}</td>
        <td style="text-align:center;font-size:16px">${alertIcon(b.alert||'yellow')}</td>
        <td style="font-size:10px;color:var(--muted)">${last}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:8px 10px;
                  background:var(--card-soft);border-radius:8px;border:1px solid var(--border)">
        <span style="font-size:18px">${overallIcon}</span>
        <span style="font-weight:600;font-size:13px">${overallMsg}</span>
      </div>
      <div class="table-scroll-wrap">
        <table class="weather-tbl">
          <thead><tr><th>작목</th><th>MAPE</th><th>편향</th><th>추세</th><th>상태</th><th>최근수확</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6" style="color:var(--muted);text-align:center;font-size:11px">수확 실측 데이터 없음</td></tr>'}</tbody>
        </table>
      </div>
      <div style="margin-top:8px;font-size:10px;color:var(--muted)">
        🔴 재학습: <code>/api/data/harvest</code> POST로 수확량 기록 누적 시 자동 개선
      </div>`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">드리프트 조회 실패: ${_esc(e.message)}</span>`;
  }
}
