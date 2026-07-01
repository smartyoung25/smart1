/* ============================================================
   stage_flow.js — 가치사슬 작업단계 스테퍼 + 다음단계 제안
   생산(온실/노지 택1) → 경영 → 유통. 각 도메인을 작업단계로 세그먼트화.
   완료/현재/다음 시각화 + "다음 단계 →" 제안(제안·넘김, 자동 실행 안 함).
   ============================================================ */
(function () {
  'use strict';

  // 도메인별 작업단계(검증된 실재 화면). key는 완료추적·전역 유일.
  var STAGES = {
    greenhouse: [
      { key: 'gh_env',    label: '환경',   icon: '🌡️', screen: 'g2_env.html' },
      { key: 'gh_irr',    label: '관수',   icon: '💧', screen: 'g3_period.html' },
      { key: 'gh_growth', label: '생육',   icon: '🌿', screen: 'g4_growth.html' },
      { key: 'gh_harv',   label: '수확',   icon: '🚜', screen: 'g6_harvest.html' }
    ],
    field: [
      { key: 'fd_wx',     label: '기상',      icon: '🌦️', screen: 'f3_weather.html' },
      { key: 'fd_soil',   label: '토양·관개', icon: '💧', screen: 'f4_soil.html' },
      { key: 'fd_ndvi',   label: '작황',      icon: '🛰️', screen: 'f5_remote.html' },
      { key: 'fd_harv',   label: '수확',      icon: '🚜', screen: 'f7_harvest.html' }
    ],
    management: [
      { key: 'mg_diag',   label: '진단',     icon: '🩺', screen: 'c17_diagnosis.html' },
      { key: 'mg_erp',    label: '수익분석', icon: '💰', screen: 'c5_erp.html' },
      { key: 'mg_bench',  label: '벤치마킹', icon: '📈', screen: 'c9_benchmark.html' },
      { key: 'mg_pdca',   label: 'PDCA',     icon: '🔄', screen: 'c25_pdca.html' }
    ],
    market: [
      { key: 'mk_join',   label: '가입', icon: '📝', screen: 'c11_pool_join.html' },
      { key: 'mk_ops',    label: '운영', icon: '🤝', screen: 'c12_joint.html' }
    ]
  };

  function _doneSet() {
    try { return new Set(JSON.parse(localStorage.getItem('sf_stage_done') || '[]')); }
    catch (e) { return new Set(); }
  }
  function _saveDone(set) {
    try { localStorage.setItem('sf_stage_done', JSON.stringify(Array.from(set))); } catch (e) {}
  }

  // 강신호(방문 여부와 무관하게 실제 완료로 간주)
  function _strongDone(key) {
    try {
      if (key === 'mk_join') {           // 공동출하 가입: C11/C12 통일 키
        var j = JSON.parse(localStorage.getItem('sf_pool_joined') || '[]');
        return Array.isArray(j) && j.length > 0;
      }
    } catch (e) {}
    return false;
  }

  function isDone(key) { return _strongDone(key) || _doneSet().has(key); }

  function markDone(key) {
    if (!key) return;
    var s = _doneSet(); s.add(key); _saveDone(s);
  }

  // 첫 미완료 단계(전부 완료면 마지막) — 제안 대상
  function next(domain) {
    var list = STAGES[domain] || [];
    for (var i = 0; i < list.length; i++) { if (!isDone(list[i].key)) return list[i]; }
    return list.length ? list[list.length - 1] : null;
  }

  function go(key) {
    var st = _find(key);
    if (!st) return;
    markDone(key);
    location.href = st.screen;
  }
  function _find(key) {
    for (var d in STAGES) { for (var i = 0; i < STAGES[d].length; i++) { if (STAGES[d][i].key === key) return STAGES[d][i]; } }
    return null;
  }

  var _esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };

  // 도메인 스테퍼 + 다음단계 제안 HTML
  function render(domain) {
    var list = STAGES[domain]; if (!list) return '';
    var nx = next(domain);
    var chips = list.map(function (s) {
      var done = isDone(s.key);
      var cur  = nx && s.key === nx.key && !done;
      var cls  = done ? 'done' : (cur ? 'cur' : 'future');
      var mark = done ? '✓' : s.icon;
      return '<button class="stage-chip ' + cls + '" onclick="StageFlow.go(\'' + s.key + '\')" title="' + _esc(s.label) + '">' +
        '<span class="sc-ico">' + mark + '</span><span class="sc-lb">' + _esc(s.label) + '</span></button>';
    }).join('<span class="stage-sep"></span>');
    var allDone = list.every(function (s) { return isDone(s.key); });
    var nextHtml = (nx && !allDone)
      ? '<button class="stage-next" onclick="StageFlow.go(\'' + nx.key + '\')">다음 단계: ' + _esc(nx.icon + ' ' + nx.label) + ' →</button>'
      : '<div class="stage-next done">✅ 이 단계 흐름 완료 — 다음 가치사슬 단계를 선택하세요</div>';
    return '<div class="stage-row">' + chips + '</div>' + nextHtml;
  }

  // 컨테이너 채우기(도메인별). domId 없으면 [data-dom]로 자동 매칭.
  function mount(domain, el) {
    var target = el || document.querySelector('.stage-flow[data-dom="' + domain + '"]');
    if (target) target.innerHTML = render(domain);
  }

  window.StageFlow = { STAGES: STAGES, isDone: isDone, markDone: markDone, next: next, go: go, render: render, mount: mount };
})();
