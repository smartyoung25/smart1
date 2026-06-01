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

  // 최근 기록 타임라인 렌더 (입력→축적 가시화)
  const KIND_META = {
    irrigation:    { ico:'💧', label:'관개' },
    disease_check: { ico:'🐛', label:'방제·점검' },
    harvest:       { ico:'🚜', label:'수확' },
    env_setpoint:  { ico:'🌡️', label:'환경설정' },
    education:     { ico:'🎓', label:'교육' },
    todo:          { ico:'✅', label:'할일' },
    decision_apply:{ ico:'🤖', label:'AI결정' },
    consult:       { ico:'🩺', label:'전문가' },
    joint_ship:    { ico:'🤝', label:'공동출하' },
    consent:       { ico:'📑', label:'데이터동의' },
  };
  function _ago(ts){
    try{ const d=new Date(ts), now=new Date(), m=Math.floor((now-d)/60000);
      if(m<1) return '방금'; if(m<60) return m+'분 전'; const h=Math.floor(m/60);
      if(h<24) return h+'시간 전'; return Math.floor(h/24)+'일 전';
    }catch(e){ return ''; }
  }
  function _injectRecentCss(){
    if(document.getElementById('rec-list-css')) return;
    const s=document.createElement('style'); s.id='rec-list-css';
    s.textContent=`
      .rl-item{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--border);}
      .rl-item:last-child{border-bottom:none;}
      .rl-ico{font-size:17px;flex:0 0 auto;}
      .rl-body{flex:1;min-width:0;}
      .rl-title{font-size:13px;font-weight:700;}
      .rl-detail{font-size:11px;color:var(--muted);margin-top:1px;line-height:1.4;}
      .rl-time{font-size:10px;color:var(--muted);flex:0 0 auto;white-space:nowrap;}
      .rl-empty{text-align:center;padding:14px;color:var(--muted);font-size:12px;}`;
    document.head.appendChild(s);
  }
  async function renderRecent(el, farmId, token, opts){
    if(!el) return; opts=opts||{}; _injectRecentCss();
    const kinds = opts.kinds ? new Set(opts.kinds) : null;
    const limit = opts.limit || 5;
    try{
      const api=(global.KaasaData&&KaasaData.getApiBase)?KaasaData.getApiBase():location.origin;
      const r=await fetch(`${api}/api/farms/${farmId}/activity/summary`,{headers:{'Authorization':'Bearer '+(token||'')}});
      const d=await r.json();
      let items=(d.recent||[]);
      if(kinds) items=items.filter(i=>kinds.has(i.kind));
      items=items.slice(0,limit);
      if(!items.length){ el.innerHTML=`<div class="rl-empty">아직 기록이 없습니다. 위 버튼으로 첫 기록을 남겨보세요.</div>`; return; }
      el.innerHTML=items.map(i=>{
        const m=KIND_META[i.kind]||{ico:'•',label:i.kind};
        return `<div class="rl-item"><span class="rl-ico">${m.ico}</span>
          <div class="rl-body"><div class="rl-title">${i.item||m.label}</div>
            ${i.detail?`<div class="rl-detail">${i.detail}</div>`:''}</div>
          <span class="rl-time">${_ago(i.ts)}</span></div>`;
      }).join('');
    }catch(e){ el.innerHTML=`<div class="rl-empty">기록을 불러오지 못했습니다.</div>`; }
  }

  global.RecordSheet = { open, logActivity, renderRecent };
})(window);
