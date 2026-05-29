// ── WebSocket 실시간 센서 — 전역 상태 ────────────────────────────────────────
let _ws = null, _wsActive = false, _wsRetryDelay = 2000, _wsRetryTimer = null;
let _wsPingTimer = null;
let _currentFarm = 'farm_001';

const SENSOR_RANGE = {
  temp_internal: [-5,  55],
  humidity_int:  [0,  100],
  co2_ppm:       [200,5000],
  soil_temp:     [-5,  50],
  ec_dsm:        [0,   10],
};

function wsBadge(state) {
  const badge = $('ws-badge'), label = $('ws-label');
  badge.className = `ws-badge ${state}`;
  const dot = badge.querySelector('.ws-dot');
  if (state === 'connected') { label.textContent='실시간 연결'; dot?.classList.add('pulse'); }
  else if (state === 'reconnecting') { label.textContent='재연결 중…'; dot?.classList.remove('pulse'); }
  else { label.textContent='연결 안 됨'; dot?.classList.remove('pulse'); }
}

function wsConnect(farmId) {
  if (farmId) _currentFarm = farmId;
  if (_ws) { _ws.onclose=null; _ws.close(); }
  clearTimeout(_wsRetryTimer);
  wsBadge('reconnecting');
  _wsActive = false;
  const url = `${_apiBase.replace(/^http/,'ws')}/ws/farms/${_currentFarm}/sensors`;
  try { _ws = new WebSocket(url); } catch { scheduleWsRetry(); return; }
  _ws.onopen    = () => { wsBadge('connected'); _wsActive=true; _wsRetryDelay=2000; };
  _ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type==='env')  applyEnvMessage(msg);
      if (msg.type==='ping') _ws.send(JSON.stringify({type:'pong'}));
    } catch {}
  };
  _ws.onerror = () => {};
  _ws.onclose = () => { wsBadge('disconnected'); _wsActive=false; scheduleWsRetry(); };
  if (_wsPingTimer) clearInterval(_wsPingTimer);
  _wsPingTimer = setInterval(() => { if(_ws?.readyState===1) _ws.send(JSON.stringify({type:'ping'})); }, 30_000);
}

function scheduleWsRetry() {
  _wsRetryTimer = setTimeout(() => wsConnect(), _wsRetryDelay);
  _wsRetryDelay = Math.min(_wsRetryDelay*2, 30_000);
}

function switchFarm(farmId) {
  _currentFarm = farmId;
  ['temp','humi','co2','solar','soil','ec'].forEach(k => { const el=$(`sv-${k}`); if(el) el.textContent='—'; });
  $('sensor-ts').textContent = '마지막 수신: —';
  _wsRetryDelay = 2000;
  wsConnect(farmId);
}

function applyEnvMessage(msg) {
  const sv = (id, v) => { const el=$(id); if(el) el.textContent = v!=null?Number(v).toFixed(1):'—'; };
  sv('sv-temp',  msg.temp_internal);
  sv('sv-humi',  msg.humidity_int);
  sv('sv-co2',   msg.co2_ppm);
  sv('sv-solar', msg.solar_rad);
  sv('sv-soil',  msg.soil_temp);
  sv('sv-ec',    msg.ec_dsm);
  const ts = msg.ts ? new Date(msg.ts).toLocaleTimeString('ko-KR') : new Date().toLocaleTimeString('ko-KR');
  $('sensor-ts').textContent = `마지막 수신: ${ts}`;
  ['temp','humi','co2','solar','soil','ec'].forEach(k => $(`sc-${k}`)?.classList.remove('anomaly'));
  if (msg._anomaly) showAnomalyToast(msg);
}

// HTTP 폴백 30초 polling
setInterval(async () => {
  if (_wsActive || !_token || document.hidden) return;
  try {
    const d = await apiFetch(`/api/sensors/${_currentFarm}/latest`);
    if (d?.messages?.length) applyEnvMessage(d.messages[d.messages.length-1]);
  } catch(e) { console.debug('[ws-fallback] 폴링 실패:', e.message); }
}, 30_000);

// ── 환경: 현재 환경값 ─────────────────────────────────────────────────────────
async function loadCurrentEnv() {
  const farmId = $('env-view-farm')?.value || _defaultFarm();
  const el = $('env-current-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment`);
    const fmtF = (n,dp=1) => n!=null ? Number(n).toFixed(dp) : '—';
    const items = [
      { label:'내부온도',    val:fmtF(d.temp_internal),  unit:'°C'  },
      { label:'내부습도',    val:fmtF(d.humidity_int),   unit:'%'   },
      { label:'CO₂',         val:fmtF(d.co2_ppm,0),      unit:'ppm' },
      { label:'지온',        val:fmtF(d.soil_temp),       unit:'°C'  },
      { label:'EC',          val:fmtF(d.ec_dsm,2),        unit:'dS/m'},
      { label:'pH',          val:fmtF(d.ph,1),            unit:''    },
    ];
    const ts = d.timestamp ? new Date(d.timestamp).toLocaleString('ko-KR') : '';
    el.innerHTML = `
      <div class="env-kpi-grid">
        ${items.map(it=>`<div class="env-kpi-item">
          <div class="ek-label">${it.label}</div>
          <div class="ek-val">${it.val} <span style="font-size:10px;color:var(--muted)">${it.unit}</span></div>
        </div>`).join('')}
      </div>
      ${ts?`<div style="font-size:10px;color:var(--muted);margin-top:6px;text-align:right">측정시각: ${ts}</div>`:''}`;

    setText('env-kpi-temp', fmtF(d.temp_internal));
    if (d.temp_internal != null && d.humidity_int != null) {
      const t = d.temp_internal; const rh = d.humidity_int;
      const svp = 0.6108 * Math.exp(17.27 * t / (t + 237.3));
      setText('env-kpi-vpd', (svp * (1 - rh / 100)).toFixed(2));
    }
    setText('env-kpi-co2', fmtF(d.co2_ppm, 0));
    const solarVal = d.solar_rad ?? d.solar_radiation ?? d.solar_rad_est ?? null;
    // 위도 37°N 기준 월별 일조시간 추정 (4~9월: 장일, 10~3월: 단일)
    const _dliHours = [9,10,11,12,13,14,14,13,12,11,10,9][new Date().getMonth()];
    setText('env-kpi-dli', solarVal != null ? (solarVal * 3600 / 1e6 * _dliHours).toFixed(1) : '—');
    apiFetch(`/api/farms/${farmId}/erp/realtime`).then(erp => {
      const energyW = erp?.cost_breakdown?.energy_per_m2;
      setText('env-kpi-energy', energyW != null ? Math.round(energyW) + 'W/m²' : '—');
      const hint = $('env-kpi-energy-hint');
      if (hint && erp?.peak_status) hint.textContent = erp.peak_status;
    }).catch(() => setText('env-kpi-energy', '—'));

    if (d.control_mode) {
      const modeColorMap = { full_auto: 'orange', approval: 'green', advisory: '', manual: '' };
      document.querySelectorAll('#env-mode-bar [data-mode]').forEach(el => {
        const active = el.dataset.mode === d.control_mode;
        el.className = 'pill-tag' + (active ? ' ' + (modeColorMap[d.control_mode] || 'blue') : '');
        el.style.fontWeight = active ? '700' : '';
        el.style.opacity    = active ? '1'   : '0.45';
      });
    }
    const fsEl = $('env-failsafe-pill');
    if (fsEl) {
      const fsOk = d.failsafe_status === 'ok' || d.failsafe_status == null;
      fsEl.textContent = fsOk ? 'Fail-safe 정상' : 'Fail-safe 이상';
      fsEl.className   = 'pill-tag ' + (fsOk ? 'green' : 'danger');
      fsEl.style.opacity = '1';
    }
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경: 7일 기상 예보 ───────────────────────────────────────────────────────
async function loadWeatherForecast() {
  const farmId = $('weather-farm-sel')?.value || _defaultFarm();
  const el = $('weather-body');
  if (!farmId || !el) return;
  el.innerHTML = '<div class="spinner"></div>';
  loadWeatherEt0(farmId);
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment/weather`);
    const _fc = d.forecast;
    const days = Array.isArray(_fc) ? _fc
               : (_fc && Array.isArray(_fc.days) ? _fc.days
               : (Array.isArray(d.days) ? d.days : []));
    if (!days.length) { el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">예보 데이터 없음</div>'; return; }
    const rows = days.map(day => {
      let dtStr = '—';
      if (day.date) {
        const raw = String(day.date);
        const normalized = raw.length === 8 ? `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}` : raw;
        try { dtStr = new Date(normalized).toLocaleDateString('ko-KR',{month:'numeric',day:'numeric',weekday:'short'}); }
        catch(e) { dtStr = _esc(raw); }
      }
      const sky = day.sky || day.sky_label || '';
      const icon = sky.includes('맑') ? '☀️' : sky.includes('구름') ? '⛅' : '🌧️';
      const windSpd = day.wind_spd ?? day.wind_speed;
      const fmtNum = v => v != null && !isNaN(Number(v)) ? Number(v) : null;
      const tMin = fmtNum(day.temp_min), tMax = fmtNum(day.temp_max), pProb = fmtNum(day.precip_prob);
      return `<tr>
        <td>${dtStr}</td><td>${icon} ${_esc(sky||'—')}</td>
        <td>${tMin!=null?tMin+'°':''} / ${tMax!=null?tMax+'°':'—'}</td>
        <td>${pProb!=null?pProb+'%':'—'}</td>
        <td>${windSpd!=null?Number(windSpd).toFixed(1)+' m/s':'—'}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<div class="weather-tbl-wrap"><table class="weather-tbl">
      <thead><tr><th>날짜</th><th>날씨</th><th>기온</th><th>강수확률</th><th>풍속</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">예보 조회 실패: ${_esc(e.message)}</span>`;
  }
}

async function loadWeatherEt0(farmId) {
  const el = $('weather-et0-body');
  if (!el || !farmId) return;
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment/weather/forecast?days=7`);
    const et0 = d.et0_forecast_mm || [];
    if (!et0.length) { el.innerHTML = ''; return; }
    const bars = et0.map((v, i) => {
      const val = v != null ? Number(v).toFixed(1) : '?';
      const pct = Math.min(100, (Number(v) / 8) * 100);
      return `<div style="text-align:center;flex:1;min-width:36px">
        <div style="font-size:10px;color:var(--muted);margin-bottom:2px">D+${i+1}</div>
        <div style="background:rgba(79,142,247,.15);border-radius:4px;overflow:hidden;height:40px;display:flex;align-items:flex-end">
          <div style="width:100%;height:${pct}%;background:var(--accent);border-radius:4px 4px 0 0;min-height:2px"></div>
        </div>
        <div style="font-size:11px;font-weight:700;margin-top:3px;color:var(--accent)">${val}</div>
      </div>`;
    }).join('');
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
        <span style="font-size:11px;font-weight:700;color:var(--green)">💧 ET₀ 예보 (mm/일)</span>
        <span style="font-size:10px;color:var(--muted)">Hargreaves · ${_esc(d.source || 'open_meteo')}</span>
      </div>
      <div style="display:flex;gap:4px;align-items:flex-end">${bars}</div>`;
  } catch(e) { el.innerHTML = ''; }
}

// ── 환경: 병해 탐지 ───────────────────────────────────────────────────────────
async function loadDiseaseDetect(farmId) {
  const el = $('disease-detect-body');
  if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const fid = farmId || _myFarmId || (_farmsData[0]?.farm_id);
    if (!fid) { el.innerHTML = _nullReasonHtml([['농장 미선택', '위에서 농장을 선택하면 병해 탐지 결과가 표시됩니다']]); return; }
    const d = await apiFetch(`/api/farms/${fid}/disease/detect`, {method:'POST',
      headers:{'Content-Type':'application/json'}, body:'{}' });
    const risk = d.risk_level || 'none';
    const riskColor = risk==='high'?'var(--red)':risk==='medium'?'var(--yellow)':'var(--green)';
    const riskTxt   = {high:'🔴 높음',medium:'🟡 중간',low:'🟢 낮음',none:'✅ 정상'}[risk] || '—';
    const srcBadges = (d.source_chain||[]).map(s=>`<span class="badge info" style="font-size:9px">${_esc(s)}</span>`).join(' ');
    const allRisks  = (d.all_risks||[]).slice(0,4).map(r=>`
      <div style="display:flex;justify-content:space-between;padding:3px 0;font-size:11px">
        <span>${_esc(r.disease_ko || r.disease || '—')}</span>
        <span style="color:${r.risk_level==='high'?'var(--red)':r.risk_level==='medium'?'var(--yellow)':'var(--green)'}">${r.score != null ? (r.score*100).toFixed(0) : '—'}%</span>
      </div>`).join('');
    const ncpms = (d.ncpms_forecast||[]).slice(0,3).map(f=>`<div style="font-size:10px;color:var(--muted)">${_esc(f.date)} ${_esc(f.pest_ko)} ${_esc(f.level)}</div>`).join('');
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <div style="font-size:22px;font-weight:700;color:${riskColor}">${riskTxt}</div>
        <div>
          <div style="font-weight:600">${_esc(d.disease_ko||'이상 없음')}</div>
          <div style="font-size:11px;color:var(--muted)">${_esc(d.action_ko||'')}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:6px">
        ${(d.reasons||[]).map(r=>`• ${_esc(r)}`).join('<br>')}
      </div>
      ${allRisks ? `<div style="border-top:1px solid var(--border);padding-top:6px;margin-bottom:6px">${allRisks}</div>` : ''}
      ${ncpms ? `<div style="border-top:1px solid var(--border);padding-top:6px"><div style="font-size:10px;font-weight:700;color:var(--muted);margin-bottom:3px">NCPMS 발생예보</div>${ncpms}</div>` : ''}
      <div style="margin-top:8px">${srcBadges}</div>`;

    const riskLabel = {high:'🔴 높음', medium:'🟡 중간', low:'🟢 낮음', none:'✅ 정상'};
    setText('g5-disease-risk', riskLabel[risk] || '—');
    const topPest = (d.all_risks||[]).find(r => r.category === '해충' || r.disease_ko?.includes('응애') || r.disease_ko?.includes('진딧물'));
    setText('g5-pest-risk', topPest ? '🟡 ' + (topPest.disease_ko||'주의') : '✅ 정상');
    setText('g5-quality-risk', '보통');
    setText('g5-disease-hint', ((d.reasons||[]).slice(0,1).join('') || 'AI 탐지 결과').slice(0, 20));
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}

// ── 환경: 수동 환경값 입력 ────────────────────────────────────────────────────
async function submitManualEnv() {
  const farmId = $('env-manual-farm')?.value;
  if (!farmId) { _setResult('env-manual-result', 'warn', '농장을 선택하세요'); return; }
  const body = {};
  const pairs = [['em-temp','temp_internal'],['em-humi','humidity_int'],
                 ['em-co2','co2_ppm'],['em-ec','ec_dsm'],['em-ph','ph'],
                 ['em-soil','soil_temp']];
  pairs.forEach(([id, key]) => { const v = $(id)?.value; if (v !== '' && v != null) body[key] = parseFloat(v); });
  if (!Object.keys(body).length) { _setResult('env-manual-result', 'warn', '입력값이 없습니다'); return; }
  try {
    await apiFetch(`/api/farms/${farmId}/environment/manual`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    _setResult('env-manual-result', 'ok', `저장 완료 — AI 추천이 업데이트됩니다`);
    loadCurrentEnv();
    setTimeout(() => { if (typeof loadEnvHistory === 'function') loadEnvHistory(farmId); }, 800);
  } catch(e) {
    _setResult('env-manual-result', 'err', '저장 실패: ' + e.message);
  }
}

// ── 환경: 이상 감지 조회 ──────────────────────────────────────────────────────
async function loadEnvAnomalies() {
  if (!_token) return;
  const farmId = $('env-anomaly-farm')?.value || _defaultFarm();
  const el = $('env-anomaly-body');
  if (!el) return;
  if (!farmId) {
    el.innerHTML = _nullReasonHtml([['농장 미선택', '위 드롭다운에서 농장을 선택하면 알림·권고 내역이 표시됩니다']]);
    return;
  }
  const sel = $('env-anomaly-farm');
  if (sel && !sel.value && farmId) {
    const opt = document.createElement('option');
    opt.value = farmId; opt.text = farmId; opt.selected = true;
    sel.appendChild(opt);
  }
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const d = await apiFetch(`/api/farms/${farmId}/environment`);
    const alerts = d.alerts || d.anomalies || [];
    // simulated = IoT 없을 때 API가 주입한 작목 표준값 (실측 아님)
    const isSimulated = d.indoor?.source === 'simulated';
    const noEnvData = isSimulated || (d.temp_internal == null && d.humidity_int == null);

    if (!alerts.length) {
      if (noEnvData) {
        const simNote = isSimulated
          ? '<div style="font-size:11px;color:var(--muted);margin-top:8px">💡 작목 표준 시뮬레이션 값이 사용 중입니다. 실측 이상 감지를 위해 IoT 센서를 연결하거나 수동 입력 탭에서 수치를 직접 입력하세요.</div>'
          : '<div style="font-size:11px;color:var(--muted);margin-top:8px">수동 입력 탭에서 환경 수치를 직접 입력할 수 있습니다.</div>';
        el.innerHTML = '<div style="padding:16px;text-align:center;border-radius:8px;background:var(--card-soft);border:1px solid var(--border)">' +
          '<div style="font-size:22px;margin-bottom:8px">📡</div>' +
          '<div style="font-size:13px;font-weight:600;color:var(--fg);margin-bottom:4px">IoT 센서 미연결</div>' +
          '<div style="font-size:12px;color:var(--muted)">센서 데이터가 수집되면 이상 감지가 자동으로 시작됩니다.</div>' +
          simNote +
          '</div>';
      } else {
        const _SEN = [
          {key:'temp_internal', label:'내부온도', unit:'°C',  icon:'🌡️'},
          {key:'humidity_int',  label:'내부습도', unit:'%',   icon:'💧'},
          {key:'co2_ppm',       label:'CO₂',     unit:'ppm', icon:'💨'},
          {key:'ec_dsm',        label:'EC',       unit:'dS/m',icon:'⚡'},
          {key:'solar_rad',     label:'일사량',   unit:'W/m²',icon:'☀️'},
          {key:'soil_temp',     label:'지온',     unit:'°C',  icon:'🌱'},
        ];
        const sensorHtml = _SEN
          .filter(s => d[s.key] != null)
          .map(s => `<div style="display:flex;align-items:center;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border)">
            <span style="font-size:12px;color:var(--muted)">${s.icon} ${s.label}</span>
            <span style="font-size:13px;font-weight:600;color:var(--green)">${Number(d[s.key]).toFixed(1)} <span style="font-size:10px;font-weight:400">${s.unit}</span></span>
          </div>`).join('');
        const srcLabel = d.iot_available ? 'IoT 실시간' : (d.indoor?.source === 'manual_input' ? '수동 입력' : '');
        const srcBadge = srcLabel ? `<span class="status-badge info" style="font-size:10px;padding:2px 7px">${srcLabel}</span>` : '';
        el.innerHTML = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">' +
          '<span class="status-badge good">✅ 정상</span>' +
          srcBadge +
          '<span style="font-size:12px;color:var(--muted)">모든 환경 지표 이상 없음</span></div>' +
          (sensorHtml ? `<div style="margin-top:4px">${sensorHtml}</div>` : '');
      }
      return;
    }
    el.innerHTML = '<div style="display:flex;flex-direction:column;gap:6px;margin-top:6px">' +
      alerts.map(a => {
        const sev = a.severity || 'minor';
        const cls  = sev === 'critical' ? 'var(--red)' : sev === 'major' ? 'var(--yellow)' : 'var(--accent)';
        const badgeCls = sev === 'critical' ? 'danger' : sev === 'major' ? 'warn' : 'info';
        const badgeTxt = sev === 'critical' ? '🚨 위험' : sev === 'major' ? '⚠️ 주의' : '💡 참고';
        const valStr = a.current_value != null ? (Number(a.current_value) % 1 === 0 ? Number(a.current_value) : Number(a.current_value).toFixed(2)) : '—';
        return `<div style="padding:10px 12px;border-radius:10px;border-left:3px solid ${cls};background:var(--card-soft);font-size:12px">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
            <span class="status-badge ${badgeCls}">${badgeTxt}</span>
            <span style="font-weight:600">${_esc(a.variable_ko || a.variable)}</span>
            <span style="color:${cls};font-weight:700">${_esc(valStr)}${_esc(a.unit||'')}</span>
          </div>
          <div style="color:var(--muted);margin-bottom:8px">${_esc(a.message_ko || '')}</div>
          <div class="anomaly-action-btns">
            <button class="reco-apply-btn" style="font-size:11px;padding:6px 14px" onclick="this.textContent='✅ 승인됨';this.disabled=true;this.nextElementSibling.disabled=true;showToast('AI 제어 권고를 승인했습니다.')">✓ 승인</button>
            <button class="btn-ghost" style="font-size:11px;padding:6px 14px" onclick="this.textContent='⏸ 보류됨';this.disabled=true;this.previousElementSibling.disabled=true;showToast('권고를 보류했습니다.')">⏸ 보류</button>
          </div></div>`;
      }).join('') + '</div>';
  } catch(e) {
    el.innerHTML = _errBoxHtml(e, '환경 이상감지 조회 실패');
  }
}

// ── 환경: LED 스펙트럼 ────────────────────────────────────────────────────────
async function loadLEDSpectrum() {
  const farmId = $('led-farm-sel')?.value || _defaultFarm();
  const el = $('led-current-stage');
  if (!farmId || !el) return;
  try {
    const d = await apiFetch(`/api/farms/${farmId}/erp/realtime`);
    const stage = d.growth_stage || '';
    const led   = d.led_spectrum || {};
    if (!stage) { el.innerHTML = ''; return; }

    const stageRow = {
      '발아·정식기': 0, '영양생장기': 1, '착화·착과기': 2, '성숙·수확기': 3,
    };
    const tbody = document.querySelectorAll('#led-spectrum-body tbody tr');
    tbody.forEach((row, i) => {
      row.style.background = i === stageRow[stage]
        ? 'rgba(79,142,247,0.12)' : (i % 2 === 1 ? 'var(--card-soft)' : '');
      row.style.outline = i === stageRow[stage] ? '1px solid rgba(79,142,247,0.4)' : '';
    });

    el.innerHTML = `
      <div style="background:rgba(79,142,247,0.1);border:1px solid rgba(79,142,247,0.35);border-radius:8px;padding:10px 14px;margin-top:4px">
        <div style="font-size:12px;font-weight:600;color:var(--accent);margin-bottom:4px">📍 현재 단계: ${_esc(stage)}</div>
        <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:12px">
          <span>🔴 적색 <strong>${led.red ?? '—'}%</strong></span>
          <span>🔵 청색 <strong>${led.blue ?? '—'}%</strong></span>
          <span>🟣 UV <strong>${led.uv ?? '—'}%</strong></span>
          <span style="color:var(--muted)">비율: <strong>${_esc(led.ratio_str || '—')}</strong></span>
        </div>
        <div style="font-size:11px;color:var(--green);margin-top:4px">✅ ${_esc(led.effect || '')}</div>
        ${led.note ? `<div style="font-size:10px;color:var(--muted);margin-top:2px">${_esc(led.note)}</div>` : ''}
      </div>`;
  } catch(e) {
    el.innerHTML = `<span class="err-inline">조회 실패: ${_esc(e.message)}</span>`;
  }
}
