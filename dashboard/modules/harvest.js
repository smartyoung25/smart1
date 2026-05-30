// ── 재배 권고 이력 ─────────────────────────────────────────────────────────────
let _advisoryEntries = [];

async function loadAdvisoryHistory() {
  if (!_token) return;
  const limit = $('adv-filter-limit') ? $('adv-filter-limit').value : 50;
  try {
    let data;
    if (_myFarmId) {
      // 농장주 계정: 내 농장 전용 권고 이력 엔드포인트 사용
      data = await apiFetch(`/api/farms/${encodeURIComponent(_myFarmId)}/journal/advisory?limit=${limit}`);
      // 농장 ID 필터 인풋 숨기기 (본인 농장만 표시)
      const filterInput = $('adv-filter-farm');
      if (filterInput) {
        filterInput.value = _myFarmId;
        filterInput.style.display = 'none';
      }
    } else {
      data = await apiFetch(`/api/admin/advisor/history?limit=${limit}`);
    }
    _advisoryEntries = data.entries || [];
    renderAdvisoryFeed();
    // 농장주 계정: 빈도 요약도 이력 로드 완료 후 갱신
    if (_myFarmId) _renderFarmerAdvisorySummary();
  } catch(e) {
    console.warn('[advisor] 이력 조회 실패:', e);
    const feed = $('advisory-feed');
    if (feed) feed.innerHTML = `<div class="data-err-box">권고 이력 조회 실패<span class="data-err-reason">${_esc(e.message)}</span></div>`;
  }
}

function renderAdvisoryFeed() {
  const feed   = $('advisory-feed');
  const empty  = $('adv-empty');
  const filter = ($('adv-filter-farm') ? $('adv-filter-farm').value.trim().toLowerCase() : '');

  const entries = filter
    ? _advisoryEntries.filter(e => (e.farm_id || '').toLowerCase().includes(filter))
    : _advisoryEntries;

  if (!entries.length) {
    feed.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  const FIELD_LABELS = {
    temp_internal: '내부온도', humidity_int: '내부습도', co2_ppm: 'CO₂',
    soil_temp: '지온', ec_dsm: 'EC',
  };
  const CH_LABEL = { email:'이메일', sms:'SMS', kakao:'카카오', dry_run:'DRY-RUN', error:'오류' };

  feed.innerHTML = entries.map(entry => {
    const ts      = entry.ts ? new Date(entry.ts).toLocaleString('ko-KR') : '—';
    const topSide = entry.advices?.length ? entry.advices[0].side : 'both';
    const sideClass = topSide === 'high' ? 'side-high' : topSide === 'low' ? 'side-low' : '';

    const itemsHtml = (entry.advices || []).map(a => {
      const fname = FIELD_LABELS[a.field] || a.field;
      const optStr = (a.optimal && a.optimal.length >= 2) ? `최적 ${a.optimal[0]}–${a.optimal[1]}` : '';
      const arrow  = a.side === 'high' ? '↑' : a.side === 'low' ? '↓' : '↕';
      return `<div class="adv-item">
        <span class="adv-field">${arrow} ${_esc(fname)}</span>
        <span class="adv-action">${_esc(a.action)}</span>
        <span class="adv-val">(현재 ${_esc(String(a.value??''))} / ${_esc(optStr)})</span>
      </div>`;
    }).join('');

    const chHtml = (entry.channels || []).map(ch =>
      `<span class="adv-ch-badge ${_esc(ch)}">${_esc(CH_LABEL[ch] || ch)}</span>`
    ).join('');

    return `<div class="adv-entry ${sideClass}">
      <div class="adv-entry-hdr">
        <div style="display:flex;gap:6px;align-items:center">
          <span class="adv-farm-tag">${_esc(entry.farm_id)}</span>
          <span class="adv-crop-tag">${_esc(entry.crop_ko)}</span>
        </div>
        <span class="adv-ts">${ts}</span>
      </div>
      <div class="adv-items">${itemsHtml}</div>
      <div class="adv-channels">${chHtml}</div>
    </div>`;
  }).join('');
}

// ── 권고 빈도 히트맵 ──────────────────────────────────────────────────────────
const FIELD_SHORT = {
  temp_internal:'내부온도', humidity_int:'내부습도',
  co2_ppm:'CO₂', soil_temp:'지온', ec_dsm:'EC',
};

async function loadAdvisorySummary() {
  if (!_token) return;
  if (_myFarmId) {
    // 농장주 계정: _advisoryEntries 기반 로컬 집계, 히트맵 관련 UI 숨기기
    const daysCtrl = $('heatmap-days-sel');
    if (daysCtrl) daysCtrl.closest('div')?.style && (daysCtrl.closest('div').style.display = 'none');
    _renderFarmerAdvisorySummary();
    return;
  }
  const days = $('heatmap-days-sel') ? $('heatmap-days-sel').value : 30;
  try {
    const d = await apiFetch(`/api/admin/advisor/summary?days=${days}`);
    renderHeatmap(d);
  } catch(e) {
    console.warn('[heatmap] 조회 실패:', e);
    const tbody = $('heatmap-tbody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="10" class="err-inline" style="padding:8px">${_esc(e.message)}</td></tr>`;
  }
}

// 농장주 전용: 권고 이력에서 항목별 빈도 막대 차트 렌더
function _renderFarmerAdvisorySummary() {
  const heatmapBody = $('heatmap-body');
  if (!heatmapBody) return;
  if (!_advisoryEntries.length) {
    heatmapBody.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🌿</div>권고 이력이 없습니다<div class="empty-state-sub">AI 권고가 발생하면 항목별 빈도가 표시됩니다</div></div>';
    return;
  }
  // 항목별 빈도 집계
  const freq = {};
  _advisoryEntries.forEach(entry => {
    (entry.advices || []).forEach(a => {
      const label = FIELD_SHORT[a.field] || a.field;
      freq[label] = (freq[label] || 0) + 1;
    });
  });
  const sorted = Object.entries(freq).sort((a, b) => b[1] - a[1]);
  const maxVal = sorted.length ? sorted[0][1] : 1;
  const bars = sorted.map(([label, count]) => {
    const pct = Math.round(count / maxVal * 100);
    return `<div style="display:grid;grid-template-columns:80px 1fr 30px;align-items:center;gap:8px;margin-bottom:6px">
      <span style="font-size:11px;color:var(--muted);text-align:right">${_esc(label)}</span>
      <div style="background:var(--card-soft);border-radius:4px;overflow:hidden;height:16px">
        <div style="width:${pct}%;background:var(--accent);height:100%;border-radius:4px;transition:width .3s"></div>
      </div>
      <span style="font-size:11px;color:var(--fg);font-weight:600">${count}</span>
    </div>`;
  }).join('');
  heatmapBody.innerHTML = `
    <div style="margin-bottom:8px;font-size:11px;color:var(--muted)">최근 ${_advisoryEntries.length}건 기준 항목별 권고 빈도</div>
    ${bars}`;
}

function renderHeatmap(d) {
  const empty  = $('heatmap-empty');
  const thead  = $('heatmap-thead');
  const tbody  = $('heatmap-tbody');

  if (!d.by_farm_field || d.by_farm_field.length === 0) {
    if (empty) empty.style.display = 'block';
    thead.innerHTML = ''; tbody.innerHTML = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  const fields = [...new Set(d.by_farm_field.map(e => e.field))].sort();
  const farms  = [...new Set(d.by_farm_field.map(e => e.farm_id))].slice(0, 15);

  const lookup = {};
  d.by_farm_field.forEach(e => { lookup[`${e.farm_id}||${e.field}`] = e.count; });

  const maxCount = Math.max(...d.by_farm_field.map(e => e.count), 1);

  function hmClass(n) {
    if (!n) return 'hm-0';
    const ratio = n / maxCount;
    if (ratio < 0.2) return 'hm-1';
    if (ratio < 0.4) return 'hm-2';
    if (ratio < 0.6) return 'hm-3';
    if (ratio < 0.8) return 'hm-4';
    return 'hm-5';
  }

  thead.innerHTML = '<th>농장</th>' +
    fields.map(f => `<th>${_esc(FIELD_SHORT[f] || f)}</th>`).join('') +
    '<th>합계</th>';

  tbody.innerHTML = farms.map(fid => {
    const total = fields.reduce((s, f) => s + (lookup[`${fid}||${f}`] || 0), 0);
    const cells = fields.map(f => {
      const n = lookup[`${fid}||${f}`] || 0;
      return `<td><span class="hm-cell ${hmClass(n)}">${n || ''}</span></td>`;
    }).join('');
    return `<tr><td style="font-size:11px;white-space:nowrap">${_esc(fid)}</td>${cells}<td style="font-weight:600">${total}</td></tr>`;
  }).join('');
}

// ── 생육 모델 세그먼트 컨트롤 ──────────────────────────────────────────────
let _growthModelType = 'kaasa'; // 'rda' | 'kaasa' | 'dynamic'

function setGrowthModel(type) {
  _growthModelType = type;
  document.querySelectorAll('#model-seg-ctrl .seg-btn').forEach(btn => {
    btn.classList.toggle('seg-active', btn.dataset.model === type);
    btn.classList.remove('green', 'blue', 'orange');
    if (btn.dataset.model === type) {
      if (type === 'kaasa')        btn.classList.add('green');
      else if (type === 'dynamic') btn.classList.add('orange');
    }
  });
  const hint = document.querySelector('#sec-growth .explain-box b');
  if (hint) {
    const labels = { rda: '농진청 표준', kaasa: 'KAASA AI', dynamic: '내 농장 동적' };
    hint.textContent = (labels[type] || 'AI') + ' 생육모델:';
  }
  loadGrowthHarvestRevenue();
}

// ── 생육/재배: 수확량 + 매출·소득 예측 ──────────────────────────────────────
async function loadGrowthHarvestRevenue() {
  const farmId = $('growth-farm-sel')?.value || _defaultFarm();
  if (!farmId) return;
  if ($('whatif-farm-sel')) $('whatif-farm-sel').value = farmId;
  const hEl = $('growth-harvest-body'), rEl = $('growth-revenue-body');
  if (hEl) hEl.innerHTML = '<div class="spinner"></div>';
  if (rEl) rEl.innerHTML = '<div class="spinner"></div>';
  try {
    const [harv, rev] = await Promise.allSettled([
      apiFetch(`/api/farms/${farmId}/harvest`),
      apiFetch(`/api/farms/${farmId}/revenue`),
    ]);
    const h = harv.status === 'fulfilled' ? harv.value : null;
    const r = rev.status  === 'fulfilled' ? rev.value  : null;
    const fmt  = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    if (hEl) hEl.innerHTML = `
      <div class="harvest-grid">
        <div class="harvest-kpi"><div class="hk-label">예상 수확량</div>
          <div class="hk-val">${fmtF(h?.yield_kg_forecast)} <span style="font-size:12px;color:var(--muted)">kg</span></div></div>
        <div class="harvest-kpi"><div class="hk-label">80% 신뢰구간</div>
          <div class="hk-val" style="font-size:14px">${h?.yield_q10!=null?`${fmtF(h.yield_q10)}–${fmtF(h.yield_q90)} kg`:'—'}</div></div>
        <div class="harvest-kpi"><div class="hk-label">잔여 재배일</div>
          <div class="hk-val">${h?.days_to_harvest ?? '—'} <span style="font-size:12px;color:var(--muted)">일</span></div></div>
      </div>
      <div class="harvest-note">${_esc(h?.crop_ko||'')} · 면적 ${h?.area_m2!=null?h.area_m2.toLocaleString('ko-KR')+' m²':'—'}</div>
      ${h?.confidence_grade ? (() => {
        const grade = h.confidence_grade;
        const isHigh = grade.startsWith('높음');
        const isMid  = grade.startsWith('보통');
        const badgeColor = isHigh ? '#22c55e' : isMid ? '#f59e0b' : '#94a3b8';
        const badgeBg    = isHigh ? 'rgba(34,197,94,.12)' : isMid ? 'rgba(245,158,11,.12)' : 'rgba(148,163,184,.10)';
        return `<div style="margin-top:5px;display:flex;align-items:center;gap:5px;flex-wrap:wrap">
          <span style="background:${badgeBg};color:${badgeColor};border:1px solid ${badgeColor}33;border-radius:4px;padding:2px 6px;font-size:10px;font-weight:600">모델 신뢰도: ${_esc(grade)}</span>
          ${h.mape_note ? `<span style="font-size:10px;color:var(--muted)">${_esc(h.mape_note)}</span>` : ''}
        </div>`;
      })() : ''}`;

    if (rEl) {
      if (!r) {
        rEl.innerHTML = `<div style="color:var(--muted);font-size:12px;padding:16px 0;text-align:center">소득 예측 조회 실패 — 잠시 후 다시 시도하세요</div>`;
      } else {
        const profit     = (r.revenue_krw ?? 0) - (r.cost_krw ?? 0);
        const pCls       = profit >= 0 ? 'positive' : 'negative';
        const confPct    = r.model_confidence != null ? Math.round(r.model_confidence * 100) : null;
        const confBar    = confPct != null
          ? `<div style="background:var(--border);border-radius:4px;height:4px;margin-top:2px">
               <div style="background:${confPct>=60?'#3ecf8e':confPct>=30?'#f5a623':'#f2645a'};width:${confPct}%;height:100%;border-radius:4px"></div>
             </div>`
          : '';
        const gateIcon   = r.model_gate_pass === true ? '✅' : r.model_gate_pass === false ? '⚠️' : '';
        const srcLabel   = r.revenue_source === 'ml_model' ? 'M3모델' : r.revenue_source === 'm2_yield_x_price' ? 'M2×시세' : '통계기반';
        const priceLabel = r.price_source === 'kamis_live' || r.price_source === 'kamis_cache' ? '🟢실시간' : '📊평균';
        const marginTxt  = r.profit_margin_pct != null ? ` · 이익률 ${r.profit_margin_pct}%` : '';
        rEl.innerHTML = `
          <div class="harvest-grid">
            <div class="harvest-kpi">
              <div class="hk-label">예상 수확량 ${gateIcon}</div>
              <div class="hk-val">${fmtF(r.yield_kg_forecast)} <span class="unit-muted">kg</span></div>
              ${confPct != null ? `<div style="font-size:9px;color:var(--muted);margin-top:1px">모델신뢰도 ${confPct}%</div>${confBar}` : ''}
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">시세 ${priceLabel}</div>
              <div class="hk-val">${fmt(r.price_krw_kg)} <span class="unit-muted">원/kg</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${_esc(r.crop_ko||'')} · ${r.area_m2!=null?r.area_m2.toLocaleString('ko-KR')+' m²':''}</div>
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">예상 매출</div>
              <div class="hk-val">${fmt(r.revenue_krw)} <span class="unit-muted">원</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${srcLabel}</div>
            </div>
            <div class="harvest-kpi">
              <div class="hk-label">예상 비용</div>
              <div class="hk-val">${fmt(r.cost_krw)} <span class="unit-muted">원</span></div>
            </div>
            <div class="harvest-kpi" style="grid-column:span 2">
              <div class="hk-label">예상 순이익</div>
              <div class="hk-val ${pCls}" style="font-size:20px">${profit>=0?'+':''}${fmt(profit)} <span style="font-size:11px">원</span></div>
              <div style="font-size:9px;color:var(--muted);margin-top:1px">${marginTxt}</div>
            </div>
          </div>
          ${r.model_gate_pass === false ? `<div style="background:rgba(242,100,90,.12);border:1px solid rgba(242,100,90,.3);border-radius:6px;padding:6px 10px;margin-top:8px;font-size:11px;color:#f2645a">⚠️ M2 수확량 모델 게이트 미통과 (MAPE ${r.model_confidence!=null?Math.round((1-r.model_confidence)*100):'-'}%대) — 통계 기준값과 블렌딩하여 표시 중. 모델 재학습 권장.</div>` : ''}`;
      }
    }
    if (h) {
      const daysLeft  = h.days_to_harvest ?? null;
      const daysSince = h.days_since_planting ?? h.days_elapsed ?? null;
      if (daysSince != null) setText('growth-days-since', daysSince + '일');
      else if (daysLeft != null) setText('growth-days-since', 'D-' + daysLeft);
      const stage = h.growth_stage_ko || h.growth_stage ||
        (h.confidence_grade ? (daysLeft != null && daysLeft < 14 ? '수확기' : '생육중') : null);
      if (stage) setText('growth-stage-label', stage);
      const aiAdj = h.ai_adjust_pct ?? h.model_adjustment_pct ?? null;
      if (aiAdj != null) setText('growth-ai-adjust', (aiAdj >= 0 ? '+' : '') + aiAdj + '%');
      else setText('growth-ai-adjust', h.confidence_grade || '—');
      if (h.yield_kg_forecast) { setText('harvest-quality-rate', '—'); const qEl=$('harvest-quality-rate'); if(qEl && !qEl.nextElementSibling?.classList.contains('kc-hint2')) { const hint=document.createElement('span'); hint.className='kc-hint kc-hint2'; hint.textContent='데이터 준비 중'; qEl.after(hint); } }
    }
    if (h?.yield_kg_forecast) {
      setText('harvest-7d-kg', Number(h.yield_kg_forecast).toFixed(1));
    }
  } catch(e) {
    if (hEl) hEl.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
    if (rEl) rEl.innerHTML = `<span class="err-inline">소득 조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── What-if 시뮬레이션 ────────────────────────────────────────────────────────
function resetWhatIf() { $('whatif-result').innerHTML = ''; }

async function runWhatIf() {
  const farmId = $('whatif-farm-sel')?.value;
  if (!farmId) {
    const el = $('whatif-result');
    if (el) el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하세요']]);
    return;
  }
  const el = $('whatif-result');
  el.innerHTML = '<div class="spinner"></div>';
  const body = {};
  if ($('wi-temp')?.value) body.temp_internal = parseFloat($('wi-temp').value);
  if ($('wi-humi')?.value) body.humidity_int  = parseFloat($('wi-humi').value);
  if ($('wi-co2')?.value)  body.co2_ppm       = parseFloat($('wi-co2').value);
  if ($('wi-ec')?.value)   body.ec_dsm        = parseFloat($('wi-ec').value);
  try {
    const d = await apiFetch(`/api/farms/${farmId}/whatif`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const fmt = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF= n => n!=null ? Number(n).toFixed(1) : '—';
    const gain    = d.profit_gain_krw ?? d.revenue_gain_krw ?? 0;
    const gainCls = gain >= 0 ? 'pos' : 'neg';
    const scenarios = d.scenarios || [];
    let scenHtml = '';
    if (scenarios.length) {
      scenHtml = '<div style="margin-top:10px"><div style="font-size:11px;color:var(--muted);margin-bottom:6px">시나리오 비교</div>' +
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px">' +
        scenarios.map(s => {
          const sg = s.profit_gain_krw ?? s.revenue_change ?? 0;
          const sCls = sg >= 0 ? 'pos' : 'neg';
          return `<div class="wi-result-item">
            <div class="wi-label">${_esc(s.label || JSON.stringify(s.env||{}))}</div>
            <div class="wi-val ${sCls}">${sg>=0?'+':''}${fmt(sg)} 원</div>
          </div>`;
        }).join('') + '</div></div>';
    }
    el.innerHTML = `
      <div class="wi-result-grid">
        <div class="wi-result-item"><div class="wi-label">예측 수확량</div>
          <div class="wi-val">${fmtF(d.yield_kg_forecast)} kg</div></div>
        <div class="wi-result-item"><div class="wi-label">예측 매출</div>
          <div class="wi-val">${fmt(d.revenue_krw)} 원</div></div>
        <div class="wi-result-item"><div class="wi-label">수익 변화</div>
          <div class="wi-val ${gainCls}">${gain>=0?'+':''}${fmt(gain)} 원</div></div>
      </div>
      ${scenHtml}`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">시뮬레이션 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 제어 최적화: 권고 조회 ────────────────────────────────────────────────────
async function loadCtrlRecommendations() {
  const farmId = $('ctrl-farm-sel')?.value || _defaultFarm();
  const el = $('ctrl-reco-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/recommendations`);
    const items = d.recommendations || d.items || [];
    if (!items.length) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">현재 권고 사항이 없습니다 ✅</div>';
      return;
    }
    const { listHtml, gainHtml } = _renderRecoItems(items, farmId);
    el.innerHTML = `<div class="reco-list">${listHtml}</div>
      ${gainHtml}
      <button class="reco-apply-btn" style="margin-top:10px" data-farmid="${_esc(farmId)}" onclick="applyCtrlRecommendations(this.dataset.farmid)">✅ 권고 적용</button>`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}

function applyCtrlRecommendations(farmId) {
  BottomSheet.open(
    '권고 자동 제어 적용',
    `<p style="line-height:1.7;font-size:13px"><b>${_esc(farmId)}</b> 농장에 AI 권고를 적용합니다.<br>이 작업은 <b>자동 제어 명령을 발송</b>합니다.</p>`,
    '권고 적용',
    async () => {
      const btn = document.querySelector(`.reco-apply-btn[data-farmid="${farmId}"]`);
      if (btn) btn.disabled = true;
      try {
        await apiFetch(`/api/farms/${farmId}/apply`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ rank: 1, confirmed: false }),
        });
        showToast('✅ 권고 적용 요청 완료');
        loadCtrlRecommendations();
      } catch(e) {
        showToast('❌ 적용 실패: ' + e.message);
      } finally {
        if (btn) btn.disabled = false;
      }
    }
  );
}

// ── 통합 홈 대시보드 (Hero) ───────────────────────────────────────────────────
async function loadHeroDashboard(farmId) {
  if (!farmId) return;
  const fmt = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
  const fmtF = n => n != null ? Number(n).toFixed(1) : '—';

  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const mc = (d.margin_per_kg ?? 0) > 0 ? '#22c55e' : '#ef4444';
    setText('hero-cost',   fmt(d.cost_per_kg));
    setText('hero-cost-hint', `원/kg${d.growth_stage ? ' · '+d.growth_stage : ''}`);
    setText('hero-margin', fmt(d.margin_per_kg));
    const marginHint = d.harvest_timing?.diff > 300 ? '내일 출하 유리 ↑' : '오늘 출하 기준';
    setText('hero-margin-hint', marginHint);
    const incRate = fmtF(d.income_rate_pct);
    setText('hero-income', incRate !== '—' ? incRate + '%' : '—');
    const el = $('hero-income');
    if (el) el.style.color = (d.income_rate_pct ?? 0) >= 50 ? '#22c55e' : (d.income_rate_pct ?? 0) >= 30 ? '#f59e0b' : '#ef4444';

    setText('c5-cost-kg',   fmt(d.cost_per_kg));
    setText('c5-margin-kg', fmt(d.margin_per_kg));
    setText('c5-income-rate', incRate !== '—' ? incRate + '%' : '—');
    setText('c5-breakeven',  fmt(d.breakeven_kg));
    setText('c5-cost-hint',   d.growth_stage || '원/kg');

    const ht = d.harvest_timing || {};
    const mktP    = d.market_price_per_kg ?? 0;
    const poolFac = d.pool_price_factor   ?? 1.083;
    const indLog  = d.logistics_cost_ind  ?? 320;
    const poolLog = d.logistics_cost_pool ?? 210;
    const costKg  = d.cost_per_kg ?? 0;
    const poolPrice = Math.round(mktP * poolFac);
    setText('c5-ind-price',      fmt(mktP));
    setText('c5-pool-price',     fmt(poolPrice));
    setText('c5-ind-logistics',  indLog  + '원');
    setText('c5-pool-logistics', poolLog + '원');
    const indMgn  = Math.round(mktP     - costKg - indLog);
    const poolMgn = Math.round(poolPrice - costKg - poolLog);
    setText('c5-ind-margin',  indMgn  !== 0 ? fmt(indMgn)  + '원' : '0원');
    setText('c5-pool-margin', poolMgn !== 0 ? fmt(poolMgn) + '원' : '0원');
    const effect = poolMgn - indMgn;
    setText('c5-pool-effect', effect !== 0 ? (effect > 0 ? '+' : '') + fmt(effect) + '원/kg' : '동일');

    const cb = d.cost_breakdown || {};
    const total = cb.total_per_m2 || 1;
    const ePct  = Math.round((cb.energy_per_m2  || 0) / total * 100);
    const lPct  = Math.round((cb.labor_per_m2   || 0) / total * 100);
    const nPct  = Math.round((cb.nutrient_per_m2|| 0) / total * 100);
    const lgPct = Math.max(0, 100 - ePct - lPct - nPct);
    setBar('cost-bar-energy',    ePct,  'cost-pct-energy');
    setBar('cost-bar-labor',     lPct,  'cost-pct-labor');
    setBar('cost-bar-material',  nPct,  'cost-pct-material');
    setBar('cost-bar-logistics', lgPct, 'cost-pct-logistics');

    if (d.harvest_7d_kg != null) {
      setText('harvest-7d-kg', fmt(d.harvest_7d_kg));
      setText('harvest-pool-margin', poolMgn !== 0 ? fmt(poolMgn) + '원/kg' : '—');
    }

    const modeEl = $('hero-mode-pill');
    if (modeEl && d.control_mode) {
      const heroModeMap = { manual:'수동보조', advisory:'권고형', approval:'승인형 자동제어', full_auto:'완전자동' };
      modeEl.textContent = heroModeMap[d.control_mode] || d.control_mode;
    }
  } catch(e) { /* hero는 선택적 — 실패해도 계속 */ }

  try {
    const r = await apiFetch(`/api/farms/${farmId}/recommendations`);
    const recs = r.recommendations || r.items || r || [];
    if (!Array.isArray(recs) || !recs.length) return;

    const TIER_BTN  = { auto: '', approval_required: 'orange', checklist: 'blue' };
    const TIER_LABEL= { auto: '적용', approval_required: '승인', checklist: '확인' };
    const colors = ['','blue','orange','red'];

    // 카테고리 감지 헬퍼
    const _cat = a => {
      if (!a) return { icon:'⚙️', label:'제어', cls:'', sec:'control' };
      if (/온도|습도|CO2|이산화탄소|일사량|환기|냉방|난방/.test(a)) return { icon:'🌡️', label:'환경제어', cls:'cat-env',     sec:'environ' };
      if (/관수|EC|pH|배액|급액|양액|드레인/.test(a))               return { icon:'💧', label:'관수·양액', cls:'cat-irr',     sec:'irrigation' };
      if (/수확|출하|수확량|판매/.test(a))                           return { icon:'🌾', label:'수확·출하', cls:'cat-harvest',  sec:'market' };
      if (/병해|해충|방제|곰팡이|잿빛/.test(a))                     return { icon:'🔬', label:'병해충',    cls:'cat-pest',    sec:'control' };
      return { icon:'⚙️', label:'제어', cls:'', sec:'control' };
    };

    // 기본 환경 권고 항목
    const allItems = recs.slice(0, 5).map((rec, i) => {
      const cls      = colors[i % colors.length];
      const tierKey  = rec.tier_action || 'checklist';
      const act      = TIER_BTN[tierKey]  || 'blue';
      const btnLabel = TIER_LABEL[tierKey] || '확인';
      const profit   = rec.profit_delta != null ? `+${Math.round(rec.profit_delta).toLocaleString('ko-KR')}원` : '';
      const cat      = _cat(rec.action_ko);
      // tier가 auto면 카테고리 섹션 우선, 아니면 control
      const destSection = tierKey === 'auto' ? cat.sec : (tierKey === 'approval_required' ? 'control' : cat.sec);
      return `<div class="todo-item">
        <div class="todo-num ${cls}">${i+1}</div>
        <div class="todo-text">
          <span class="todo-cat-badge ${cat.cls}">${cat.icon} ${cat.label}</span>
          <b>${_esc(rec.action_ko || '권고')}</b>
          <span>${profit}</span>
        </div>
        <button class="todo-action ${act}" onclick="showSection('${destSection}')">${btnLabel}</button>
      </div>`;
    });

    // 이상감지 항목 보강 (anomaly API)
    try {
      const anomRes = await apiFetch(`/api/farms/${farmId}/anomalies/latest`);
      const anomList = anomRes.anomalies || anomRes.items || [];
      const criticals = anomList.filter(a => a.severity === 'critical' || a.severity === 'high');
      criticals.slice(0, 2).forEach(a => {
        allItems.push(`<div class="todo-item">
          <div class="todo-num red">🚨</div>
          <div class="todo-text">
            <span class="todo-cat-badge cat-alert">⚠️ 이상감지</span>
            <b>${_esc(a.variable_ko || a.variable || '센서 이상')} ${_esc(a.value != null ? String(Number(a.value).toFixed(1)) + (a.unit||'') : '')}</b>
            <span>${_esc(a.message_ko || '즉시 확인 필요')}</span>
          </div>
          <button class="todo-action orange" onclick="showSection('environ')">확인</button>
        </div>`);
      });
    } catch(_) { /* 이상감지 API 없으면 무시 */ }

    const todoHtml = allItems.join('');
    const tb = $('todo-body');
    if (tb) tb.innerHTML = todoHtml;
    setText('todo-meta', `AI 생성 ${recs.length}건`);

    const immediate = recs.filter(r => r.tier_action === 'auto').length;
    const growth    = recs.filter(r => r.tier_action === 'checklist').length;
    const profit    = recs.filter(r => r.tier_action === 'approval_required').length;
    const maxN = Math.max(immediate, growth, profit, 1);
    const iPct = Math.round(immediate / maxN * 100);
    const gPct = Math.round(growth    / maxN * 100);
    const pPct = Math.round(profit    / maxN * 100);
    setBar('bar-immediate', iPct, 'bv-immediate', immediate+'건');
    setBar('bar-growth-s',  gPct, 'bv-growth',   growth+'건');
    setBar('bar-profit',    pPct, 'bv-profit',   profit+'건');

    const topRec = recs[0];
    setText('ai-reco-explain', '');
    const exEl = $('ai-reco-explain');
    if (exEl && topRec) exEl.innerHTML = `<b>추천:</b> ${_esc(topRec.action_ko || '')}`;
  } catch(e) {
    const tb = $('todo-body');
    if (tb) tb.innerHTML = `<div class="todo-item"><div class="todo-num">!</div><div class="todo-text"><b>AI 권고 조회 실패</b><span>${_esc(e.message)||'서버 연결 확인'}</span></div><button class="todo-action gray">재시도</button></div>`;
  }
}

// ── SFROP 시나리오 ────────────────────────────────────────────────────────────
async function loadSfropScenarios() {
  const farmId = $('sfrop-farm-sel')?.value || _defaultFarm();
  const el = $('sfrop-scenario-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const base = {
      name: '현재기준',
      energy_idx: 100, brix: 9.2, yield_idx: 100,
      income: d.income_rate_pct ?? 50,
      cost_per_kg: d.cost_per_kg ?? 0,
      margin_per_kg: d.margin_per_kg ?? 0,
    };
    const scenarios = [
      { ...base },
      {
        name: '생육최적화', icon: '🌱',
        energy_idx: 95, brix: 9.8, yield_idx: 116,
        income: Math.min(99, base.income * 1.12),
        cost_per_kg: Math.round(base.cost_per_kg * 0.96),
        margin_per_kg: Math.round(base.margin_per_kg * 1.12),
        tip: 'LED 스펙트럼 최적화 + CO₂ 800ppm 유지',
      },
      {
        name: '에너지최적화', icon: '⚡',
        energy_idx: 65, brix: 9.1, yield_idx: 97,
        income: Math.min(99, base.income * 1.08),
        cost_per_kg: Math.round(base.cost_per_kg * 0.82),
        margin_per_kg: Math.round(base.margin_per_kg * 1.08),
        tip: '야간 보온 강화 + 인버터 제어 최적화',
      },
      {
        name: 'AI통합최적화', icon: '🤖',
        energy_idx: 63, brix: 10.1, yield_idx: 119,
        income: Math.min(99, base.income * 1.21),
        cost_per_kg: Math.round(base.cost_per_kg * 0.80),
        margin_per_kg: Math.round(base.margin_per_kg * 1.21),
        tip: 'SFROP v2.0 전체 권고 적용 시 최적 상태',
      },
    ];
    const fmtN = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';

    const cols = scenarios.map((s, i) => {
      const isBase = i === 0;
      const isBest = i === 3;
      const border = isBest ? '2px solid var(--accent)' : '1px solid var(--border)';
      const bg     = isBest ? 'var(--green-soft)' : 'var(--card-soft)';
      const gainM  = s.margin_per_kg - base.margin_per_kg;
      const gainColor = gainM > 0 ? 'var(--green)' : gainM < 0 ? 'var(--red)' : 'var(--muted)';
      return `
        <div style="border:${border};border-radius:10px;background:${bg};padding:14px;text-align:center">
          <div style="font-size:13px;font-weight:700;margin-bottom:10px;color:${isBest?'var(--accent)':'var(--text)'}">${s.icon||'📊'} ${s.name}</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">에너지 지수</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.energy_idx}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">당도 (Brix)</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.brix}</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">수확량 지수</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${s.yield_idx}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">소득률</div>
          <div style="font-size:16px;font-weight:700;margin-bottom:8px;color:var(--text)">${fmtF(s.income)}%</div>
          <div style="font-size:10px;color:var(--muted);margin-bottom:3px">kg당 마진</div>
          <div style="font-size:15px;font-weight:700;color:${gainColor};margin-bottom:8px">
            ${fmtN(s.margin_per_kg)} 원
            ${!isBase ? `<div style="font-size:11px">(${gainM>=0?'+':''}${fmtN(gainM)})</div>` : ''}
          </div>
          ${s.tip ? `<div style="font-size:10px;color:var(--muted);margin-top:4px;padding:6px;border-top:1px solid var(--border)">${s.tip}</div>` : ''}
        </div>`;
    }).join('');

    el.innerHTML = `
      <div class="form-4col" style="gap:10px;margin-top:4px">
        ${cols}
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:8px;text-align:right">
        * 시나리오 수치는 RDA 2022 실태조사 기반 추정값 · ERP 실시간 데이터 반영
      </div>`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">시나리오 계산 실패: ${_esc(e.message)}</span>`;
  }
}

// ── AI 어드바이저 최적 환경 조회 ─────────────────────────────────────────────
async function loadAdvisorOptimal() {
  const cropKo = $('advisor-crop-sel')?.value;
  const el = $('advisor-opt-body');
  if (!cropKo || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/admin/advisor/optimal/${encodeURIComponent(cropKo)}`);
    const LABELS = { temp_internal:'온도', humidity_int:'습도', co2_ppm:'CO₂', ec_dsm:'EC', solar_rad:'일사량' };
    const UNITS  = { temp_internal:'°C',  humidity_int:'%',   co2_ppm:'ppm', ec_dsm:'dS/m', solar_rad:'W/m²' };
    let items = [];
    if (d.ranges && d.ranges.length) {
      items = d.ranges.map(r => ({
        label: LABELS[r.field] || r.field,
        unit:  UNITS[r.field]  || '',
        val:   null,
        lo:    r.optimal_lo,
        hi:    r.optimal_hi,
        action_high: r.high_action,
        action_low:  r.low_action,
      }));
    } else {
      const opt = d.optimal_env || d.optimal || d;
      items = Object.keys(LABELS).map(k => ({
        label: LABELS[k], unit: UNITS[k],
        val:   opt[k] ?? null,
        lo:    opt[`${k}_min`] ?? opt[`${k}_p25`] ?? null,
        hi:    opt[`${k}_max`] ?? opt[`${k}_p75`] ?? null,
      }));
    }
    el.innerHTML = '<div class="advisor-opt-grid">' +
      items.map(it => {
        const mid = it.val != null ? Number(it.val).toFixed(1) :
                    (it.lo != null && it.hi != null ? ((it.lo+it.hi)/2).toFixed(1) : '—');
        const range = (it.lo != null && it.hi != null)
          ? `${Number(it.lo).toFixed(1)}~${Number(it.hi).toFixed(1)}` : '—';
        return `<div class="advisor-opt-item">
          <div class="ao-var">${_esc(it.label)}</div>
          <div class="ao-val">${_esc(mid)} <span style="font-size:10px;color:var(--muted)">${_esc(it.unit)}</span></div>
          <div class="ao-range">최적 ${_esc(range)}</div>
        </div>`;
      }).join('') + '</div>' +
      (d.note ? `<div style="font-size:11px;color:var(--muted);margin-top:8px">${_esc(d.note)}</div>` : '');
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}
