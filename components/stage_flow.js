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

  // 가치사슬 도메인 순서: 생산(택1) → 경영 → 유통. 생산 도메인은 farm_type 로 결정.
  var DOMAIN_LABEL = { greenhouse: '온실 생산', field: '노지 생산', management: '경영', market: '유통' };
  function _prodDomain() {
    try {
      var p = JSON.parse(localStorage.getItem('sf_profile') || '{}');
      return p.farm_type === 'field' ? 'field' : 'greenhouse';
    } catch (e) { return 'greenhouse'; }
  }
  function _order() { return [_prodDomain(), 'management', 'market']; }
  function nextDomain(domain) {
    var o = _order(), i = o.indexOf(domain);
    return (i >= 0 && i < o.length - 1) ? o[i + 1] : null;
  }

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

  // 칩/허브 제안 클릭 = 해당 단계로 '이동만'(완료 표시 안 함 — 방문≠완료).
  function go(key) {
    var st = _find(key);
    if (st) location.href = st.screen;
  }
  // '다음 단계' 명시 클릭 = 현재 단계를 완료 처리하고 다음 단계로 이동(도메인 내 → 다음 도메인).
  function advance(currentKey) {
    if (!currentKey) return;
    markDone(currentKey);
    var domain = _domainOf(currentKey);
    var list = STAGES[domain] || [];
    var i = _indexOf(domain, currentKey);
    var target = (i >= 0 && i < list.length - 1) ? list[i + 1] : null;
    if (!target) { var nd = nextDomain(domain); target = (nd && STAGES[nd]) ? STAGES[nd][0] : null; }
    if (target) location.href = target.screen;
  }
  function _find(key) {
    for (var d in STAGES) { for (var i = 0; i < STAGES[d].length; i++) { if (STAGES[d][i].key === key) return STAGES[d][i]; } }
    return null;
  }
  function _indexOf(domain, key) { var l = STAGES[domain] || []; for (var i = 0; i < l.length; i++) { if (l[i].key === key) return i; } return -1; }
  function _domainOf(key) { for (var d in STAGES) { if (_indexOf(d, key) >= 0) return d; } return null; }

  var _esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };

  // 도메인 스테퍼 + 다음단계 제안 HTML.
  //   currentKey 있으면(단계 화면 주입) 그 단계를 '현재 위치'로 강조 + '다음 단계'는 완료 처리 이동.
  //   없으면(허브) 첫 미완료를 현재로 보고 '다음'은 이동만(완료는 각 단계 화면에서).
  function render(domain, currentKey) {
    var list = STAGES[domain]; if (!list) return '';
    var nx = next(domain);
    var curKey = currentKey || (nx ? nx.key : null);
    var chips = list.map(function (s) {
      var done = isDone(s.key);
      var cur  = !done && s.key === curKey;
      var cls  = done ? 'done' : (cur ? 'cur' : 'future');
      var mark = done ? '✓' : s.icon;
      return '<button class="stage-chip ' + cls + '" onclick="StageFlow.go(\'' + s.key + '\')" title="' + _esc(s.label) + '">' +
        '<span class="sc-ico">' + mark + '</span><span class="sc-lb">' + _esc(s.label) + '</span></button>';
    }).join('<span class="stage-sep"></span>');
    // 다음 대상: 주입=현재 다음 단계 / 허브=첫 미완료(전부 완료면 다음 도메인)
    var nextTarget = null, crossLabel = '';
    if (currentKey) {
      var ci = _indexOf(domain, currentKey);
      if (ci >= 0 && ci < list.length - 1) nextTarget = list[ci + 1];
      else { var ndc = nextDomain(domain); if (ndc && STAGES[ndc]) { nextTarget = STAGES[ndc][0]; crossLabel = DOMAIN_LABEL[ndc] + ' · '; } }
    } else {
      var allDone = list.every(function (s) { return isDone(s.key); });
      if (nx && !allDone) nextTarget = nx;
      else { var ndh = nextDomain(domain); if (ndh && STAGES[ndh]) { nextTarget = STAGES[ndh][0]; crossLabel = DOMAIN_LABEL[ndh] + ' · '; } }
    }
    var nextHtml;
    if (nextTarget) {
      var lbl = crossLabel + nextTarget.icon + ' ' + nextTarget.label;
      var oc = currentKey ? ("StageFlow.advance('" + currentKey + "')") : ("StageFlow.go('" + nextTarget.key + "')");
      nextHtml = '<button class="stage-next" onclick="' + oc + '">' + (currentKey ? '다음 단계: ' : '다음: ') + _esc(lbl) + ' →</button>';
    } else {
      nextHtml = '<div class="stage-next done">✅ 가치사슬 전 단계 완료</div>';
    }
    return '<div class="stage-row">' + chips + '</div>' + nextHtml;
  }

  // 컨테이너 채우기(도메인별). currentKey 있으면 그 단계를 '현재 위치'로 강조.
  function mount(domain, el, currentKey) {
    var target = el || document.querySelector('.stage-flow[data-dom="' + domain + '"]');
    if (target) target.innerHTML = render(domain, currentKey);
  }

  window.StageFlow = { STAGES: STAGES, isDone: isDone, markDone: markDone, next: next, nextDomain: nextDomain, go: go, advance: advance, render: render, mount: mount };
})();
