/* ──────────────────────────────────────────────────────────────
 * KaasaTier — 화면 내부 위젯 등급(티어) 게이팅 (Level ②)
 *
 * 사용법:
 *   await KaasaTier.init(farmId, token);          // 1회 호출 (등급/기능 로드)
 *   KaasaTier.guard(el, 'env_vpd_stage');         // 미달 시 위젯 위에 잠금 오버레이
 *   if (KaasaTier.allowed('growth_yield_interval')) { ... }  // 조건부 렌더
 *
 * 백엔드: GET /api/farms/{id}/billing/features (allowed:true/false 반환)
 * ────────────────────────────────────────────────────────────── */
(function (global) {
  const RANK = { basic: 1, smart: 2, pro: 3, enterprise: 4 };
  const NAME = { basic: '기본', smart: '스마트', pro: '프로', enterprise: '엔터프라이즈' };
  const COLOR = { basic: '#8892a4', smart: '#4f8ef7', pro: '#a78bfa', enterprise: '#f9a825' };

  let _tier = 'basic';
  let _feat = {};   // { feature_code: { allowed, min_tier, label_ko } }
  let _ready = false;

  function _injectCss() {
    if (document.getElementById('kaasa-tier-css')) return;
    const s = document.createElement('style');
    s.id = 'kaasa-tier-css';
    s.textContent = `
      .kt-lock-wrap { position: relative; }
      .kt-lock-ovl {
        position: absolute; inset: 0; border-radius: inherit;
        background: rgba(20,28,24,.72); backdrop-filter: blur(2px);
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 6px; text-align: center; padding: 12px; cursor: pointer; z-index: 5;
      }
      .kt-lock-ovl .kt-ico { font-size: 26px; }
      .kt-lock-ovl .kt-msg { font-size: 12px; font-weight: 800; color: #fff; line-height: 1.4; }
      .kt-lock-ovl .kt-cta { font-size: 11px; font-weight: 800; color: #fff;
        padding: 4px 10px; border-radius: 999px; }
    `;
    document.head.appendChild(s);
  }

  async function init(farmId, token) {
    _injectCss();
    try {
      const r = await fetch(`${location.origin}/api/farms/${farmId}/billing/features`, {
        headers: token ? { 'Authorization': 'Bearer ' + token } : {}
      });
      if (r.ok) {
        const d = await r.json();
        _tier = d.tier || 'basic';
        (d.features || []).forEach(f => { _feat[f.feature_code] = f; });
        _ready = true;
      }
    } catch (e) { /* 실패 시 모두 허용(폴백) */ }
    return _ready;
  }

  function tier() { return _tier; }
  function allowed(code) {
    if (!_ready) return true;            // 로드 실패 → 막지 않음(안전)
    const f = _feat[code];
    if (!f) return true;                 // 모르는 코드 → 허용
    return f.allowed === true;
  }
  function minTier(code) { return (_feat[code] || {}).min_tier || 'basic'; }

  /** el 위젯을 code 기능 등급으로 게이팅. 미달이면 잠금 오버레이 + 클릭→onUpgrade */
  function guard(el, code, opts) {
    opts = opts || {};
    if (!el || allowed(code)) return false;
    const mt = minTier(code);
    const f = _feat[code] || {};
    el.classList.add('kt-lock-wrap');
    const ovl = document.createElement('div');
    ovl.className = 'kt-lock-ovl';
    ovl.innerHTML =
      `<div class="kt-ico">🔒</div>
       <div class="kt-msg">${f.label_ko || '고급 기능'}<br>${NAME[mt] || mt} 등급부터 이용</div>
       <div class="kt-cta" style="background:${COLOR[mt] || '#888'}">업그레이드 →</div>`;
    ovl.addEventListener('click', () => {
      if (typeof opts.onUpgrade === 'function') opts.onUpgrade(mt, code);
      else location.href = '/smartos';     // 기본: 메뉴(등급 안내)로 이동
    });
    el.appendChild(ovl);
    return true;
  }

  global.KaasaTier = { init, guard, allowed, minTier, tier, NAME, COLOR };
})(window);
