/* ============================================================
   console_dashboard.js — PC 관리자 콘솔: 운영 현황 랜딩 요약
   ★ 클러스터 overview + 모델 성능을 합쳐 한눈 KPI·하이라이트 제공.
   ============================================================ */
(function () {
  'use strict';

  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
  var token = function () { try { return sessionStorage.getItem('sf_token') || ''; } catch (e) { return ''; } };
  var SYS_FARM = 'farm_001';
  var state = { loaded: false, loading: false };

  function base() { return location.origin; }

  async function getJSON(url, auth) {
    try {
      var r = await fetch(base() + url, auth ? { headers: { Authorization: 'Bearer ' + token() } } : undefined);
      if (r.ok) return await r.json();
    } catch (e) {}
    return null;
  }

  function kpis(cl, perf) {
    var s = (cl && cl.summary) || {};
    var m2 = (perf && perf.m2_yield) || [];
    var gatePass = m2.filter(function (m) { return m.gate_pass; }).length;
    var driftRisk = m2.filter(function (m) { return (m.mape_pct != null ? m.mape_pct : 999) > 35; }).length;
    var cards = [
      { v: cl ? (cl.total_farms || 0).toLocaleString() : '–', l: '관제 농가', c: 'var(--text)' },
      { v: s.anomaly != null ? s.anomaly : '–', l: '이상 농가 (' + (s.anomaly_pct != null ? s.anomaly_pct : '–') + '%)', c: 'var(--chart-hot,#dc2626)' },
      { v: s.warn != null ? s.warn : '–', l: '주의 농가', c: 'var(--chart-warn,#f59e0b)' },
      { v: s.avg_vigor != null ? s.avg_vigor : '–', l: '평균 작황 NDVI', c: 'var(--blue,#2563eb)' },
      { v: m2.length ? gatePass + '/' + m2.length : '–', l: 'M2 모델 게이트', c: (m2.length && gatePass === m2.length) ? 'var(--green)' : 'var(--chart-warn,#f59e0b)' },
      { v: perf ? driftRisk : '–', l: '드리프트 위험', c: driftRisk ? 'var(--chart-hot,#dc2626)' : 'var(--green)' }
    ];
    return cards.map(function (k) {
      return '<div class="cc-kpi"><div class="cc-kpi-v" style="color:' + k.c + '">' + esc(k.v) + '</div><div class="cc-kpi-l">' + esc(k.l) + '</div></div>';
    }).join('');
  }

  function highlights(cl, perf) {
    var out = [];
    // 이상 다발 지역 Top — by_region 이상 많은 순
    var br = (cl && cl.by_region) || [];
    var topAnom = br.slice().sort(function (a, b) { return (b.anomaly || 0) - (a.anomaly || 0); }).slice(0, 3)
      .filter(function (r) { return (r.anomaly || 0) > 0; });
    if (topAnom.length) {
      var items = topAnom.map(function (r) {
        return '<div class="dash-hl-row"><span class="dash-hl-name">' + esc(r.name) + '</span>' +
          '<span class="dash-hl-val" style="color:var(--chart-hot,#dc2626)">이상 ' + r.anomaly + '<span class="dash-hl-sub"> / ' + r.count + '농가</span></span></div>';
      }).join('');
      out.push('<a class="con-card" href="#cluster"><span class="ico">⚠️</span><span class="t">이상 다발 지역 Top 3</span>' + items + '</a>');
    }
    // 모델 위험 — 드리프트 🔴 작물
    var m2 = (perf && perf.m2_yield) || [];
    var risk = m2.filter(function (m) { return (m.mape_pct != null ? m.mape_pct : 999) > 35; });
    if (risk.length) {
      var ritems = risk.slice(0, 3).map(function (m) {
        return '<div class="dash-hl-row"><span class="dash-hl-name">' + esc(m.crop) + '</span>' +
          '<span class="dash-hl-val" style="color:var(--chart-hot,#dc2626)">MAPE ' + m.mape_pct + '%</span></div>';
      }).join('');
      out.push('<a class="con-card" href="#model"><span class="ico">🔴</span><span class="t">모델 드리프트 위험</span>' + ritems +
        '<div class="dash-hl-foot">재학습 검토 권장</div></a>');
    } else if (perf) {
      out.push('<a class="con-card" href="#model"><span class="ico">🟢</span><span class="t">모델 건전성 양호</span>' +
        '<div class="dash-hl-foot">M2 드리프트 위험 작물 없음</div></a>');
    }
    return out.join('');
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    var kEl = document.getElementById('dashKpis');
    var hEl = document.getElementById('dashHighlights');
    if (kEl) kEl.innerHTML = '<div class="cc-loading" style="grid-column:1/-1;">현황 집계 중…</div>';
    var res = await Promise.all([
      getJSON('/api/admin/cluster/overview', true).then(function (d) { return d || getJSON('/api/cluster/overview', false); }),
      getJSON('/api/farms/' + SYS_FARM + '/system/model-performance', true)
    ]);
    var cl = res[0], perf = res[1];
    state.loading = false; state.loaded = true;
    if (kEl) kEl.innerHTML = kpis(cl, perf);
    if (hEl) hEl.innerHTML = highlights(cl, perf);
  }

  window.ConsoleDashboard = {
    ensure: function () { if (state.loaded) return; load(); }
  };
})();
