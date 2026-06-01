/* ─────────────────────────────────────────────────────────────
 * DeviceAlert — 기기/연결 상태 알림 (데이터 이상 알림과 분리)
 *  벤치마킹: 30MHz/Aranet — "데이터 알림 vs 기기(연결·배터리) 알림" 2계층
 *
 * DeviceAlert.mount(containerId)         // 1회: 배너 컨테이너 지정
 * DeviceAlert.onStatus(state)            // _onWsStatus에서 호출 ('connected'|'reconnecting'|기타)
 * DeviceAlert.setDevices([{name,online,battery}])  // (선택) 기기 메타 주입
 * ───────────────────────────────────────────────────────────── */
(function (global) {
  let _elId = null, _state = 'connected', _devices = [];

  function _injectCss() {
    if (document.getElementById('dev-alert-css')) return;
    const s = document.createElement('style'); s.id = 'dev-alert-css';
    s.textContent = `
      .dev-alert { display:flex; align-items:center; gap:9px; padding:10px 12px;
        border-radius:12px; font-size:12.5px; font-weight:700; margin-bottom:10px;
        border:1.5px solid; }
      .dev-alert .dev-ico { font-size:16px; }
      .dev-alert .dev-sub { font-weight:500; color:var(--muted); font-size:11px; }
      .dev-alert.off  { background:var(--red-soft,#ffeaea);   color:var(--red,#dc2626);   border-color:var(--red,#dc2626); }
      .dev-alert.recon{ background:var(--orange-soft,#fff4e5); color:var(--orange,#ea8a00); border-color:var(--orange,#ea8a00); }
      .dev-alert.batt { background:var(--orange-soft,#fff4e5); color:var(--orange,#ea8a00); border-color:var(--orange,#ea8a00); }
    `;
    document.head.appendChild(s);
  }

  function mount(elId) { _elId = elId; _injectCss(); _render(); }
  function onStatus(state) { _state = state || 'connected'; _render(); }
  function setDevices(list) { _devices = list || []; _render(); }

  function _render() {
    if (!_elId) return;
    const el = document.getElementById(_elId);
    if (!el) return;
    const banners = [];
    // 연결 상태 (데이터값과 무관한 기기 링크 알림)
    if (_state === 'reconnecting') banners.push(
      `<div class="dev-alert recon"><span class="dev-ico">📡</span>
         <span>센서 재연결 중… <span class="dev-sub">표시값이 최신이 아닐 수 있습니다</span></span></div>`);
    else if (_state !== 'connected') banners.push(
      `<div class="dev-alert off"><span class="dev-ico">🔌</span>
         <span>실시간 연결 끊김 <span class="dev-sub">마지막 수신값 표시 중 · 네트워크/게이트웨이 점검</span></span></div>`);
    // 기기 오프라인 / 배터리 (메타 주입 시)
    const off = _devices.filter(d => d && d.online === false);
    const low = _devices.filter(d => d && d.battery != null && d.battery < 15);
    if (off.length) banners.push(
      `<div class="dev-alert off"><span class="dev-ico">⚠️</span>
         <span>센서 ${off.length}개 오프라인 <span class="dev-sub">${off.map(d=>d.name).join(', ')}</span></span></div>`);
    if (low.length) banners.push(
      `<div class="dev-alert batt"><span class="dev-ico">🔋</span>
         <span>배터리 부족 ${low.length}건 <span class="dev-sub">${low.map(d=>`${d.name} ${d.battery}%`).join(', ')}</span></span></div>`);
    el.innerHTML = banners.join('');
  }

  global.DeviceAlert = { mount, onStatus, setDevices };
})(window);
