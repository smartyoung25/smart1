/* ============================================================
   console_cluster.js — PC 관리자 콘솔: 클러스터 관제 풀폭 네이티브 뷰
   ★ C20(c20_cluster_admin.html) 모바일 480px 화면을 PC 풀폭 Analytics Dashboard로 승격.
   ★ 동일 데이터 계약 사용: /api/admin/cluster/overview → /api/cluster/overview → 데모 폴백.
   ============================================================ */
(function () {
  'use strict';

  // 오프라인·차단 시 최종 폴백 샘플(PII 없음·합성) — C20 모바일과 동일 데이터셋
  var DEMO = {"total_farms":725,"summary":{"avg_vigor":0.643,"avg_diag":70,"anomaly":227,"warn":200,"normal":298,"anomaly_pct":31.3},"regions":["전남","경기","경남","전북","충남","경북","강원","충북"],"crops":["딸기","완숙토마토","방울토마토","파프리카","오이","국화","참외","가지","감귤"],"by_region":[{"name":"전남","count":187,"avg_vigor":0.624,"avg_diag":71,"anomaly":62,"warn":60},{"name":"경기","count":121,"avg_vigor":0.64,"avg_diag":69,"anomaly":39,"warn":38},{"name":"경남","count":96,"avg_vigor":0.635,"avg_diag":71,"anomaly":31,"warn":17},{"name":"전북","count":93,"avg_vigor":0.658,"avg_diag":68,"anomaly":26,"warn":34},{"name":"충남","count":85,"avg_vigor":0.65,"avg_diag":71,"anomaly":26,"warn":18},{"name":"경북","count":51,"avg_vigor":0.667,"avg_diag":72,"anomaly":13,"warn":11},{"name":"강원","count":43,"avg_vigor":0.677,"avg_diag":69,"anomaly":13,"warn":10},{"name":"충북","count":33,"avg_vigor":0.648,"avg_diag":69,"anomaly":8,"warn":11}],"by_crop":[{"name":"딸기","count":192,"avg_vigor":0.643,"avg_diag":69,"anomaly":58,"warn":56},{"name":"완숙토마토","count":194,"avg_vigor":0.645,"avg_diag":70,"anomaly":57,"warn":52},{"name":"방울토마토","count":138,"avg_vigor":0.653,"avg_diag":70,"anomaly":41,"warn":43},{"name":"파프리카","count":90,"avg_vigor":0.629,"avg_diag":70,"anomaly":33,"warn":22},{"name":"오이","count":51,"avg_vigor":0.62,"avg_diag":70,"anomaly":18,"warn":16},{"name":"국화","count":18,"avg_vigor":0.634,"avg_diag":71,"anomaly":9,"warn":3},{"name":"참외","count":26,"avg_vigor":0.681,"avg_diag":75,"anomaly":5,"warn":5},{"name":"가지","count":5,"avg_vigor":0.633,"avg_diag":64,"anomaly":2,"warn":1},{"name":"감귤","count":3,"avg_vigor":0.708,"avg_diag":61,"anomaly":2,"warn":0}],"alerts":[{"location":"전남 장흥","crop":"파프리카","detail":"작황 NDVI 0.42 · 진단 87점","farm_id":"전남_장흥_파프리카_20_1","vigor":0.42,"diag":87},{"location":"충남 부여","crop":"방울토마토","detail":"작황 NDVI 0.42 · 진단 68점","farm_id":"충남_부여_방울토마토_13_1","vigor":0.42,"diag":68},{"location":"경기 평택","crop":"방울토마토","detail":"작황 NDVI 0.42 · 진단 51점","farm_id":"경기_평택_방울토마토_8_2","vigor":0.421,"diag":51},{"location":"경기 안성","crop":"오이","detail":"작황 NDVI 0.42 · 진단 67점","farm_id":"경기_안성_오이_9_1","vigor":0.421,"diag":67},{"location":"전남 장성","crop":"파프리카","detail":"작황 NDVI 0.42 · 진단 68점","farm_id":"전남_장성_파프리카_25_1","vigor":0.421,"diag":68},{"location":"경남 사천","crop":"완숙토마토","detail":"작황 NDVI 0.42 · 진단 88점","farm_id":"경남_사천_완숙토마토_58_1","vigor":0.421,"diag":88}]};

  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
  var vcol = function (v) { return v >= 0.62 ? 'var(--chart-good,#16a34a)' : v >= 0.55 ? 'var(--chart-warn,#f59e0b)' : 'var(--chart-hot,#dc2626)'; };
  var token = function () { try { return sessionStorage.getItem('sf_token') || ''; } catch (e) { return ''; } };

  var state = { data: null, isDemo: false, inited: false, loading: false };

  function apiBase() { return location.origin; }

  async function fetchOverview(region, crop) {
    var qs = 'region=' + encodeURIComponent(region || '') + '&crop=' + encodeURIComponent(crop || '');
    var base = apiBase();
    // 1순위: admin (Bearer). PUBLIC_DEMO=1 환경은 403 → 공개 폴백.
    try {
      var r = await fetch(base + '/api/admin/cluster/overview?' + qs, { headers: { Authorization: 'Bearer ' + token() } });
      if (r.ok) return { data: await r.json(), isDemo: false, admin: true };
    } catch (e) {}
    // 2순위: 공개 조회 전용(실데이터)
    try {
      var rp = await fetch(base + '/api/cluster/overview?' + qs);
      if (rp.ok) return { data: await rp.json(), isDemo: false, admin: false };
    } catch (e) {}
    // 3순위: 데모 샘플
    return { data: DEMO, isDemo: true, admin: false };
  }

  function kpiStrip(d) {
    var s = d.summary || {};
    var cards = [
      { v: (d.total_farms || 0).toLocaleString(), l: '관제 농가', c: 'var(--text)' },
      { v: s.anomaly, l: '이상 (' + s.anomaly_pct + '%)', c: 'var(--chart-hot,#dc2626)' },
      { v: s.warn, l: '주의', c: 'var(--chart-warn,#f59e0b)' },
      { v: s.normal, l: '정상', c: 'var(--chart-good,#16a34a)' },
      { v: s.avg_vigor, l: '평균 작황 NDVI', c: 'var(--blue,#2563eb)' },
      { v: s.avg_diag + '점', l: '평균 진단', c: 'var(--purple,#7c3aed)' }
    ];
    return '<div class="cc-kpi-row">' + cards.map(function (k) {
      return '<div class="cc-kpi"><div class="cc-kpi-v" style="color:' + k.c + '">' + esc(k.v) + '</div><div class="cc-kpi-l">' + esc(k.l) + '</div></div>';
    }).join('') + '</div>';
  }

  function clusterTable(rows, title) {
    var max = Math.max.apply(null, (rows || []).map(function (r) { return r.count; }).concat([1]));
    var body = (rows || []).map(function (r) {
      var w = Math.round(r.count / max * 100);
      return '<tr>' +
        '<td class="cc-name">' + esc(r.name) + '</td>' +
        '<td class="cc-barcell"><div class="cc-bar"><i style="width:' + w + '%;background:' + vcol(r.avg_vigor) + '"></i></div></td>' +
        '<td class="cc-num">' + r.count + '</td>' +
        '<td class="cc-num" style="color:' + vcol(r.avg_vigor) + ';font-weight:800;">' + r.avg_vigor + '</td>' +
        '<td class="cc-num">' + (r.avg_diag != null ? r.avg_diag : '–') + '</td>' +
        '<td class="cc-num">' + (r.anomaly ? '<span class="cc-anom">⚠ ' + r.anomaly + '</span>' : '<span class="cc-ok">–</span>') + '</td>' +
        '</tr>';
    }).join('') || '<tr><td colspan="6" class="cc-empty">데이터 없음</td></tr>';
    return '<div class="cc-card"><div class="cc-card-h">' + esc(title) + '</div>' +
      '<table class="cc-table"><thead><tr><th>구분</th><th>규모</th><th>농가</th><th>작황</th><th>진단</th><th>이상</th></tr></thead>' +
      '<tbody>' + body + '</tbody></table></div>';
  }

  function alertsTable(alerts) {
    var rows = (alerts || []).map(function (a) {
      var sev = a.vigor != null ? (a.vigor >= 0.62 ? 'good' : a.vigor >= 0.55 ? 'warn' : 'hot') : 'warn';
      return '<tr>' +
        '<td class="cc-loc">📍 ' + esc(a.location) + '</td>' +
        '<td>' + esc(a.crop) + '</td>' +
        '<td class="cc-num cc-sev-' + sev + '">' + (a.vigor != null ? a.vigor : '–') + '</td>' +
        '<td class="cc-num">' + (a.diag != null ? a.diag + '점' : '–') + '</td>' +
        '<td class="cc-det">' + esc(a.detail) + '</td>' +
        '<td class="cc-drill-cell">' +
          '<button class="cc-drill cc-drill-sat" data-fid="' + esc(a.farm_id) + '" title="위성 작황 상세">🛰️ 위성</button>' +
          '<button class="cc-drill" data-fid="' + esc(a.farm_id) + '">진단 →</button>' +
        '</td>' +
        '</tr>';
    }).join('');
    if (!rows) rows = '<tr><td colspan="6" class="cc-empty" style="color:var(--green)">✅ 이상 농가 없음</td></tr>';
    return '<div class="cc-card cc-card-full">' +
      '<div class="cc-card-h">이상 농가 위치특정 <span class="cc-pill-live">🟢 진단→위치→실행</span></div>' +
      '<div class="cc-tablewrap"><table class="cc-table cc-table-alerts"><thead><tr>' +
      '<th>위치</th><th>작목</th><th>작황 NDVI</th><th>진단</th><th>상세</th><th>조치</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div></div>';
  }

  function render(d, isDemo) {
    var root = document.getElementById('clusterView');
    if (!root) return;
    var demoTag = isDemo ? ' · 🧪 샘플 시뮬레이션(데모)' : '';
    root.innerHTML =
      '<div class="cc-head">' +
        '<div><h1>클러스터 관제</h1><p class="cc-sub">평균 작황 NDVI ' + esc((d.summary || {}).avg_vigor) + ' · 평균 진단 ' + esc((d.summary || {}).avg_diag) + '점' + demoTag + '</p></div>' +
        '<div class="cc-actions">' +
          '<div class="cc-filters">' +
            '<select id="ccRegion"></select>' +
            '<select id="ccCrop"></select>' +
          '</div>' +
          '<button class="cc-btn cc-btn-report" id="ccReport">📄 보고서 PDF</button>' +
          '<button class="cc-btn cc-btn-notify" id="ccNotify">🔔 이상농가 일괄 알림</button>' +
        '</div>' +
      '</div>' +
      '<div class="cc-msg" id="ccMsg"></div>' +
      kpiStrip(d) +
      '<div class="cc-grid2">' + clusterTable(d.by_region, '지역 클러스터') + clusterTable(d.by_crop, '작목 클러스터') + '</div>' +
      alertsTable(d.alerts);

    // 필터 옵션
    if (!state.inited) {
      var fr = document.getElementById('ccRegion'), fc = document.getElementById('ccCrop');
      fr.innerHTML = '<option value="">전체 지역</option>' + (d.regions || []).map(function (r) { return '<option value="' + esc(r) + '">' + esc(r) + '</option>'; }).join('');
      fc.innerHTML = '<option value="">전체 작목</option>' + (d.crops || []).map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
      state.inited = true;
    } else {
      // 재렌더 시 선택값 복원
      document.getElementById('ccRegion').value = state.region || '';
      document.getElementById('ccCrop').value = state.crop || '';
    }
    bindEvents();
  }

  function bindEvents() {
    var fr = document.getElementById('ccRegion'), fc = document.getElementById('ccCrop');
    if (fr) fr.addEventListener('change', reload);
    if (fc) fc.addEventListener('change', reload);
    var rep = document.getElementById('ccReport');
    if (rep) rep.addEventListener('click', function () {
      window.open('/screens/c20_report.html?region=' + encodeURIComponent(state.region || '') + '&crop=' + encodeURIComponent(state.crop || ''), '_blank');
    });
    var nt = document.getElementById('ccNotify');
    if (nt) nt.addEventListener('click', notify);
    var btns = document.querySelectorAll('.cc-drill');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var fid = this.getAttribute('data-fid');
        try { sessionStorage.setItem('sf_farm_id', fid); } catch (e) {}
        if (this.classList.contains('cc-drill-sat')) {
          // 콘솔 내 위성 작황 상세로 드릴다운(풀폭)
          if (window.ConsoleSatellite) window.ConsoleSatellite.setFarm(fid);
          location.hash = '#satellite';
        } else {
          // 개별 진단(c17)은 새 탭
          window.open('/screens/c17_diagnosis.html?farm=' + encodeURIComponent(fid), '_blank');
        }
      });
    }
  }

  function msg(t, c) { var el = document.getElementById('ccMsg'); if (el) { el.style.color = c || 'var(--text)'; el.textContent = t; } }

  async function notify() {
    var d = state.data;
    if (!d || !(d.alerts || []).length) { msg('이상 농가가 없습니다.', 'var(--muted)'); return; }
    var ids = (d.alerts || []).map(function (a) { return a.farm_id; });
    if (state.isDemo) { msg('🧪 샘플 시뮬레이션 — 실제 환경에서는 이상 농가 ' + ids.length + '곳에 현장점검 지시가 일괄 기록됩니다.', 'var(--orange)'); return; }
    if (!confirm('이상 농가 ' + ids.length + '곳에 현장점검 지시를 기록할까요?')) return;
    try {
      var r = await fetch(apiBase() + '/api/admin/cluster/notify', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() },
        body: JSON.stringify({ farm_ids: ids, region: state.region || '', crop: state.crop || '', message: '위성·진단 기반 작황 이상 — 현장 점검 요망' })
      });
      if (r.ok) { var j = await r.json(); msg('✓ ' + j.recorded + '곳 지시 기록 · ' + (j.note || ''), j.dispatched ? 'var(--green)' : 'var(--orange)'); }
      else { msg('알림 기록 실패 (' + r.status + ') — 관리자 권한 필요', 'var(--red)'); }
    } catch (e) { msg('알림 기록 실패: ' + e.message, 'var(--red)'); }
  }

  async function reload() {
    if (state.loading) return;
    state.loading = true;
    state.region = (document.getElementById('ccRegion') || {}).value || '';
    state.crop = (document.getElementById('ccCrop') || {}).value || '';
    var res = await fetchOverview(state.region, state.crop);
    state.data = res.data; state.isDemo = res.isDemo;
    state.loading = false;
    if (!res.data || res.data.total_farms == null) { msg('데이터 없음', 'var(--muted)'); return; }
    render(res.data, res.isDemo);
  }

  // 콘솔 라우터가 #cluster 최초 진입 시 호출
  window.ConsoleCluster = {
    ensure: function () {
      if (state.data) return;            // 이미 로드됨
      var root = document.getElementById('clusterView');
      if (root) root.innerHTML = '<div class="cc-loading">클러스터 데이터 집계 중…</div>';
      reload();
    }
  };
})();
