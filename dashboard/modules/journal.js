// ══════════════════════════════════════════════════════════════════════════
//  journal.js — 생육·수확·환경 이력 타임라인 + 등록 폼
//  의존: core.js (apiFetch, $, _token, _defaultFarm, _myFarmId)
// ══════════════════════════════════════════════════════════════════════════

// ── 폼 피드백 헬퍼 ────────────────────────────────────────────────────────
function _setFeedback(elId, type, msg) {
  const el = $(elId);
  if (!el) return;
  el.className = `form-feedback ${type}`;
  el.textContent = msg;
  if (type === 'ok') setTimeout(() => { el.className = 'form-feedback'; }, 4000);
}

function _setLoading(btn, loading) {
  if (!btn) return;
  btn.disabled = loading;
  if (loading) {
    btn.classList.add('loading');
  } else {
    btn.classList.remove('loading');
  }
}

// ── 생육 측정 등록 ────────────────────────────────────────────────────────
async function submitGrowthRecord() {
  const btn = document.querySelector('[onclick="submitGrowthRecord()"]');
  const farmId = $('gr-farm')?.value;
  const dateVal = $('gr-date')?.value;

  if (!farmId) { _setFeedback('gr-result', 'err', '농장을 선택해 주세요.'); return; }
  if (!dateVal) { _setFeedback('gr-result', 'err', '측정일을 입력해 주세요.'); return; }

  // 작목 — farm 메타에서 가져오거나 선택값 사용
  const farmMeta = (_farmsData || []).find(f => f.farm_id === farmId);
  const cropKo = $('gr-crop')?.value || farmMeta?.crop_ko || '방울토마토';

  const body = {
    farm_id:    farmId,
    crop_ko:    cropKo,
    recorded_date: dateVal,
    source:     'manual_ui',
    plant_height_cm:  _numVal('gr-height'),
    leaf_count:       _numVal('gr-leaves'),
    fruit_count:      _numVal('gr-fruits'),
    stem_diameter_mm: _numVal('gr-stem'),
    temp_internal:    _numVal('gr-temp'),
    humidity_int:     _numVal('gr-humi'),
    co2_ppm:          _numVal('gr-co2'),
    ec_dsm:           _numVal('gr-ec'),
  };
  // null 제거
  Object.keys(body).forEach(k => { if (body[k] === null) delete body[k]; });

  _setLoading(btn, true);
  try {
    const res = await apiFetch('/api/data/growth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    _setFeedback('gr-result', 'ok', `✅ ${res.message_ko || '생육 측정 저장 완료'}`);
    // 이력 새로고침
    setTimeout(() => loadGrowthHistory(farmId), 600);
  } catch (e) {
    _setFeedback('gr-result', 'err', `저장 실패: ${e.message || '서버 오류'}`);
  } finally {
    _setLoading(btn, false);
  }
}

function _numVal(id) {
  const v = $(id)?.value;
  if (v === '' || v == null) return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : n;
}

// ── 수확량 등록 ────────────────────────────────────────────────────────────
async function submitHarvestRecord() {
  const btn = document.querySelector('[onclick="submitHarvestRecord()"]');
  const farmId = $('hv-farm')?.value;
  const dateVal = $('hv-date')?.value;
  const yieldVal = _numVal('hv-yield');

  if (!farmId) { _setFeedback('hv-result', 'err', '농장을 선택해 주세요.'); return; }
  if (!dateVal) { _setFeedback('hv-result', 'err', '수확일을 입력해 주세요.'); return; }
  if (!yieldVal || yieldVal <= 0) { _setFeedback('hv-result', 'err', '단위수확량(kg/m²)을 올바르게 입력해 주세요.'); return; }

  const farmMeta = (_farmsData || []).find(f => f.farm_id === farmId);
  const cropKo = $('hv-crop')?.value || farmMeta?.crop_ko || '방울토마토';

  const body = {
    farm_id:        farmId,
    crop_ko:        cropKo,
    harvest_date:   dateVal,
    source:         'manual_ui',
    yield_kg_m2:    yieldVal,
    area_m2:        _numVal('hv-area'),
    planting_date:  $('hv-plant-date')?.value || undefined,
    season_avg_temp:     _numVal('hv-avg-temp'),
    season_avg_humidity: _numVal('hv-avg-humi'),
  };
  if (!body.planting_date) delete body.planting_date;
  Object.keys(body).forEach(k => { if (body[k] === null || body[k] === undefined) delete body[k]; });

  // 미리보기 숨기기
  const pv = $('hv-preview');
  if (pv) pv.classList.remove('visible');

  _setLoading(btn, true);
  try {
    const res = await apiFetch('/api/data/harvest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    _setFeedback('hv-result', 'ok', `✅ ${res.message_ko || '수확량 저장 완료'}`);
    // 재학습 트리거 알림
    if (res.retrain_triggered) {
      setTimeout(() => _setFeedback('hv-result', 'warn', `🔄 ${res.retrain_message_ko || '재학습이 예약되었습니다'}`), 2000);
    }
    // 이력 새로고침
    setTimeout(() => loadHarvestHistory(farmId), 600);
  } catch (e) {
    _setFeedback('hv-result', 'err', `저장 실패: ${e.message || '서버 오류'}`);
  } finally {
    _setLoading(btn, false);
  }
}

// 수확 입력값 미리보기 (실시간)
function _updateHarvestPreview() {
  const yield_ = _numVal('hv-yield');
  const area   = _numVal('hv-area');
  const pv     = $('hv-preview');
  const pvb    = $('hv-preview-body');
  if (!pv || !pvb || !yield_) { if (pv) pv.classList.remove('visible'); return; }
  const total = area ? (yield_ * area).toFixed(1) : null;
  pvb.innerHTML = `단위수확량 <b style="color:var(--green)">${yield_} kg/m²</b>` +
    (area ? ` × 면적 ${area}m² = <b style="color:var(--accent)">${total} kg</b>` : '') +
    (total ? ` | 예상 매출 ≈ <b>${(parseFloat(total) * 3500).toLocaleString()}원</b> (평균 3,500원/kg)` : '');
  pv.classList.add('visible');
}

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
    ? `<span class="rec-count">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span class="rec-count">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const trCls = i % 2 === 1 ? ' class="tbl-alt"' : '';
    const dateStr  = _jFmtDate(r.recorded_date || r.recorded_at);
    const crop     = r.crop_ko || '—';
    const ph       = _jFmtNum(r.plant_height_cm,  'cm', 1);
    const lc       = _jFmtNum(r.leaf_count,        '개');
    const fc       = _jFmtNum(r.fruit_count,       '개');
    const sd       = _jFmtNum(r.stem_diameter_mm,  'mm', 1);
    const temp     = _jFmtNum(r.temp_internal,     '°C', 1);
    const vpd      = _jFmtNum(r.vpd_kpa,           'kPa', 2);
    const src      = r.source || 'api';
    return `<tr${trCls}>
      <td class="tbl-td accent">${dateStr}</td>
      <td class="tbl-td">${crop}</td>
      <td class="tbl-td r">${ph}</td>
      <td class="tbl-td r">${lc}</td>
      <td class="tbl-td r">${fc}</td>
      <td class="tbl-td r">${sd}</td>
      <td class="tbl-td r">${temp}</td>
      <td class="tbl-td r">${vpd}</td>
      <td class="tbl-td muted">${src}</td>
    </tr>`;
  }).join('');

  return `<div class="tbl-hdr">
    <span class="tbl-hdr-title">📋 생육 측정 이력</span>${badge}
  </div>
  <div class="tbl-wrap">
    <table style="min-width:560px">
      <thead>
        <tr class="tbl-head-row">
          <th class="tbl-th">측정일</th>
          <th class="tbl-th">작물</th>
          <th class="tbl-th r">초장</th>
          <th class="tbl-th r">엽수</th>
          <th class="tbl-th r">착과수</th>
          <th class="tbl-th r">경경</th>
          <th class="tbl-th r">온도</th>
          <th class="tbl-th r">VPD</th>
          <th class="tbl-th">출처</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 수확 이력 렌더 ─────────────────────────────────────────────────────────
function _renderHarvestTimeline(records, total) {
  const badge = total > records.length
    ? `<span class="rec-count">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span class="rec-count">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const trCls     = i % 2 === 1 ? ' class="tbl-alt"' : '';
    const dateStr   = _jFmtDate(r.harvest_date || r.recorded_at);
    const crop      = r.crop_ko || '—';
    const yld       = _jFmtNum(r.yield_kg_m2,   'kg/㎡', 2);
    const totalKg   = _jFmtNum(r.total_yield_kg, 'kg', 1);
    const area      = _jFmtNum(r.area_m2,        '㎡', 0);
    const days      = r.growing_days != null ? `${r.growing_days}일` : '—';
    const planting  = _jFmtDate(r.planting_date);
    const src       = r.source || 'api';
    return `<tr${trCls}>
      <td class="tbl-td accent">${dateStr}</td>
      <td class="tbl-td">${crop}</td>
      <td class="tbl-td r green">${yld}</td>
      <td class="tbl-td r">${totalKg}</td>
      <td class="tbl-td r">${area}</td>
      <td class="tbl-td r">${days}</td>
      <td class="tbl-td r muted">${planting}</td>
      <td class="tbl-td muted">${src}</td>
    </tr>`;
  }).join('');

  return `<div class="tbl-hdr">
    <span class="tbl-hdr-title">📦 수확량 기록 이력</span>${badge}
  </div>
  <div class="tbl-wrap">
    <table style="min-width:520px">
      <thead>
        <tr class="tbl-head-row">
          <th class="tbl-th">수확일</th>
          <th class="tbl-th">작물</th>
          <th class="tbl-th r">수량(kg/㎡)</th>
          <th class="tbl-th r">총수확(kg)</th>
          <th class="tbl-th r">면적(㎡)</th>
          <th class="tbl-th r">재배일수</th>
          <th class="tbl-th r">정식일</th>
          <th class="tbl-th">출처</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── 환경 수동 입력 이력 렌더 ───────────────────────────────────────────────
function _renderEnvTimeline(records, total) {
  const badge = total > records.length
    ? `<span class="rec-count">최신 ${records.length}건 / 전체 ${total}건</span>`
    : `<span class="rec-count">전체 ${total}건</span>`;

  const rows = records.map((r, i) => {
    const trCls = i % 2 === 1 ? ' class="tbl-alt"' : '';
    const ts  = r.recorded_at ? String(r.recorded_at).substring(0, 16).replace('T', ' ') : '—';
    const p   = r.payload || {};
    const temp = _jFmtNum(p.temp_internal,  '°C', 1);
    const humi = _jFmtNum(p.humidity_int,   '%',  0);
    const co2  = _jFmtNum(p.co2_ppm,        'ppm',0);
    const ec   = _jFmtNum(p.ec_dsm,         'dS/m',1);
    const ph   = _jFmtNum(p.ph,             '',   1);
    const vpd  = _jFmtNum(p.vpd_kpa,        'kPa',2);
    return `<tr${trCls}>
      <td class="tbl-td accent">${ts}</td>
      <td class="tbl-td r">${temp}</td>
      <td class="tbl-td r">${humi}</td>
      <td class="tbl-td r">${co2}</td>
      <td class="tbl-td r">${ec}</td>
      <td class="tbl-td r">${ph}</td>
      <td class="tbl-td r">${vpd}</td>
    </tr>`;
  }).join('');

  return `<div class="tbl-hdr">
    <span class="tbl-hdr-title">📋 환경값 수동 입력 이력</span>${badge}
  </div>
  <div class="tbl-wrap">
    <table style="min-width:420px">
      <thead>
        <tr class="tbl-head-row">
          <th class="tbl-th">입력 시각</th>
          <th class="tbl-th r">온도</th>
          <th class="tbl-th r">습도</th>
          <th class="tbl-th r">CO₂</th>
          <th class="tbl-th r">EC</th>
          <th class="tbl-th r">pH</th>
          <th class="tbl-th r">VPD</th>
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
    el.innerHTML = _errBoxHtml(e, '생육 이력 로드 실패');
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
    el.innerHTML = _errBoxHtml(e, '수확 이력 로드 실패');
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
    el.innerHTML = _errBoxHtml(e, '환경 이력 조회 실패');
  }
}

// ── 관수 이력 렌더 ─────────────────────────────────────────────────────────
function _renderIrrigationTimeline(records, dataDays) {
  const badge = `<span class="rec-count">최근 ${dataDays}일 데이터 · ${records.length}건</span>`;

  const rows = records.slice().reverse().map((r, i) => {
    const trCls   = i % 2 === 1 ? ' class="tbl-alt"' : '';
    const dateStr = _jFmtDate(r.date);
    const wc      = _jFmtNum(r.wc_mean,      '%', 1);
    const dr      = r.dr_pct_mean != null ? _jFmtNum(r.dr_pct_mean, '%', 1) : '—';
    const ec      = _jFmtNum(r.ec_drain,      'dS/m', 2);
    const sup     = _jFmtNum(r.supply_total,  'ml', 0);
    const cnt     = _jFmtNum(r.irr_count,     '회', 0);
    const nl      = r.nl_pct != null ? _jFmtNum(r.nl_pct, '%', 1) : '—';

    // 배액률 상태 컬러
    let drColor = 'var(--fg)';
    if (r.dr_pct_mean != null) {
      if (r.dr_pct_mean < 20)      drColor = 'var(--red)';
      else if (r.dr_pct_mean > 40) drColor = 'var(--orange)';
      else                          drColor = 'var(--green)';
    }
    // 함수율 컬러
    let wcColor = 'var(--fg)';
    if (r.wc_mean != null) {
      if (r.wc_mean < 60)      wcColor = 'var(--red)';
      else if (r.wc_mean > 95) wcColor = 'var(--orange)';
    }

    return `<tr${trCls}>
      <td class="tbl-td accent">${dateStr}</td>
      <td class="tbl-td r bold" style="color:${wcColor}">${wc}</td>
      <td class="tbl-td r bold" style="color:${drColor}">${dr}</td>
      <td class="tbl-td r">${ec}</td>
      <td class="tbl-td r">${sup}</td>
      <td class="tbl-td r">${cnt}</td>
      <td class="tbl-td r muted">${nl}</td>
    </tr>`;
  }).join('');

  return `<div class="tbl-hdr">
    <span class="tbl-hdr-title">💧 관수 기록 이력</span>${badge}
  </div>
  <div class="tbl-wrap">
    <table style="min-width:480px">
      <thead>
        <tr class="tbl-head-row">
          <th class="tbl-th">날짜</th>
          <th class="tbl-th r">함수율</th>
          <th class="tbl-th r">배액률</th>
          <th class="tbl-th r">배액EC</th>
          <th class="tbl-th r">총공급량</th>
          <th class="tbl-th r">관수횟수</th>
          <th class="tbl-th r">야간소실</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
  <div class="rec-count" style="margin-top:6px">
    🟢 배액률 20~40% 정상 &nbsp;|&nbsp; 🔴 배액률 &lt;20% 부족 &nbsp;|&nbsp; 🟠 배액률 &gt;40% 과다
  </div>`;
}

// ── 관수 이력 로더 ─────────────────────────────────────────────────────────
async function loadIrrigationHistory(farmId) {
  farmId = farmId || _defaultFarm();
  const el = $('irr-hist-body');
  if (!el || !farmId || !_token) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await apiFetch(`/api/farms/${encodeURIComponent(farmId)}/irrigation/analysis?days=30`);
    if (!data.records || !data.records.length) {
      el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💧</div>관수 기록이 없습니다<div class="empty-state-sub">P4 관수 데이터를 입력하면 이력이 표시됩니다</div></div>';
      return;
    }
    el.innerHTML = _renderIrrigationTimeline(data.records, data.data_days);
  } catch (e) {
    el.innerHTML = _errBoxHtml(e, '관수 이력 로드 실패');
  }
}
