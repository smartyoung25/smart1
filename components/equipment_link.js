/* ─────────────────────────────────────────────────────────────
 * EquipmentLink — 등록된 시설 기자재(C16)를 화면에 연결
 *  · 매핑된 표준변수 → 화면에 "연동 장비" 배지 (실측 backing 가시화)
 *  · device_alert 와 연계 (online/battery 텔레메트리 주입 시 자동 표출)
 *
 * const inv = await EquipmentLink.load(farmId, token);
 *   → { items:[...], mappedVars:Set, deviceCount }
 * EquipmentLink.renderBadge(el, inv, relevantVars[])  // 화면 관련 변수만 표시
 * ───────────────────────────────────────────────────────────── */
(function (global) {
  function _css(){
    if(document.getElementById('eqlink-css')) return;
    const s=document.createElement('style'); s.id='eqlink-css';
    s.textContent=`
      .eql-badge{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
        background:var(--panel);border:1.5px solid var(--border);border-left:4px solid var(--blue,#2563eb);
        border-radius:12px;padding:9px 12px;margin-bottom:12px;font-size:12px;}
      .eql-badge .eql-h{font-weight:800;}
      .eql-var{font-size:10px;font-weight:800;padding:2px 7px;border-radius:7px;}
      .eql-var.on{background:var(--green-soft);color:var(--green-dark);}
      .eql-var.off{background:var(--gray-soft);color:var(--muted);}
      .eql-link{margin-left:auto;font-size:11px;font-weight:800;color:var(--blue,#2563eb);text-decoration:none;}`;
    document.head.appendChild(s);
  }
  const VAR_KO={temp_internal:'내부온도',humidity_int:'습도',co2_ppm:'CO₂',solar_rad:'일사',
    soil_temp:'지온',ec_dsm:'EC',ph:'pH',drain_pct:'배액률',supply_ml:'급액량',
    water_content_pct:'함수율',temp_external:'외기온',wind_speed_ext:'풍속',rainfall_detect:'강우'};

  async function load(farmId, token){
    try{
      const api=(global.KaasaData&&KaasaData.getApiBase)?KaasaData.getApiBase():location.origin;
      const d=await fetch(`${api}/api/farms/${farmId}/equipment`,{headers:{Authorization:'Bearer '+(token||'')}}).then(r=>r.json());
      const items=d.items||[];
      const mapped=new Set(items.flatMap(i=>(i.datapoints||[]).map(p=>p.canonical_name).filter(Boolean)));
      return { items, mappedVars:mapped, deviceCount:items.length };
    }catch(e){ return { items:[], mappedVars:new Set(), deviceCount:0 }; }
  }

  function renderBadge(el, inv, relevantVars){
    if(!el) return; _css();
    inv=inv||{mappedVars:new Set(),deviceCount:0};
    if(!inv.deviceCount){
      el.innerHTML=`<div class="eql-badge"><span class="eql-h">🔌 연동 장비 없음</span>
        <span style="color:var(--muted);">표시값은 데모/수동 기준입니다.</span>
        <a class="eql-link" href="c16_equipment.html">기자재 등록 →</a></div>`;
      return;
    }
    const vars=(relevantVars||[]).map(v=>{
      const on=inv.mappedVars.has(v);
      return `<span class="eql-var ${on?'on':'off'}">${on?'🟢':'○'} ${VAR_KO[v]||v}</span>`;
    }).join('');
    el.innerHTML=`<div class="eql-badge"><span class="eql-h">🔌 연동 장비 ${inv.deviceCount}대</span>
      ${vars}<a class="eql-link" href="c16_equipment.html">관리 →</a></div>`;
  }

  // 등록 장비를 device_alert 에 연계 (online/battery 필드가 있으면 경보)
  function feedDeviceAlert(inv){
    if(!global.DeviceAlert || !inv) return;
    DeviceAlert.setDevices((inv.items||[]).map(i=>({
      name:i.device_id, online:i.online, battery:i.battery })));
  }

  global.EquipmentLink = { load, renderBadge, feedDeviceAlert };
})(window);
