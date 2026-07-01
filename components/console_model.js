/* ============================================================
   console_model.js — PC 관리자 콘솔: AI 학습·모델 풀폭 네이티브 뷰
   ★ C6(c6_learning.html) 모델 성능·게이트·드리프트를 PC 풀폭 대시보드로 승격.
   ★ 데이터: /api/farms/{id}/system/model-performance (작물별 모델은 전역 메트릭).
   ============================================================ */
(function () {
  'use strict';

  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
  var token = function () { try { return sessionStorage.getItem('sf_token') || ''; } catch (e) { return ''; } };
  // 모델 성능은 전역 메트릭 — 대표 농가 farm_001 경로로 조회
  var SYS_FARM = 'farm_001';

  var state = { data: null, adv: null, loading: false };

  function apiBase() { return location.origin; }

  async function fetchPerf() {
    try {
      var r = await fetch(apiBase() + '/api/farms/' + SYS_FARM + '/system/model-performance',
        { headers: { Authorization: 'Bearer ' + token() } });
      if (r.ok) return await r.json();
    } catch (e) {}
    return null;
  }

  // 제안형 스케줄러가 기록한 재학습 권고(감지→제안, 자동실행 안 함)
  async function fetchAdvisories() {
    try {
      var r = await fetch(apiBase() + '/api/admin/models/advisories',
        { headers: { Authorization: 'Bearer ' + token() } });
      if (r.ok) return await r.json();
    } catch (e) {}
    return null;
  }

  function num(n) { return (n == null ? 0 : n).toLocaleString(); }

  function kpiStrip(d) {
    var m1 = d.m1_growth || [], m2 = d.m2_yield || [];
    var totalN = m1.concat(m2).reduce(function (s, m) { return s + (m.n_train || m.n_samples || 0); }, 0);
    var avgR2 = m1.length ? m1.reduce(function (s, m) { return s + (m.r2 || 0); }, 0) / m1.length : 0;
    var gatePass = m2.filter(function (m) { return m.gate_pass; }).length;
    var driftRisk = m2.filter(function (m) { return (m.mape_pct != null ? m.mape_pct : 999) > 35; }).length;
    var cards = [
      { v: num(totalN), l: '누적 학습 샘플', c: 'var(--blue,#2563eb)' },
      { v: avgR2 ? avgR2.toFixed(3) : '–', l: '평균 M1 생육 R²', c: 'var(--green)' },
      { v: m2.length ? gatePass + '/' + m2.length : '–', l: 'M2 게이트 통과', c: (m2.length && gatePass === m2.length) ? 'var(--green)' : 'var(--chart-warn,#f59e0b)' },
      { v: driftRisk, l: 'M2 드리프트 위험', c: driftRisk ? 'var(--chart-hot,#dc2626)' : 'var(--green)' },
      { v: m1.length, l: 'M1 생육 모델', c: 'var(--purple,#7c3aed)' },
      { v: (d.m3_revenue || []).length, l: 'M3 매출 모델', c: 'var(--text)' }
    ];
    return '<div class="cc-kpi-row">' + cards.map(function (k) {
      return '<div class="cc-kpi"><div class="cc-kpi-v" style="color:' + k.c + '">' + esc(k.v) + '</div><div class="cc-kpi-l">' + esc(k.l) + '</div></div>';
    }).join('') + '</div>';
  }

  function pipeline() {
    var steps = [
      ['📥', '데이터 수집', '센서·관수·생육·수확 실측', '실시간'],
      ['🔧', 'ETL 변환', 'canonical 정규화 → parquet', '야간'],
      ['🛰️', '외부기상 보강', 'ERA5 재분석 결측 보완', 'ERA5'],
      ['🧠', '모델 학습', 'M1 생육·M2 수확·M5 병해', '주간'],
      ['✅', '게이트 검증', 'MAPE·R² 기준 통과 시 배포', '자동']
    ];
    return '<div class="cc-card cc-card-full"><div class="cc-card-h">학습 파이프라인 ' +
      '<span class="cm-gate-info">통과 기준: MAPE ≤ 35% AND R² ≥ 0 · 챔피언/챌린저 자동선택(미달 시 rollback)</span></div>' +
      '<div class="cm-pipe">' + steps.map(function (s, i) {
        return '<div class="cm-pipe-step"><div class="cm-pipe-ico">' + s[0] + '</div>' +
          '<div class="cm-pipe-body"><div class="cm-pipe-t">' + esc(s[1]) + '</div><div class="cm-pipe-s">' + esc(s[2]) + '</div></div>' +
          '<span class="cm-pipe-badge">' + esc(s[3]) + '</span></div>' +
          (i < steps.length - 1 ? '<div class="cm-pipe-arrow">→</div>' : '');
      }).join('') + '</div></div>';
  }

  function m2GateTable(m2) {
    var rows = (m2 || []).map(function (m) {
      var mape = m.mape_pct != null ? m.mape_pct.toFixed(1) : '–';
      var r2 = m.cv_r2 != null ? m.cv_r2.toFixed(2) : '–';
      var mc = (m.mape_pct != null && m.mape_pct <= 35) ? 'var(--chart-good,#16a34a)' : 'var(--chart-hot,#dc2626)';
      var badge = m.gate_pass
        ? '<span class="cm-badge cm-pass">✅ 통과</span>'
        : '<span class="cm-badge cm-fail">⛔ 폴백</span>';
      return '<tr><td class="cc-name">' + esc(m.crop) + '</td>' +
        '<td class="cc-num">' + num(m.n_samples) + '</td>' +
        '<td class="cc-num" style="color:' + mc + ';font-weight:800;">' + mape + '%</td>' +
        '<td class="cc-num">' + r2 + '</td>' +
        '<td>' + badge + '</td></tr>';
    }).join('') || '<tr><td colspan="5" class="cc-empty">데이터 없음</td></tr>';
    return '<div class="cc-card"><div class="cc-card-h">M2 수확량 모델 게이트</div>' +
      '<table class="cc-table"><thead><tr><th>작물</th><th>샘플</th><th>MAPE</th><th>CV R²</th><th>게이트</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function m2DriftCard(m2) {
    var rows = (m2 || []).map(function (m) {
      var mape = m.mape_pct != null ? m.mape_pct : 999;
      var st = mape <= 20 ? { d: '🟢', l: '양호', c: 'var(--green-dark)' }
        : mape <= 35 ? { d: '🟡', l: '주의·재학습 권고', c: 'var(--orange)' }
        : { d: '🔴', l: '위험·폴백', c: 'var(--chart-hot,#dc2626)' };
      var w = Math.min(100, Math.round(mape / 50 * 100));
      return '<div class="cm-drift">' +
        '<div class="cm-drift-head"><span>' + st.d + '</span><span class="cm-drift-name">' + esc(m.crop) + '</span>' +
        '<span class="cm-drift-mape" style="color:' + st.c + '">MAPE ' + (mape === 999 ? '–' : mape + '%') + '</span></div>' +
        '<div class="cm-drift-bar"><i style="width:' + w + '%;background:' + st.c + '"></i></div>' +
        '<div class="cm-drift-label" style="color:' + st.c + '">' + st.l + '</div></div>';
    }).join('') || '<div class="cc-empty">데이터 없음</div>';
    return '<div class="cc-card"><div class="cc-card-h">M2 학습시 성능 (CV MAPE) ' +
      '<span class="cc-pill-live" style="background:var(--blue-soft);color:var(--blue)">🔵 학습 평가</span>' +
      '<span class="cm-gate-info">학습 시점 검증값 — 현재(라이브) 드리프트는 상단 \'재학습 권고\' 참조</span></div>' + rows + '</div>';
  }

  // 재학습 권고 배너 — 제안형 스케줄러 결과. 자동 실행 안 함, 관리자 승인 후 재학습.
  function advisoryCard() {
    var adv = state.adv;
    if (!adv || !adv.count) return '';
    var sevC = { high: 'var(--chart-hot,#dc2626)', medium: 'var(--orange,#f59e0b)', low: 'var(--muted)' };
    var items = (adv.advisories || []).map(function (a) {
      var c = sevC[a.severity] || 'var(--muted)';
      var mape = (a.mape != null) ? ' · 라이브 MAPE ' + a.mape + '%' : '';
      var crop = a.crop === '*' ? '전체' : a.crop;
      var arg = (a.crop === '*' ? '' : a.crop);
      return '<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);">' +
        '<span style="width:9px;height:9px;border-radius:50%;background:' + c + ';flex:0 0 auto;"></span>' +
        '<b style="min-width:74px;color:' + c + ';">' + esc(crop) + '</b>' +
        '<span style="flex:1;color:var(--muted);font-size:13px;">' + esc((a.reason || '') + mape) + '</span>' +
        '<button onclick="ConsoleModel.approve(\'' + esc(arg) + '\',this)" title="관리자 승인 시 재학습 실행(제안→실행)" ' +
        'style="flex:0 0 auto;font-size:12px;font-weight:800;padding:6px 12px;border:1.5px solid ' + c + ';color:' + c + ';background:transparent;border-radius:8px;cursor:pointer;min-height:34px;">▶ 재학습 승인</button>' +
        '</div>';
    }).join('');
    var when = adv.generated_at ? String(adv.generated_at).slice(0, 16).replace('T', ' ') : '';
    return '<div class="cc-card cc-card-full" style="border-left:4px solid var(--chart-hot,#dc2626);">' +
      '<div class="cc-card-h">🔁 재학습 권고 ' + adv.count + '건 ' +
      '<span class="cm-gate-info">최근 실측 대비 라이브 드리프트 · 제안형(자동 실행 안 함) — 승인 시 재학습 · 점검 ' + esc(when) + '</span></div>' +
      items + '</div>';
  }

  function matrix(d) {
    var m1 = d.m1_growth || [], m2 = d.m2_yield || [], m3 = d.m3_revenue || [];
    var avgR2 = m1.length ? (m1.reduce(function (s, x) { return s + (x.r2 || 0); }, 0) / m1.length) : 0;
    var m3mape = m3.length ? (m3.reduce(function (s, x) { return s + (x.mape_pct || 0); }, 0) / m3.length) : 0;
    var rows = [
      ['M1 생육', m1.length ? m1.length + '작물·타깃 · 평균 R² ' + avgR2.toFixed(3) : '–', m1.some(function (x) { return x.gate_pass; }) ? '✅' : '⚠️'],
      ['M2 수확량', m2.length ? m2.filter(function (x) { return x.gate_pass; }).length + '/' + m2.length + ' 게이트 통과' : '–', m2.some(function (x) { return x.gate_pass; }) ? '✅' : '⚠️'],
      ['M3 매출', m3.length ? m3.length + '작물 · 평균 MAPE ' + m3mape.toFixed(1) + '%' : '–', m3.length ? '✅' : '–'],
      ['M4 원가', (d.m4_cost || {}).status === 'parameter_based' ? '파라미터 기반' : '–', (d.m4_cost || {}).grade || '–'],
      ['M5 병해', '규칙기반 v2 · 8병해', (d.m5_disease || {}).grade || '⚠️'],
      ['관수(Priva)', (d.priva_irrigation || {}).status === 'active' ? '활성' : '–', (d.priva_irrigation || {}).grade || '–']
    ];
    var body = rows.map(function (r) {
      return '<tr><td class="cc-name">' + esc(r[0]) + '</td><td class="cc-det">' + esc(r[1]) + '</td><td class="cc-num" style="font-size:14px;">' + esc(r[2]) + '</td></tr>';
    }).join('');
    return '<div class="cc-card cc-card-full"><div class="cc-card-h">모델 성능 매트릭스 (M1~M5 · 관수)</div>' +
      '<table class="cc-table"><thead><tr><th>모델</th><th>현황</th><th>등급</th></tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  function m1Table(m1) {
    var rows = (m1 || []).slice().sort(function (a, b) { return (b.r2 || 0) - (a.r2 || 0); }).map(function (m) {
      var r2 = m.r2 != null ? m.r2.toFixed(3) : '–';
      var c = m.r2 > 0.6 ? 'var(--chart-good,#16a34a)' : m.r2 > 0.3 ? 'var(--chart-warn,#f59e0b)' : 'var(--chart-hot,#dc2626)';
      return '<tr><td class="cc-name">' + esc(m.crop) + '</td><td>' + esc(m.target) + '</td>' +
        '<td class="cc-num" style="color:' + c + ';font-weight:800;">' + r2 + '</td>' +
        '<td class="cc-num">' + num(m.n_train || m.n_samples) + '</td>' +
        '<td class="cc-num">' + esc(m.grade || '') + '</td>' +
        '<td>' + (m.gate_pass ? '<span class="cm-badge cm-pass">✅</span>' : '<span class="cm-badge cm-fail">⛔</span>') + '</td></tr>';
    }).join('') || '<tr><td colspan="6" class="cc-empty">데이터 없음</td></tr>';
    return '<div class="cc-card cc-card-full"><div class="cc-card-h">M1 생육 모델별 성능 (R² 내림차순)</div>' +
      '<div class="cc-tablewrap" style="max-height:340px;overflow-y:auto;"><table class="cc-table"><thead><tr><th>작물</th><th>타깃</th><th>R²</th><th>학습샘플</th><th>등급</th><th>게이트</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div></div>';
  }

  function render(d) {
    var root = document.getElementById('modelView');
    if (!root) return;
    if (!d) { root.innerHTML = '<div class="cc-loading">모델 성능 데이터를 불러오지 못했습니다.</div>'; return; }
    root.innerHTML =
      '<div class="cc-head"><div><h1>AI 학습·모델</h1>' +
      '<p class="cc-sub">M1 생육·M2 수확·M3 매출·M5 병해 모델 성능 / 배포 게이트 · 드리프트 모니터링' +
      (d.generated_at ? ' · 생성 ' + esc(String(d.generated_at).slice(0, 16).replace('T', ' ')) : '') + '</p></div></div>' +
      kpiStrip(d) +
      advisoryCard() +
      pipeline() +
      '<div class="cc-grid2">' + m2GateTable(d.m2_yield) + m2DriftCard(d.m2_yield) + '</div>' +
      matrix(d) +
      m1Table(d.m1_growth);
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    var root = document.getElementById('modelView');
    if (root) root.innerHTML = '<div class="cc-loading">모델 성능 집계 중…</div>';
    var results = await Promise.all([fetchPerf(), fetchAdvisories()]);
    state.loading = false;
    state.data = results[0];
    state.adv = results[1];
    render(results[0]);
  }

  // 재학습 승인·실행 — 제안(권고)을 관리자가 승인하면 파이프라인 트리거(제안→실행 사슬).
  //   PUBLIC_DEMO 에서는 쓰기 게이트로 403 → 정직하게 "관리자 계정 필요" 안내.
  async function approveRetrain(crop, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '요청 중…'; }
    try {
      var r = await fetch(apiBase() + '/api/admin/pipeline/trigger', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() },
        body: JSON.stringify(crop ? { crop: crop } : {})
      });
      if (!btn) return;
      if (r.status === 403) {
        btn.textContent = '🔒 데모 — 관리자 계정 필요'; btn.style.opacity = '.7';
        btn.style.borderColor = 'var(--muted)'; btn.style.color = 'var(--muted)';
      } else if (r.ok) {
        btn.textContent = '✓ 재학습 시작'; btn.style.background = 'var(--green)';
        btn.style.color = '#fff'; btn.style.borderColor = 'var(--green)';
      } else { btn.disabled = false; btn.textContent = '재시도'; }
    } catch (e) { if (btn) { btn.disabled = false; btn.textContent = '재시도'; } }
  }

  window.ConsoleModel = {
    ensure: function () { if (state.data) return; load(); },
    approve: approveRetrain
  };
})();
