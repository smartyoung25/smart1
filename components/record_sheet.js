/* ─────────────────────────────────────────────────────────────
 * RecordSheet — 운영 기록 입력 Bottom Sheet (재사용)
 *  벤치마킹: John Deere "계획→실행→기록" 폐루프 — 농가가 실제 이행을 기록
 *
 * RecordSheet.open({
 *   title:'관개 실행 기록',
 *   fields:[ {id,label,type:'number|text|select|date', options?, unit?, placeholder?, value?} ],
 *   submitLabel:'기록 저장',
 *   onSubmit: async (values) => {...}   // values = {id: value}
 * })
 * RecordSheet.logActivity(farmId, token, {kind, item, value, detail}) → POST /activity
 * ───────────────────────────────────────────────────────────── */
(function (global) {
  function _css() {
    if (document.getElementById('rec-sheet-css')) return;
    const s = document.createElement('style'); s.id = 'rec-sheet-css';
    s.textContent = `
      .rs-mask{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:flex-end;z-index:200;}
      .rs-sheet{background:var(--panel);width:100%;max-width:480px;margin:0 auto;border-radius:18px 18px 0 0;
        padding:18px 18px calc(18px + env(safe-area-inset-bottom));box-shadow:0 -8px 24px rgba(0,0,0,.25);
        max-height:88vh;overflow-y:auto;}
      .rs-title{font-size:17px;font-weight:800;margin:0 0 12px;}
      .rs-label{font-size:12.5px;font-weight:700;margin:12px 0 5px;display:block;}
      .rs-input,.rs-select{width:100%;min-height:46px;padding:11px 13px;border:1.5px solid var(--border);
        border-radius:10px;font-size:15px;outline:none;background:var(--panel);color:var(--text);}
      .rs-input:focus,.rs-select:focus{border-color:var(--green);}
      .rs-unit{font-size:11px;color:var(--muted);margin-left:4px;}
      .rs-msg{font-size:12.5px;font-weight:700;text-align:center;margin-top:10px;min-height:16px;}
      .rs-btns{display:flex;gap:10px;margin-top:16px;}
      .rs-btn{flex:1;padding:14px;border-radius:12px;font-size:14px;font-weight:800;border:none;cursor:pointer;min-height:48px;}
      .rs-ok{background:var(--green);color:#fff;}.rs-ok:disabled{opacity:.6;}
      .rs-cancel{background:var(--gray-soft);color:var(--muted);flex:0 0 96px;}
    `;
    document.head.appendChild(s);
  }

  function open(cfg) {
    _css(); cfg = cfg || {};
    const fields = cfg.fields || [];
    const mask = document.createElement('div'); mask.className = 'rs-mask';
    const body = fields.map(f => {
      const lab = `<label class="rs-label">${f.label}${f.unit?`<span class="rs-unit">(${f.unit})</span>`:''}</label>`;
      if (f.type === 'select') {
        const opts = (f.options||[]).map(o => `<option value="${o}"${f.value===o?' selected':''}>${o}</option>`).join('');
        return lab + `<select class="rs-select" data-id="${f.id}">${opts}</select>`;
      }
      const t = f.type === 'date' ? 'date' : f.type === 'number' ? 'number' : 'text';
      const im = f.type === 'number' ? ' inputmode="decimal"' : '';
      return lab + `<input class="rs-input" data-id="${f.id}" type="${t}"${im} placeholder="${f.placeholder||''}" value="${f.value!=null?f.value:''}"/>`;
    }).join('');
    mask.innerHTML = `<div class="rs-sheet" role="dialog" aria-modal="true">
      <div class="rs-title">${cfg.title||'기록 입력'}</div>
      ${body}
      <div class="rs-msg" id="rsMsg"></div>
      <div class="rs-btns">
        <button class="rs-btn rs-cancel" data-act="cancel">취소</button>
        <button class="rs-btn rs-ok" data-act="ok">${cfg.submitLabel||'기록 저장'}</button>
      </div>
    </div>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', e => { if (e.target === mask) close(); });
    mask.querySelector('[data-act="cancel"]').addEventListener('click', close);
    mask.querySelector('[data-act="ok"]').addEventListener('click', async () => {
      const vals = {};
      mask.querySelectorAll('[data-id]').forEach(el => { vals[el.dataset.id] = el.value.trim(); });
      // 필수 검증 (required:true 인 필드)
      const miss = fields.find(f => f.required && !vals[f.id]);
      const msg = mask.querySelector('#rsMsg');
      if (miss) { msg.style.color = 'var(--red)'; msg.textContent = `${miss.label}을(를) 입력하세요`; return; }
      const ok = mask.querySelector('[data-act="ok"]');
      ok.disabled = true; ok.textContent = '저장 중…';
      try {
        if (typeof cfg.onSubmit === 'function') await cfg.onSubmit(vals);
        msg.style.color = 'var(--green)'; msg.textContent = '✓ 기록 저장됨';
        setTimeout(close, 800);
      } catch (e) {
        msg.style.color = 'var(--orange)'; msg.textContent = '⚠ 저장 실패: ' + (e.message || '오류');
        ok.disabled = false; ok.textContent = cfg.submitLabel || '기록 저장';
      }
    });
  }

  async function logActivity(farmId, token, rec) {
    const api = (global.KaasaData && KaasaData.getApiBase) ? KaasaData.getApiBase() : location.origin;
    const r = await fetch(`${api}/api/farms/${farmId}/activity`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token||'') },
      body: JSON.stringify({ kind: rec.kind, item: rec.item || '', value: rec.value ?? null, detail: rec.detail || '' })
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  global.RecordSheet = { open, logActivity };
})(window);
