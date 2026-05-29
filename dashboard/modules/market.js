// ── 손익 예측 ────────────────────────────────────────────────────────────────
async function loadProfitForecast() {
  if (!_token) return;
  const sel    = $('profit-farm-sel');
  const farmId = (sel ? sel.value : '') || _defaultFarm();
  const body   = $('profit-body');
  if (!farmId) return;

  body.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/admin/farms/${farmId}/profit-forecast`);
    const fmt = n => n != null && !isNaN(n) ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtKg = n => n != null ? Number(n).toFixed(1) : '—';
    const profit = d.profit_krw ?? ((d.revenue_krw ?? 0) - (d.cost_krw ?? 0));
    const profitClass = profit >= 0 ? 'positive' : 'negative';
    const sign = profit >= 0 ? '+' : '';
    const marginPct = d.profit_margin_pct != null ? d.profit_margin_pct.toFixed(1) : '—';
    body.innerHTML = `
      <div class="profit-grid">
        <div class="profit-kpi"><div class="pk-label">예상 수확량</div>
          <div class="pk-val">${fmtKg(d.yield_kg_forecast)} <span style="font-size:11px;color:var(--muted)">kg</span></div></div>
        <div class="profit-kpi"><div class="pk-label">시세 (${d.price_source === 'kamis_live' ? '🟢실시간' : '📊평균'})</div>
          <div class="pk-val">${fmt(d.price_krw_kg)} <span style="font-size:11px;color:var(--muted)">원/kg</span></div></div>
        <div class="profit-kpi"><div class="pk-label">재배 면적</div>
          <div class="pk-val">${fmt(d.plant_area_m2)} <span style="font-size:11px;color:var(--muted)">m²</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 매출</div>
          <div class="pk-val">${fmt(d.revenue_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 비용</div>
          <div class="pk-val">${fmt(d.cost_krw)} <span style="font-size:11px;color:var(--muted)">원</span></div></div>
        <div class="profit-kpi"><div class="pk-label">예상 순이익</div>
          <div class="pk-val ${profitClass}">${sign}${fmt(profit)} <span style="font-size:11px">원</span></div></div>
      </div>
      <div class="profit-note">${_esc(d.crop_ko || '')} · ${d.season_months || '—'}개월 시즌 · 이익률 ${marginPct}% · ${_esc(d.note || '')}</div>
    `;
  } catch(e) {
    body.innerHTML = `<div style="color:var(--muted);font-size:12px;padding:8px">조회 실패: ${_esc(e.message)}</div>`;
  }
}

// ── 에너지/비용: 비용 내역 조회 ──────────────────────────────────────────────
async function loadCostBreakdown() {
  const farmId = $('cost-farm-sel')?.value || _defaultFarm();
  const el = $('cost-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/costs`);
    const fmt = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const items = d.items || d.breakdown || [];
    const total = d.total_cost_krw ?? d.total_krw ?? d.total ?? 0;
    const perM2 = d.cost_per_m2;
    const rows = items.map(it => {
      const label = it.label_ko || it.label || it.name || it.item || '—';
      const pct   = it.pct_of_total != null ? Math.round(it.pct_of_total * 100) : null;
      const manualBadge = it.is_manual ? ' <span style="font-size:9px;color:var(--accent);border:1px solid var(--accent);border-radius:3px;padding:0 3px">실제입력</span>' : '';
      const barHtml = pct != null
        ? `<div style="height:3px;background:var(--border);border-radius:2px;margin-top:3px">
            <div style="height:3px;background:var(--accent);border-radius:2px;width:${pct}%"></div></div>` : '';
      return `<div class="cost-row" style="flex-direction:column;align-items:stretch;gap:2px">
        <div style="display:flex;justify-content:space-between">
          <span>${_esc(label)}${manualBadge}</span>
          <span style="font-weight:600">${fmt(it.amount_krw??it.amount)} 원${pct!=null?` <span style="font-size:10px;color:var(--muted)">(${pct}%)</span>`:''}</span>
        </div>
        ${it.unit_label ? `<div style="font-size:10px;color:var(--muted)">${_esc(it.unit_label)}</div>` : ''}
        ${barHtml}
      </div>`;
    }).join('');
    const hasManualBadge = d.has_manual_input
      ? '<span style="font-size:10px;color:var(--accent);border:1px solid var(--accent);border-radius:4px;padding:1px 5px;margin-left:6px">일부 실제입력</span>' : '';
    el.innerHTML = `
      <div class="cost-section">
        <div class="cost-section-title">월간 비용 분석 ${hasManualBadge}</div>
        ${rows}
        <div class="cost-row" style="margin-top:6px;border-top:1px solid var(--border);padding-top:8px">
          <span style="font-weight:600">월간 합계</span>
          <span class="cost-total">${fmt(total)} 원</span>
        </div>
        ${perM2 != null ? `<div style="font-size:11px;color:var(--muted);text-align:right;margin-top:4px">㎡당 ${Number(perM2).toFixed(1)}원</div>` : ''}
      </div>
      ${d.electricity_kwh_month != null ? `<div style="font-size:10px;color:var(--muted);margin-top:4px">전기 ${Math.round(d.electricity_kwh_month).toLocaleString('ko-KR')} kWh / 용수 ${Math.round(d.water_m3_month||0).toLocaleString('ko-KR')} m³</div>` : ''}`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 에너지/비용: 수동 비용 입력 / 삭제 ──────────────────────────────────────
function loadCostManualForm() {
  if (!_token) return;
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) return;
  apiFetch(`/api/farms/${farmId}/costs`).then(d => {
    const mi = d.manual_input || {};
    const set = (id, key) => { const el=$(id); if(el && mi[key]!=null) el.value=mi[key]; else if(el) el.value=''; };
    set('mc-elec-kwh', 'electricity_kwh_month');
    set('mc-elec-rate','electricity_rate');
    set('mc-water-m3', 'water_m3_month');
    set('mc-water-rate','water_rate');
    set('mc-heat-kwh', 'heating_kwh_month');
    set('mc-heat-rate','heating_rate');
    set('mc-labor-hrs','labor_hours_month');
    set('mc-labor-rate','labor_rate');
    set('mc-nutr',     'nutrients_krw_month');
    set('mc-pest',     'pesticides_krw_month');
  }).catch(e => console.warn('[cost-manual-form] 기존 입력값 로드 실패:', e.message));
}

async function submitManualCost() {
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) { _setResult('cost-manual-result', 'warn', '농장을 선택하세요'); return; }
  const f = (id) => { const v = $(id)?.value; return v !== '' && v != null ? parseFloat(v) : undefined; };
  const body = {};
  const fields = [
    ['mc-elec-kwh', 'electricity_kwh_month'],
    ['mc-elec-rate','electricity_rate'],
    ['mc-water-m3', 'water_m3_month'],
    ['mc-water-rate','water_rate'],
    ['mc-heat-kwh', 'heating_kwh_month'],
    ['mc-heat-rate','heating_rate'],
    ['mc-labor-hrs','labor_hours_month'],
    ['mc-labor-rate','labor_rate'],
    ['mc-nutr',     'nutrients_krw_month'],
    ['mc-pest',     'pesticides_krw_month'],
  ];
  fields.forEach(([id, key]) => { const v = f(id); if (v !== undefined && !isNaN(v)) body[key] = v; });
  if (!Object.keys(body).length) { _setResult('cost-manual-result', 'warn', '하나 이상의 비용을 입력하세요'); return; }
  try {
    const r = await apiFetch(`/api/farms/${farmId}/costs/manual`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    _setResult('cost-manual-result', 'ok', r.message_ko || '저장 완료');
    if ($('cost-farm-sel')?.value === farmId) loadCostBreakdown();
  } catch(e) {
    _setResult('cost-manual-result', 'err', '저장 실패: ' + e.message);
  }
}

function deleteManualCost() {
  const farmId = $('cost-manual-farm')?.value;
  if (!farmId) { _setResult('cost-manual-result', 'warn', '농장을 선택하세요'); return; }
  BottomSheet.open(
    '수동 비용 항목 삭제',
    `<p style="line-height:1.7;font-size:13px"><b>${_esc(farmId)}</b> 농장의 수동 비용 항목을 <b style="color:var(--red)">모두 삭제</b>합니다.<br>이 작업은 되돌릴 수 없습니다.</p>`,
    '삭제 확인',
    async () => {
      try {
        await apiFetch(`/api/farms/${farmId}/costs/manual`, { method: 'DELETE' });
        _setResult('cost-manual-result', 'ok', '삭제 완료');
        loadCostBreakdown();
      } catch(e) { _setResult('cost-manual-result', 'err', '삭제 실패: ' + e.message); }
    }
  );
}

// ── ERP 실시간 원가·마진 ──────────────────────────────────────────────────────
async function loadERPRealtime() {
  const farmId = $('erp-farm-sel')?.value || _defaultFarm();
  const el = $('erp-realtime-body');
  if (!el) return;
  if (!farmId) {
    el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하면 실시간 원가·마진이 표시됩니다']]);
    return;
  }
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const fmt  = n => n != null ? Math.round(n).toLocaleString('ko-KR') : '—';
    const fmtF = n => n != null ? Number(n).toFixed(1) : '—';
    const cb   = d.cost_breakdown || {};
    const ht   = d.harvest_timing || {};
    const incomeColor = (d.income_rate_pct ?? 0) >= 40 ? 'var(--green)' : (d.income_rate_pct ?? 0) >= 20 ? 'var(--yellow)' : 'var(--red)';
    const marginColor = (d.margin_per_kg ?? 0) > 0 ? 'var(--green)' : 'var(--red)';
    const adviceColor = (ht.diff ?? 0) > 300 ? 'var(--green)' : (ht.diff ?? 0) < -200 ? 'var(--yellow)' : 'var(--muted)';

    const beKg = d.breakeven_kg ?? 0;
    const _DEFAULT_YIELD_KG_M2_MONTH = 3.0;
    const estKg = d.yield_kg_month ?? ((d.area_m2 ?? 0) * _DEFAULT_YIELD_KG_M2_MONTH);
    const bePct = beKg > 0 && estKg > 0 ? Math.min(100, Math.round(estKg / beKg * 100)) : 0;
    const barColor = bePct >= 100 ? 'var(--green)' : bePct >= 70 ? 'var(--accent)' : 'var(--orange)';
    const barHtml = `<div style="height:5px;background:var(--border);border-radius:3px;margin-top:4px;overflow:hidden"><div style="width:${bePct}%;height:100%;background:${barColor};border-radius:3px;transition:width .4s ease"></div></div>`;

    const led = d.led_spectrum || {};
    const stageHtml = d.growth_stage
      ? `<span style="font-size:11px;color:var(--accent);border:1px solid var(--accent);border-radius:4px;padding:2px 8px;margin-left:8px">${_esc(d.growth_stage)}</span>`
      : '';

    const nullReasons = [];
    if (d.market_price_per_kg == null || d.market_price_per_kg === 0)
      nullReasons.push(['KAMIS 도매가', 'KAMIS API 키 미설정 — 작목별 연평균 기본가 사용 중']);
    if (d.cost_per_kg == null || d.cost_per_kg === 0)
      nullReasons.push(['kg당 원가', '수확량이 0이거나 작목별 기본 원가 미적용 상태']);
    if (!d.growth_stage)
      nullReasons.push(['작기단계', '정식일 미등록 — 농가 메타 설정에서 정식월을 입력하세요']);

    el.innerHTML = `
      <div class="form-3col" style="gap:10px;margin-bottom:12px">
        <div class="profit-kpi">
          <div class="pk-label">kg당 원가</div>
          <div class="pk-val">${fmt(d.cost_per_kg)} <span style="font-size:11px">원</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">KAMIS 도매가</div>
          <div class="pk-val">${fmt(d.market_price_per_kg)} <span style="font-size:11px">원</span></div>
          ${d.market_price_per_kg > 0 ? '' : '<div class="data-ok-hint">기본 평균가 적용 중</div>'}
        </div>
        <div class="profit-kpi">
          <div class="pk-label">kg당 마진</div>
          <div class="pk-val" style="color:${marginColor}">${fmt(d.margin_per_kg)} <span style="font-size:11px">원</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">소득률</div>
          <div class="pk-val" style="color:${incomeColor}">${fmtF(d.income_rate_pct)}<span style="font-size:13px">%</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">손익분기점</div>
          <div class="pk-val">${fmt(beKg)} <span style="font-size:11px">kg</span></div>
        </div>
        <div class="profit-kpi">
          <div class="pk-label">달성률 추정</div>
          <div class="pk-val" style="font-size:14px">${bePct}%</div>
          ${barHtml}
        </div>
      </div>
      <div style="border-top:1px solid var(--border);padding-top:10px;margin-bottom:8px">
        <div style="font-size:11px;color:var(--muted);margin-bottom:6px">원가 구성 (원/m²/월)</div>
        <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:12px">
          <span>⚡ 에너지 <strong>${fmt(cb.energy_per_m2)}</strong></span>
          <span>🌿 양액·자재 <strong>${fmt(cb.nutrient_per_m2)}</strong></span>
          <span>👷 노동 <strong>${fmt(cb.labor_per_m2)}</strong></span>
          <span>🌱 종묘 <strong>${fmt(cb.seed_per_m2)}</strong></span>
          <span style="color:var(--accent)">합계 <strong>${fmt(cb.total_per_m2)}</strong></span>
        </div>
      </div>
      <div style="background:var(--green-soft);border-radius:8px;padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="font-size:13px">💡 출하 타이밍</span>
        ${stageHtml}
        <span style="color:${adviceColor};font-weight:600;font-size:13px">${_esc(ht.advice || '—')}</span>
        <span style="font-size:11px;color:var(--muted);margin-left:auto">오늘 ${fmt(ht.today_margin)}원 → 내일 ${fmt(ht.tomorrow_margin_est)}원</span>
      </div>
      ${led.ratio_str ? `<div style="margin-top:8px;font-size:11px;color:var(--muted)">💡 LED 권장 (${_esc(d.growth_stage)}): <strong style="color:var(--accent)">${_esc(led.ratio_str)}</strong> — ${_esc(led.effect || '')}</div>` : ''}
      ${_nullReasonHtml(nullReasons)}
    `;
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, 'ERP 원가·마진 조회 실패');
  }
}

// ── 생산/유통: KAMIS 가격 현황 ───────────────────────────────────────────────
async function loadMarketPrices() {
  const el = $('market-prices-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch('/api/admin/prices/latest');
    const prices = d.prices || d.data || (Array.isArray(d) ? d : []);
    if (!prices.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:16px">가격 데이터 없음</div>'; return; }
    const rows = prices.map(p => {
      const chg = p.change_pct ?? p.change_rate ?? null;
      const chgHtml = chg != null
        ? `<span class="${chg>=0?'price-up':'price-down'}">${chg>=0?'+':''}${Number(chg).toFixed(1)}%</span>` : '—';
      const priceVal = p.price_krw_kg ?? p.price_krw ?? p.price;
      const dateVal  = p.regday || p.base_date || p.date || p.updated_at;
      return `<tr>
        <td>${_esc(p.crop_ko || p.crop || '—')}</td>
        <td>${priceVal != null ? Math.round(priceVal).toLocaleString('ko-KR') : '—'} 원/kg</td>
        <td>${chgHtml}</td>
        <td style="color:var(--muted)">${dateVal ? dateVal.substring(0,10) : '—'}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="table-scroll-wrap"><table class="price-hist-table">
      <thead><tr><th>작목</th><th>시세</th><th>전일비</th><th>기준일</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
    const poolPrices = prices.filter(p => p.price_krw_kg != null);
    if (poolPrices.length) {
      const avgP = Math.round(poolPrices.reduce((s,p)=>s+(p.price_krw_kg||0),0)/poolPrices.length);
      setText('pool-avg-price', avgP.toLocaleString('ko-KR')+'원/kg');
      setText('pool-volume-7d', '—');
      setText('pool-quality-rate', '특·상 —%');
      setText('pool-farm-count', _farmsData.length || '—');
      setText('pool-farm-approved', '등록 '+(_farmsData.length||'—')+'개');
      const curAvg  = poolPrices.reduce((s,p)=>s+(p.price_krw_kg||0),0) / poolPrices.length;
      const prevAvg = poolPrices.reduce((s,p)=>s+(p.prev_price_krw_kg || p.price_krw_kg || 0),0) / poolPrices.length;
      const marginPct = prevAvg > 0 ? ((curAvg - prevAvg) / prevAvg * 100) : null;
      setText('pool-margin-vs-ind', marginPct != null ? (marginPct >= 0 ? '+' : '') + marginPct.toFixed(1) + '%' : '—');
      const priceDiff = Math.round(curAvg - prevAvg);
      setText('pool-price-change', prevAvg > 0 ? (priceDiff >= 0 ? '+' : '') + priceDiff.toLocaleString('ko-KR') + '원' : '전주 대비');
      const tbEl = $('pool-table-body');
      if (tbEl && tbEl.innerHTML.includes('갱신 중')) {
        tbEl.innerHTML = poolPrices.slice(0,5).map(p=>`
          <tr>
            <td>${_esc(p.crop_ko||'—')}</td>
            <td style="text-align:center;color:var(--muted)">금주</td>
            <td style="text-align:right">${p.supply_volume != null ? Math.round(p.supply_volume).toLocaleString('ko-KR') + 'kg' : '—'}</td>
            <td style="text-align:center"><span class="pill-tag">${p.change_pct != null ? (p.change_pct >= 0 ? '모집중' : '완료') : '—'}</span></td>
          </tr>`).join('');
      }
    }
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadPriceHistory() {
  const cropKo = $('price-hist-crop')?.value;
  const el = $('price-hist-body');
  if (!el) return;
  if (!cropKo) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px 0;text-align:center">작목을 선택하세요</div>'; return; }

  const farmId = _myFarmId || _farmsData[0]?.farm_id;
  if (!farmId) { el.innerHTML = '<div style="color:var(--muted);font-size:12px">농장 정보 로딩 중…</div>'; return; }

  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/market/price-history?days=30&crop_ko=${encodeURIComponent(cropKo)}`);
    const items = d.history || [];
    if (!items.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:12px">이력 없음</div>'; return; }

    const stats = d.stats || {};
    const trendIcon = {up:'↑', down:'↓', flat:'→'}[d.trend] || '→';
    const trendColor= {up:'var(--red)', down:'var(--accent)', flat:'var(--muted)'}[d.trend] || 'var(--muted)';
    const src = d.source === 'kamis_cache' ? 'KAMIS 실시간' : d.source === 'rda_static_estimated' ? '통계 추정' : '통계 기반';

    const prices = items.map(i => i.price_krw_kg);
    const minP = Math.min(...prices), maxP = Math.max(...prices);
    const W = 340, H = 60, pad = 4;
    const toX = i => prices.length > 1 ? pad + (i / (prices.length - 1)) * (W - 2*pad) : W / 2;
    const toY = p => H - pad - ((p - minP) / (maxP - minP + 1)) * (H - 2*pad);
    const pts = prices.map((p, i) => `${toX(i).toFixed(1)},${toY(p).toFixed(1)}`).join(' ');
    const sparkline = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:60px;display:block;margin:8px 0">
      <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round"/>
      <circle cx="${toX(prices.length-1)}" cy="${toY(prices[prices.length-1])}" r="3" fill="var(--accent)"/>
    </svg>`;

    const rows = items.slice(-14).reverse().map((it, i, arr) => {
      const prev = arr[i+1];
      const chg  = prev ? ((it.price_krw_kg - prev.price_krw_kg) / prev.price_krw_kg * 100) : null;
      const chgHtml = chg != null
        ? `<span class="${chg>=0?'price-up':'price-down'}">${chg>=0?'+':''}${chg.toFixed(1)}%</span>` : '—';
      return `<tr>
        <td style="color:var(--muted)">${_esc(it.date)}</td>
        <td style="text-align:right;font-weight:600">${it.price_krw_kg.toLocaleString('ko-KR')}원</td>
        <td style="text-align:right">${chgHtml}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <span style="font-size:12px;font-weight:700">${cropKo} 도매가 추세</span>
        <span style="font-size:11px;color:${trendColor};font-weight:700">${trendIcon} ${d.trend === 'up' ? '상승세' : d.trend === 'down' ? '하락세' : '보합세'}</span>
      </div>
      ${sparkline}
      <div class="form-4col" style="gap:6px;margin-bottom:10px">
        ${[['최신가',stats.latest],['평균',stats.avg],['최고',stats.max],['최저',stats.min]].map(([l,v])=>
          `<div style="background:var(--card-soft);border:1px solid var(--border);border-radius:6px;padding:6px 8px;text-align:center">
            <div style="font-size:9px;color:var(--muted)">${l}</div>
            <div style="font-size:13px;font-weight:700;color:var(--text)">${v!=null?v.toLocaleString('ko-KR'):'—'}</div>
          </div>`).join('')}
      </div>
      <div class="table-scroll-wrap"><table class="price-hist-table">
        <thead><tr><th>날짜</th><th style="text-align:right">시세(원/kg)</th><th style="text-align:right">전일비</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div style="font-size:10px;color:var(--muted);margin-top:6px;text-align:right">출처: ${src}</div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadMarketHarvest() {
  const farmId = $('market-harvest-farm')?.value || _defaultFarm();
  const el = $('market-harvest-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const [harv, rev] = await Promise.allSettled([
      apiFetch(`/api/farms/${farmId}/harvest`),
      apiFetch(`/api/farms/${farmId}/revenue`),
    ]);
    const h = harv.status==='fulfilled' ? harv.value : null;
    const r = rev.status ==='fulfilled' ? rev.value  : null;
    const fmtF = n => n!=null ? Number(n).toFixed(1) : '—';
    const fmt  = n => n!=null ? Math.round(n).toLocaleString('ko-KR') : '—';
    el.innerHTML = `
      <div class="advisor-opt-grid">
        <div class="advisor-opt-item"><div class="ao-var">예상 수확량</div>
          <div class="ao-val">${fmtF(h?.yield_kg_forecast)} kg</div>
          <div class="ao-range">잔여 ${h?.days_to_harvest??'—'}일</div></div>
        <div class="advisor-opt-item"><div class="ao-var">예상 매출</div>
          <div class="ao-val" style="font-size:13px">${fmt(r?.revenue_krw)} 원</div>
          <div class="ao-range">${r?.price_krw_kg!=null?Math.round(r.price_krw_kg).toLocaleString('ko-KR')+'원/kg':''}</div></div>
        <div class="advisor-opt-item"><div class="ao-var">예상 순이익</div>
          <div class="ao-val ${(r?.revenue_krw??0)-(r?.cost_krw??0)>=0?'positive':'negative'}" style="font-size:13px">
            ${fmt((r?.revenue_krw??0)-(r?.cost_krw??0))} 원</div>
          <div class="ao-range">${r?.price_source==='kamis_live'?'🟢실시간 시세':'📊 평균 시세'}</div></div>
      </div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 도매 시장 기준가 조회 ─────────────────────────────────────────────────────
async function loadWholesaleMarket(farmId) {
  const el = $('wholesale-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const fid = farmId || _myFarmId || (_farmsData[0]?.farm_id);
    if (!fid) { el.innerHTML = _nullReasonHtml([['농장 미선택', '농장을 선택하면 도매가격 기준이 표시됩니다']]); return; }
    const d = await apiFetch(`/api/farms/${fid}/market/wholesale`);
    const price = d.price_krw_kg ? `${Number(d.price_krw_kg).toLocaleString()}원/kg` : '—';
    const faoRef = d.fao_ref_price_krw_kg ? `FAO 기준: ${Number(d.fao_ref_price_krw_kg).toLocaleString()}원/kg` : '';
    const corr = d.m3_correction_factor ? `보정계수 ×${d.m3_correction_factor}` : '';
    const bounds = d.yield_bounds;
    const boundsHtml = bounds ? `
      <div style="background:var(--card-soft);border:1px solid var(--border);border-radius:6px;padding:8px;margin-top:8px;font-size:11px">
        <div style="font-weight:700;color:var(--muted);margin-bottom:4px">📊 수확량 합리적 범위 (M2 클리핑)</div>
        <div>${_esc(d.crop)}: <span style="color:var(--green)">${bounds.lower_kg_m2}~${bounds.upper_kg_m2} kg/m²/시즌</span></div>
        <div style="color:var(--muted);font-size:10px">${_esc(bounds.reference)} · ${_esc(d.yield_clipping_note||'')}</div>
      </div>` : '';
    const srcBadges = (d.source_chain||[]).map(s=>`<span class="badge info" style="font-size:9px">${_esc(s)}</span>`).join(' ');
    el.innerHTML = `
      <div style="font-size:20px;font-weight:700;color:var(--green)">${price}</div>
      <div style="font-size:11px;color:var(--muted);margin:4px 0">${faoRef}${faoRef&&corr?' · ':''}${corr}</div>
      ${boundsHtml}
      <div style="margin-top:8px">${srcBadges}</div>`;
  } catch(e) {
    el.innerHTML = `<span style="color:var(--red);font-size:12px">조회 실패: ${_esc(e.message)}</span>`;
  }
}
