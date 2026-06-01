/* ─────────────────────────────────────────────────────────────
 * DecisionDeck — AI 의사결정 카드 렌더러 (벤치마킹 패턴 구현)
 *
 * DecisionDeck.render(el, items, opts)
 *   item = {
 *     id, severity:'danger|warn|info|ok', sevLabel, title, why, action,
 *     confidence:0~100, source:'live|model|est|standard', updatedMin:Number,
 *     evidence:'근거 텍스트', applyLabel, target:'g3_period.html'
 *   }
 *   opts.onApply(item) → 원탭 실행 콜백 (예: /activity 적재)
 * ───────────────────────────────────────────────────────────── */
(function (global) {
  const SEV = {
    danger: { ico: '🚨', label: '긴급' },
    warn:   { ico: '⚠️', label: '주의' },
    info:   { ico: '💡', label: '권장' },
    ok:     { ico: '✅', label: '정상' },
  };
  const SRC = {
    live:     { cls: 'trust-live',  txt: '🟢 실측' },
    model:    { cls: 'trust-model', txt: '🔵 모델' },
    est:      { cls: 'trust-est',   txt: '🟠 추정' },
    standard: { cls: 'trust-model', txt: '📘 농진청표준' },
    mock:     { cls: 'trust-mock',  txt: '⚪ 예시' },
  };

  function _fresh(min) {
    if (min == null) return '';
    if (min < 1) return '방금 전';
    if (min < 60) return `${Math.round(min)}분 전`;
    const h = Math.floor(min / 60);
    return `${h}시간 전`;
  }

  function render(el, items, opts) {
    opts = opts || {};
    if (!el) return;
    if (!items || !items.length) {
      el.innerHTML = `<div style="text-align:center;padding:18px;color:var(--muted);font-size:13px;">
        ✅ 지금 조치가 필요한 항목이 없습니다.</div>`;
      return;
    }
    el.classList.add('dd-deck');
    el.innerHTML = items.map((it, i) => {
      const sev = SEV[it.severity] || SEV.info;
      const src = SRC[it.source] || SRC.model;
      const conf = Math.max(0, Math.min(100, it.confidence ?? 0));
      const confCls = conf >= 70 ? '' : conf >= 45 ? 'mid' : 'low';
      const fresh = _fresh(it.updatedMin);
      return `<div class="dd-card sev-${it.severity || 'info'}" data-i="${i}">
        <div class="dd-head">
          <div class="dd-ico">${sev.ico}</div>
          <div class="dd-hbody">
            <span class="dd-sev">${it.sevLabel || sev.label}</span>
            <div class="dd-title">${it.title || ''}</div>
            ${it.why ? `<div class="dd-why">${it.why}</div>` : ''}
          </div>
        </div>
        ${it.action ? `<div class="dd-action"><span class="dd-arrow">→</span><span>${it.action}</span></div>` : ''}
        <div class="dd-meta">
          <span class="dd-conf">신뢰도 ${conf}%
            <span class="dd-conf-bar"><span class="dd-conf-fill ${confCls}" style="width:${conf}%"></span></span>
          </span>
          <span class="dd-src trust-badge ${src.cls}">${src.txt}</span>
          ${fresh ? `<span class="dd-fresh">⏱ ${fresh}</span>` : ''}
        </div>
        <div class="dd-btns">
          <button class="dd-btn dd-btn-apply" data-act="apply" data-i="${i}">${it.applyLabel || '적용 기록'}</button>
          ${it.evidence ? `<button class="dd-btn dd-btn-why" data-act="why" data-i="${i}">근거</button>` : ''}
        </div>
        ${it.evidence ? `<div class="dd-evidence" data-ev="${i}">${it.evidence}</div>` : ''}
      </div>`;
    }).join('');

    el.querySelectorAll('[data-act="why"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const ev = el.querySelector(`[data-ev="${btn.dataset.i}"]`);
        if (ev) ev.classList.toggle('open');
      });
    });
    el.querySelectorAll('[data-act="apply"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const it = items[+btn.dataset.i];
        btn.disabled = true; btn.textContent = '기록 중…';
        try {
          if (typeof opts.onApply === 'function') await opts.onApply(it);
          btn.textContent = '✓ 기록됨';
          if (it.target) setTimeout(() => { location.href = it.target; }, 700);
        } catch (e) {
          btn.disabled = false; btn.textContent = '다시 시도';
        }
      });
    });
  }

  global.DecisionDeck = { render };
})(window);
