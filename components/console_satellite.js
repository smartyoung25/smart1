/* ============================================================
   console_satellite.js — PC 관리자 콘솔: 위성 작황(필지 NDVI) 풀폭 네이티브 뷰
   ★ F8(f8_cluster.html) 단일농가 필지 NDVI 상세를 PC 풀폭으로 승격.
   ★ 데이터: /api/farms/{farm_id}/field/cluster (클러스터 관제에서 드릴다운).
   ============================================================ */
(function () {
  'use strict';

  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
  var token = function () { try { return sessionStorage.getItem('sf_token') || ''; } catch (e) { return ''; } };
  var ncol = function (v) { return v >= 0.70 ? 'var(--chart-good,#16a34a)' : v >= 0.55 ? 'var(--chart-warn,#f59e0b)' : 'var(--chart-hot,#dc2626)'; };
  // 연속 색상(0.40~0.90) — F8 _heatColor 동일 로직
  function heatColor(v) {
    var t = Math.max(0, Math.min(1, (v - 0.40) / 0.50));
    var r = t < 0.5 ? 220 : Math.round(220 - (t - 0.5) * 2 * 180);
    var g = t < 0.5 ? Math.round(38 + t * 2 * 120) : 158;
    return 'rgb(' + r + ',' + g + ',38)';
  }

  var state = { farmId: 'farm_001', data: null, loading: false, lastFarm: null };

  function apiBase() { return location.origin; }

  async function fetchCluster(farmId) {
    try {
      var r = await fetch(apiBase() + '/api/farms/' + encodeURIComponent(farmId) + '/field/cluster',
        { headers: { Authorization: 'Bearer ' + token() } });
      if (r.ok) return await r.json();
    } catch (e) {}
    return null;
  }

  function kpiStrip(d) {
    var s = d.summary || {}, w = d.weather_stress || {};
    var cards = [
      { v: s.vigor_grade || '–', l: '작황 등급', c: 'var(--text)' },
      { v: s.mean_ndvi, l: '평균 NDVI', c: ncol(s.mean_ndvi || 0) },
      { v: (s.uniformity_pct || 0) + '%', l: '작황 균일도', c: 'var(--blue,#2563eb)' },
      { v: s.anomaly_count || 0, l: '이상 필지', c: 'var(--chart-hot,#dc2626)' },
      { v: s.warn_count || 0, l: '주의 필지', c: 'var(--chart-warn,#f59e0b)' },
      { v: (w.water_stress_pct != null ? w.water_stress_pct + '%' : '–'), l: '수분 스트레스', c: (w.water_stress_pct >= 25 ? 'var(--chart-warn,#f59e0b)' : 'var(--green)') }
    ];
    return '<div class="cc-kpi-row">' + cards.map(function (k) {
      return '<div class="cc-kpi"><div class="cc-kpi-v" style="color:' + k.c + '">' + esc(k.v) + '</div><div class="cc-kpi-l">' + esc(k.l) + '</div></div>';
    }).join('') + '</div>';
  }

  function heatmap(parcels) {
    var tiles = (parcels || []).map(function (p) {
      var ring = p.status === '이상' ? 'box-shadow:0 0 0 2px var(--chart-hot,#dc2626);' : '';
      return '<div class="sat-tile" title="' + esc(p.name) + ' · NDVI ' + p.ndvi.toFixed(2) + ' (' + esc(p.status) + ')" ' +
        'style="background:' + heatColor(p.ndvi) + ';' + ring + '">' + p.ndvi.toFixed(2).slice(1) + '</div>';
    }).join('') || '<div class="cc-empty">필지 없음</div>';
    return '<div class="cc-card"><div class="cc-card-h">필지별 식생활력 (NDVI) <span class="cc-pill-live" style="background:var(--blue-soft);color:var(--blue)">🛰️ 무센서</span></div>' +
      '<div class="sat-heat">' + tiles + '</div>' +
      '<div class="sat-legend"><span>저활력</span><span class="sat-legend-bar"></span><span>고활력</span></div></div>';
  }

  function parcelTable(parcels) {
    var rows = (parcels || []).map(function (p) {
      return '<tr>' +
        '<td class="cc-name">' + esc(p.name) + '</td>' +
        '<td>' + esc(p.crop) + '</td>' +
        '<td class="cc-num">' + (p.area_ha != null ? p.area_ha + 'ha' : '–') + '</td>' +
        '<td class="cc-num" style="color:' + ncol(p.ndvi) + ';font-weight:800;">' + p.ndvi.toFixed(2) + '</td>' +
        '<td class="cc-num">' + (p.deviation_pct > 0 ? '+' : '') + p.deviation_pct + '%</td>' +
        '<td><span class="sat-status sat-' + (p.status === '이상' ? 'hot' : p.status === '주의' ? 'warn' : 'good') + '">' + esc(p.status) + '</span></td>' +
        '</tr>';
    }).join('') || '<tr><td colspan="6" class="cc-empty">필지 없음</td></tr>';
    return '<div class="cc-card"><div class="cc-card-h">필지 상세</div>' +
      '<table class="cc-table"><thead><tr><th>필지</th><th>작목</th><th>면적</th><th>NDVI</th><th>Δ평균</th><th>상태</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function alertsTable(alerts) {
    var rows = (alerts || []).map(function (a) {
      var sev = a.severity === 'danger' ? 'hot' : 'warn';
      return '<tr>' +
        '<td class="cc-loc">📍 ' + esc(a.location) + '</td>' +
        '<td>' + esc(a.type) + '</td>' +
        '<td class="cc-num cc-sev-' + sev + '">' + (a.ndvi != null ? a.ndvi.toFixed(2) : '–') + '</td>' +
        '<td class="cc-num">' + (a.deviation_pct > 0 ? '+' : '') + a.deviation_pct + '%</td>' +
        '<td><span class="sat-status sat-' + sev + '">' + (a.severity === 'danger' ? '시급' : '주의') + '</span></td>' +
        '<td class="cc-det">' + esc(a.action) + '</td>' +
        '</tr>';
    }).join('');
    if (!rows) rows = '<tr><td colspan="6" class="cc-empty" style="color:var(--green)">✅ 이상 필지 없음 — 작황 균일</td></tr>';
    return '<div class="cc-card cc-card-full"><div class="cc-card-h">위치특정 이상 알림 <span class="cc-pill-live">🟢 진단→위치→실행</span></div>' +
      '<div class="cc-tablewrap"><table class="cc-table"><thead><tr><th>위치</th><th>유형</th><th>NDVI</th><th>Δ평균</th><th>심각도</th><th>조치</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div></div>';
  }

  function render(d, farmId) {
    var root = document.getElementById('satelliteView');
    if (!root) return;
    if (!d) { root.innerHTML = '<div class="cc-loading">위성 작황 데이터를 불러오지 못했습니다 (' + esc(farmId) + ').</div>'; return; }
    var src = d.source === 'sentinel-2' ? '🛰️ Sentinel-2 실측' : '🛰️ 위성 프록시(미연동)';
    var w = d.weather_stress || {};
    root.innerHTML =
      '<div class="cc-head">' +
        '<div><h1>위성 작황 <span class="sat-srcbadge">' + esc(src) + '</span></h1>' +
        '<p class="cc-sub">' + esc(d.region || '') + ' · ' + esc(farmId) + ' · ' + (d.parcel_count || 0) + '필지 · ' + (d.total_area_ha || 0) + 'ha</p></div>' +
        '<div class="cc-actions"><a class="cc-btn cc-btn-report" href="#cluster">‹ 클러스터 관제로</a></div>' +
      '</div>' +
      (w.note ? '<div class="sat-wx">🌦️ <b>무센서 기상 스트레스</b> — ' + esc(w.note) + (w.water_stress_pct >= 25 ? ' <b style="color:var(--orange)">(관개 우선 검토)</b>' : '') + '</div>' : '') +
      kpiStrip(d) +
      '<div class="cc-grid2">' + heatmap(d.parcels) + parcelTable(d.parcels) + '</div>' +
      alertsTable(d.alerts);
  }

  async function load(farmId) {
    if (state.loading) return;
    state.loading = true;
    var root = document.getElementById('satelliteView');
    if (root && state.lastFarm !== farmId) root.innerHTML = '<div class="cc-loading">위성 작황 집계 중… (' + esc(farmId) + ')</div>';
    var d = await fetchCluster(farmId);
    state.loading = false;
    state.data = d; state.lastFarm = farmId;
    render(d, farmId);
  }

  window.ConsoleSatellite = {
    setFarm: function (fid) { if (fid) state.farmId = fid; },
    ensure: function () {
      // 이미 같은 농가 로드됨 → 스킵
      if (state.data && state.lastFarm === state.farmId) return;
      load(state.farmId);
    }
  };
})();
