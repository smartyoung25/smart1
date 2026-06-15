// ── 관수: Priva ET₀ 스케줄 ───────────────────────────────────────────────────
async function loadPrivaSchedule() {
  const farmId = $('priva-farm-sel')?.value || _defaultFarm();
  const stage  = $('priva-stage-sel')?.value || 'mid';
  const size   = parseFloat($('priva-size')?.value || '100');
  const el = $('priva-sched-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(
      `/api/farms/${farmId}/irrigation/schedule/priva?growth_stage=${stage}&plant_size_pct=${size}`
    );
    const fmt1 = n => n != null ? Number(n).toFixed(1) : '—';
    const fmt0 = n => n != null ? Math.round(n) : '—';
    const phaseColors = ['#4f8ef7','#3ecf8e','#f5c842'];
    const phaseList = d.phases || [];
    const phases = phaseList.length ? phaseList.map((ph, i) => `
      <div style="background:rgba(${i===0?'79,142,247':i===1?'62,207,142':'245,200,66'},.1);border-radius:8px;padding:10px;border:1px solid rgba(${i===0?'79,142,247':i===1?'62,207,142':'245,200,66'},.3)">
        <div style="font-size:11px;font-weight:700;color:${phaseColors[i]||'var(--accent)'};margin-bottom:6px">${_esc(ph?.name_ko || 'Phase'+(i+1))} <span style="color:var(--muted);font-weight:400">${_esc(ph?.start_hhmm??'')}~${_esc(ph?.end_hhmm??'')}</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px">
          <div style="color:var(--muted)">횟수</div><div style="font-weight:700">${ph?.n_max ?? '—'}회</div>
          <div style="color:var(--muted)">회당공급</div><div style="font-weight:700">${fmt0(ph?.supply_ml)} ml</div>
          <div style="color:var(--muted)">배액목표</div><div style="font-weight:700">${fmt1(ph?.drain_target_pct)}%</div>
        </div>
      </div>`).join('')
    : '<div style="color:var(--muted);font-size:12px;padding:8px">페이즈 정보 없음</div>';
    el.innerHTML = `
      <div class="form-4col" style="gap:8px;margin-bottom:12px">
        <div class="irr-kpi"><div class="ik-label">총 관수</div><div class="ik-val">${d.n_irrigations ?? '—'}</div><div class="ik-unit">회/일</div></div>
        <div class="irr-kpi"><div class="ik-label">총 공급량</div><div class="ik-val">${fmt0(d.supply_total_ml)}</div><div class="ik-unit">ml/slab</div></div>
        <div class="irr-kpi"><div class="ik-label">ET₀</div><div class="ik-val">${fmt1(d.et0_mm)}</div><div class="ik-unit">mm</div></div>
        <div class="irr-kpi"><div class="ik-label">ETc (Kc=${fmt1(d.kc)})</div><div class="ik-val">${fmt1(d.etc_mm)}</div><div class="ik-unit">mm</div></div>
      </div>
      <div class="form-3col" style="gap:8px;margin-bottom:12px">${phases}</div>
      <div class="form-3col" style="gap:8px;font-size:11px">
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">배액 목표</div>
          <div style="font-weight:700;color:var(--green)">${fmt1(d.drain_target_pct)}%</div>
        </div>
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">P/I 교정</div>
          <div style="font-weight:700;color:${(d.pi_correction_lm2||0)>0?'var(--green)':'var(--yellow)'}">
            ${d.pi_correction_lm2 != null ? (Number(d.pi_correction_lm2)>=0?'+':'')+Number(d.pi_correction_lm2).toFixed(3)+' L/m²' : '미적용'}
          </div>
        </div>
        <div style="background:var(--card);padding:8px;border-radius:6px">
          <div style="color:var(--muted);margin-bottom:2px">증산량</div>
          <div style="font-weight:700;color:var(--accent)">${fmt1(d.transpiration_mm)} mm</div>
        </div>
      </div>
      <div style="margin-top:8px;font-size:10px;color:var(--muted)">
        🌱 ${_esc(d.crop_ko || '')} · ${_esc(d.growth_stage || stage)} · 작물크기 ${d.plant_size_pct || size}%
        ${d.note ? '· ' + _esc(d.note.slice(0,80)) : ''}
      </div>`;
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, 'ET₀ 스케줄 조회 실패');
  }
}

// ── 관수관리: 스케줄 예측 ─────────────────────────────────────────────────────
async function loadIrrigationSchedule() {
  const farmId  = $('irr-sched-farm')?.value || _defaultFarm();
  const trigger = parseFloat($('irr-trigger-mj')?.value || '2.0');
  const el = $('irr-sched-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation/schedule?trigger_mj_m2=${trigger}`);
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    if (d.n_irrigations != null) setText('irr-count-today', d.n_irrigations);
    el.innerHTML = `
      <div class="irr-sched-grid">
        <div class="irr-kpi"><div class="ik-label">관수 횟수</div>
          <div class="ik-val">${d.n_irrigations ?? '—'}</div><div class="ik-unit">회/일</div></div>
        <div class="irr-kpi"><div class="ik-label">총 공급량</div>
          <div class="ik-val">${d.total_supply_ml != null ? Math.round(d.total_supply_ml) : '—'}</div><div class="ik-unit">ml/slab</div></div>
        <div class="irr-kpi"><div class="ik-label">GSR (전일)</div>
          <div class="ik-val">${fmtF(d.daily_gsr_mj_m2)}</div><div class="ik-unit">MJ/m²</div></div>
      </div>
      <div class="irr-timeline" style="margin-top:12px">
        <div class="irr-time-dot"></div>
        <span style="font-weight:700">첫 관수</span>
        <span style="color:var(--accent);font-size:16px;font-weight:700">${_esc(d.first_irrigation ?? '—')}</span>
        <span style="color:var(--muted)">→</span>
        <span style="font-weight:700">마지막 관수</span>
        <span style="color:var(--accent);font-size:16px;font-weight:700">${_esc(d.last_irrigation ?? '—')}</span>
      </div>
      <div style="margin-top:8px;font-size:11px;color:var(--muted)">
        📡 ${d.source === 'kma_asos_yesterday' ? 'ASOS 전일 실측 기반' : '계절 평균 기반'} — ${_esc(d.note ?? '')}
      </div>`;
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '관수 일정 조회 실패');
  }
}

async function submitIrrigationP4() {
  const farmId    = $('irri-farm-sel2')?.value;
  const supply    = parseFloat($('irri-supply')?.value || '0');
  const drain     = parseFloat($('irri-drain')?.value || '0');
  const ec        = parseFloat($('irri-ec2')?.value || '0');
  const maxWt     = parseFloat($('irri-maxwt')?.value || '0');
  const sunsetWt  = parseFloat($('irri-sunsetwt')?.value || '0');
  const uptake    = parseFloat($('irri-uptake')?.value || '0');
  if (!farmId) { _setResult('irri-result2', 'warn', '농장을 선택하세요'); return; }
  if (!supply)  { _setResult('irri-result2', 'warn', '공급량을 입력하세요'); return; }

  const dateVal = $('irri-date')?.value || new Date().toISOString().slice(0,10);
  const body = {
    crop: _farmsData.find(f=>f.farm_id===farmId)?.crop_ko || '알 수 없음',
    date: dateVal,
    slab_vol_l: 15.0,
    max_wt_kg:    maxWt    || null,
    sunset_wt_kg: sunsetWt || null,
    periods: [{ period: 2, supply_ml: supply, drain_ml: drain, ec: ec||null, slab_wt_kg: null }],
  };
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    const s = d.summary || {};
    const drPct = s.dr_pct_mean != null ? s.dr_pct_mean.toFixed(1) : '—';
    const wcMean= s.wc_mean     != null ? s.wc_mean.toFixed(1)     : '—';
    _setResult('irri-result2', 'ok', `저장 완료 — 배액률 ${drPct}%, 함수율 ${wcMean}%`);
    loadIrrigationAnalysis(farmId);
    setTimeout(() => loadIrrigationHistory(farmId), 400);
  } catch(e) {
    _setResult('irri-result2', 'err', '저장 실패: ' + e.message);
  }
}

function renderIrrigationAnomalies(metrics) {
  const el = $('irr-anomaly-body');
  if (!el) return;
  const alerts = [];
  const checks = [
    { key:'dr_pct_mean',  label:'배액률',    unit:'%',    norm:[20,35], crit:[15,45] },  // ★ 모바일 기준 통일(목표 20~30·허용~35)
    { key:'nl_pct',       label:'야간소실률', unit:'%',    norm:[3,7],   crit:[1,10]  },
    { key:'uptake_efficiency_ml_j', label:'흡수효율', unit:'ml/J', norm:[1.0,2.5], crit:[0.7,3.0] },
  ];
  checks.forEach(c => {
    const v = metrics[c.key];
    if (v == null || isNaN(v)) return;
    let sev = null, dir = '';
    if (v < c.crit[0] || v > c.crit[1]) { sev = 'critical'; dir = v < c.crit[0] ? '너무 낮음' : '너무 높음'; }
    else if (v < c.norm[0] || v > c.norm[1]) { sev = 'major'; dir = v < c.norm[0] ? '낮음' : '높음'; }
    if (sev) alerts.push({ sev, label: c.label, val: v.toFixed(2), unit: c.unit,
      range: `정상 ${c.norm[0]}~${c.norm[1]}${c.unit}`, dir });
  });
  if (!alerts.length) {
    el.innerHTML = '<div style="color:var(--green);font-size:12px;padding:12px 0;text-align:center">✅ 관수 지표 정상 범위</div>';
    return;
  }
  el.innerHTML = '<div class="irr-anomaly-list">' + alerts.map(a =>
    `<div class="irr-alert-row ${a.sev}">
      <span>${a.sev==='critical'?'🔴':'🟡'}</span>
      <div><strong>${a.label}</strong> ${a.val}${a.unit} — ${a.range} <span style="color:var(--muted)">${a.dir}</span></div>
    </div>`
  ).join('') + '</div>';
}

function checkIrrigationAnomalies() {
  const farmId = $('irri-farm-sel2')?.value;
  if (farmId) { loadIrrigationAnalysis(farmId); return; }
  const s = parseFloat($('irri-supply')?.value||'0');
  const d = parseFloat($('irri-drain')?.value||'0');
  const m = parseFloat($('irri-maxwt')?.value||'0');
  const sw= parseFloat($('irri-sunsetwt')?.value||'0');
  renderIrrigationAnomalies({
    dr_pct_mean: s>0 ? d/s*100 : null,
    nl_pct: m>0&&sw>0 ? (m-sw)/m*100 : null,
  });
}

async function loadIrrigationAnalysis(farmId) {
  const el = $('irr-anomaly-body');
  if (!el || !farmId) return;
  el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px 0">분석 중…</div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/irrigation/analysis?days=7`);
    if (!d.data_days) {
      el.innerHTML = _emptyHtml('💧', '관수 데이터 없음', '최근 7일 관수 기록이 없습니다');
      return;
    }
    if (d.alerts && d.alerts.length) {
      el.innerHTML = '<div class="irr-anomaly-list">' + d.alerts.map(a => {
        const sevClass = a.severity === 'critical' ? 'critical' : a.severity === 'major' ? 'major' : 'minor';
        const icon = a.severity === 'critical' ? '🔴' : a.severity === 'major' ? '🟡' : 'ℹ️';
        return `<div class="irr-alert-row ${sevClass}">
          <span>${icon}</span>
          <div><strong>${_esc(a.label_ko)}</strong> — ${_esc(a.message_ko)}</div>
        </div>`;
      }).join('') + '</div>';
    } else {
      el.innerHTML = '<div style="color:var(--green);font-size:12px;padding:8px 0;text-align:center">✅ 최근 7일 관수 지표 정상</div>';
    }
    const sm = d.summary || {};
    const rows = ['wc_mean','dr_pct_mean','ec_drain','nl_pct'].map(k => {
      const v = sm[k];
      if (!v) return '';
      const statusColor = v.status === 'normal' ? 'var(--green)' : v.status === 'high' ? 'var(--red)' : 'var(--yellow)';
      return `<tr>
        <td style="color:var(--muted)">${_esc(v.label_ko)}</td>
        <td style="text-align:right;font-weight:600;color:${statusColor}">${_esc(String(v.latest))}${_esc(v.unit)}</td>
        <td style="text-align:right;color:var(--muted);font-size:10px">${_esc(String(v.avg))}${_esc(v.unit)} (7일평균)</td>
      </tr>`;
    }).filter(Boolean).join('');
    if (rows) {
      el.innerHTML += `<div class="table-scroll-wrap"><table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:12px">${rows}</table></div>
        <div style="font-size:10px;color:var(--muted);margin-top:4px">데이터: ${d.data_days}일 (${_esc(d.start||'')}~${_esc(d.end||'')})</div>`;
    }
    if (d.data_days)    setText('irr-count-today', d.avg_daily_count != null ? d.avg_daily_count : (d.total_count != null ? Math.round(d.total_count / d.data_days) : '—'));
    if (sm.dr_pct_mean) setText('irr-drain-rate', (sm.dr_pct_mean.latest||'—') + '%');
    if (sm.ec_drain)    setText('irr-drain-ec',   (sm.ec_drain.latest||'—') + ' dS/m');
    if (sm.ph_supply)   setText('irr-supply-ph',  sm.ph_supply.latest||'—');
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '관수 이상 감지 조회 실패');
  }
}
