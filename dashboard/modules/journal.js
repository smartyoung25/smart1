// ══════════════════════════════════════════════════════════════════════════
//  journal.js — 생육·수확·환경 이력 타임라인
//  의존: core.js (apiFetch, $, _token, _defaultFarm, _myFarmId)
// ══════════════════════════════════════════════════════════════════════════

// ── 날짜 포맷 헬퍼 ─────────────────────────────────────────────────────────
function _jFmtDate(s) {
  if (!s) return '—';
  return String(s).substring(0, 10);
}

function _jFmtNum(v, unit, digits) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return String(v);
  return (digits != null ? n.toFixed(digits) : n) + (unit || '');
}

// ── 생육 이력 렌더 ─────────────────────────────────────────────────────────
function _renderGrowthTimeline(records, total) {
  const badge = total > records.length
    ? `<span style="color:var(--muted);font-size:11px">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span style="color:var(--muted);font-size:11px">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const bg = i % 2 === 1 ? 'background:var(--card-soft)' : '';
    const dateStr  = _jFmtDate(r.recorded_date || r.recorded_at);
    const crop     = r.crop_ko || '—';
    const ph       = _jFmtNum(r.plant_height_cm,  'cm', 1);
    const lc       = _jFmtNum(r.leaf_count,        '개');
    const fc       = _jFmtNum(r.fruit_count,       '개');
    const sd       = _jFmtNum(r.stem_diameter_mm,  'mm', 1);
    const temp     = _jFmtNum(r.temp_internal,     '°C', 1);
    const vpd      = _jFmtNum(r.vpd_kpa,           'kPa', 2);
    const src      = r.source || 'api';
    return `<tr style="${bg}">
      <td style="padding:5px 8px;white-space:nowrap;color:var(--accent);font-size:12px">${dateStr}</td>
      <td style="padding:5px 8px;font-size:12px">${crop}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${ph}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${lc}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${fc}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${sd}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${temp}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${vpd}</td>
      <td style="padding:5px 8px;color:var(--muted);font-size:11px">${src}</td>
    </tr>`;
  }).join('');

  return `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span style="font-size:12px;color:var(--fg);font-weight:600">📋 생육 측정 이력</span>${badge}
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;min-width:560px">
      <thead>
        <tr style="background:var(--card-soft);color:var(--muted);font-size:11px">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">측정일</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">작물</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">초장</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">엽수</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">착과수</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">경경</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">온도</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">VPD</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">출처</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 수확 이력 렌더 ─────────────────────────────────────────────────────────
function _renderHarvestTimeline(records, total) {
  const badge = total > records.length
    ? `<span style="color:var(--muted);font-size:11px">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span style="color:var(--muted);font-size:11px">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const bg        = i % 2 === 1 ? 'background:var(--card-soft)' : '';
    const dateStr   = _jFmtDate(r.harvest_date || r.recorded_at);
    const crop      = r.crop_ko || '—';
    const yld       = _jFmtNum(r.yield_kg_m2,   'kg/㎡', 2);
    const totalKg   = _jFmtNum(r.total_yield_kg, 'kg', 1);
    const area      = _jFmtNum(r.area_m2,        '㎡', 0);
    const days      = r.growing_days != null ? `${r.growing_days}일` : '—';
    const planting  = _jFmtDate(r.planting_date);
    const src       = r.source || 'api';
    return `<tr style="${bg}">
      <td style="padding:5px 8px;white-space:nowrap;color:var(--accent);font-size:12px">${dateStr}</td>
      <td style="padding:5px 8px;font-size:12px">${crop}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px;font-weight:600;color:var(--green)">${yld}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${totalKg}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${area}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${days}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px;color:var(--muted)">${planting}</td>
      <td style="padding:5px 8px;color:var(--muted);font-size:11px">${src}</td>
    </tr>`;
  }).join('');

  return `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span style="font-size:12px;color:var(--fg);font-weight:600">📦 수확량 기록 이력</span>${badge}
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;min-width:520px">
      <thead>
        <tr style="background:var(--card-soft);color:var(--muted);font-size:11px">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">수확일</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">작물</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">수량(kg/㎡)</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">총수확(kg)</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">면적(㎡)</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">재배일수</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">정식일</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">출처</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 환경 수동 입력 이력 렌더 ───────────────────────────────────────────────
function _renderEnvTimeline(records, total) {
  const badge = total > records.length
    ? `<span style="color:var(--muted);font-size:11px">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span style="color:var(--muted);font-size:11px">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const bg  = i % 2 === 1 ? 'background:var(--card-soft)' : '';
    const ts  = r.recorded_at ? String(r.recorded_at).substring(0, 16).replace('T', ' ') : '—';
    const p   = r.payload || {};
    const temp = _jFmtNum(p.temp_internal,  '°C', 1);
    const humi = _jFmtNum(p.humidity_int,   '%',  0);
    const co2  = _jFmtNum(p.co2_ppm,        'ppm',0);
    const ec   = _jFmtNum(p.ec_dsm,         'dS/m',1);
    const ph   = _jFmtNum(p.ph,             '',   1);
    const vpd  = _jFmtNum(p.vpd_kpa,        'kPa',2);
    return `<tr style="${bg}">
      <td style="padding:5px 8px;white-space:nowrap;color:var(--accent);font-size:12px">${ts}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${temp}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${humi}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${co2}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${ec}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${ph}</td>
      <td style="padding:5px 8px;text-align:right;font-size:12px">${vpd}</td>
    </tr>`;
  }).join('');

  return `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <span style="font-size:12px;color:var(--fg);font-weight:600">📋 환경값 수동 입력 이력</span>${badge}
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;min-width:420px">
      <thead>
        <tr style="background:var(--card-soft);color:var(--muted);font-size:11px">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">입력 시각</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">온도</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">습도</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">CO₂</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">EC</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">pH</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">VPD</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 공개 함수 ──────────────────────────────────────────────────────────────

async function loadGrowthHistory(farmId) {
  farmId = farmId || _defaultFarm();
  const el = $('growth-hist-body');
  if (!el || !farmId || !_token) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await apiFetch(`/api/data/growth?farm_id=${encodeURIComponent(farmId)}&limit=30`);
    if (!data.records || !data.records.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🌱</div>생육 기록이 없습니다<div class="empty-state-sub">생육 측정 데이터를 등록하면 이력이 표시됩니다</div></div>';
      return;
    }
    el.innerHTML = _renderGrowthTimeline(data.records, data.total);
  } catch (e) {
    el.innerHTML = `<div class="data-reason-box"><span style="font-size:13px;color:var(--muted)">생육 이력 로드 실패: ${e.message || '서버 오류'}</span></div>`;
  }
}

async function loadHarvestHistory(farmId) {
  farmId = farmId || _defaultFarm();
  const el = $('harvest-hist-body');
  if (!el || !farmId || !_token) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await apiFetch(`/api/data/harvest?farm_id=${encodeURIComponent(farmId)}&limit=30`);
    if (!data.records || !data.records.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📦</div>수확 기록이 없습니다<div class="empty-state-sub">수확 데이터를 등록하면 이력이 표시됩니다</div></div>';
      return;
    }
    el.innerHTML = _renderHarvestTimeline(data.records, data.total);
  } catch (e) {
    el.innerHTML = `<div class="data-reason-box"><span style="font-size:13px;color:var(--muted)">수확 이력 로드 실패: ${e.message || '서버 오류'}</span></div>`;
  }
}

async function loadEnvHistory(farmId) {
  farmId = farmId || _defaultFarm();
  const el = $('env-hist-body');
  if (!el || !farmId || !_token) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await apiFetch(`/api/farms/${encodeURIComponent(farmId)}/journal/env?limit=20`);
    if (!data.records || !data.records.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📋</div>환경값 수동 입력 이력이 없습니다<div class="empty-state-sub">위의 폼으로 환경값을 입력하면 이력이 표시됩니다</div></div>';
      return;
    }
    el.innerHTML = _renderEnvTimeline(data.records, data.total);
  } catch (e) {
    el.innerHTML = `<div class="data-reason-box"><span style="font-size:13px;color:var(--muted)">환경 이력 조회 실패: ${e.message || '서버 오류'}</span></div>`;
  }
}
