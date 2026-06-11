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
          const demo = /데모|읽기 전용|403/.test(e && e.message || '');
          if (demo) {
            // 데모: 기록은 비활성이지만 상세 화면 링크는 연결 유지
            btn.textContent = '🔒 데모 — 상세로 이동';
            btn.style.opacity = '.85';
            if (it.target) setTimeout(() => { location.href = it.target; }, 900);
          } else {
            btn.disabled = false; btn.textContent = '다시 시도';
          }
        }
      });
    });
  }

  // ── 공통 빌더: 환경/추천 데이터 → 결정카드 items ──────────────────────────
  // 온실용 (배액률·VPD 이상감지 + AI 추천)
  function buildGreenhouse(env, recs, opts) {
    env = env || {}; recs = recs || []; opts = opts || {};
    const items = [];
    const age = env._ageMin ?? 1;
    const pl = opts.periodLabel || '';
    const dr = env.dr_pct ?? env.dr_pct_mean ?? null;
    if (dr != null && dr < 12) items.push({ severity:'danger', title:`배액률 ${dr.toFixed(1)}% — 근권 건조 위험`,
      why:`목표 20~30% 대비 크게 미달${pl?` (${pl})`:''}. 즉시 추가 관수가 필요합니다.`,
      action:'추가 관수 1회 실행 · 급액량 +10%', confidence:88, source:'live', updatedMin:age,
      evidence:'배액률<12%는 근권 수분 부족 신호로, 농진청 표준상 즉시 보충 관수 대상입니다.',
      applyLabel:'추가 관수 기록', target:'g3_period.html' });
    else if (dr != null && dr < 20) items.push({ severity:'warn', title:`배액률 ${dr.toFixed(1)}% — 목표 미달`,
      why:`목표 20~30%보다 낮습니다${pl?` (${pl})`:''}. 급액량 소폭 상향을 검토하세요.`,
      action:'급액량 +5% 또는 관수 간격 단축', confidence:74, source:'live', updatedMin:age,
      evidence:'배액률 12~20%는 경계 구간으로, 일사·VPD 추이를 보며 점진 상향이 권장됩니다.',
      applyLabel:'조정 기록', target:'g3_period.html' });
    const vpd = env.vpd ?? null;
    if (vpd != null && vpd > 1.8) items.push({ severity:'warn', title:`VPD ${vpd.toFixed(1)} kPa — 증산 과다`,
      why:'공기가 건조해 수분 스트레스 위험이 있습니다. 환기 약화 또는 가습/급액 보완이 필요합니다.',
      action:'환기 단계 ↓ · 급액 보충', confidence:70, source:'live', updatedMin:age,
      evidence:'VPD>1.8 kPa는 기공 폐쇄·광합성 저하 구간. 적정대(0.6~1.2) 복귀가 목표.',
      applyLabel:'환경 조정 기록', target:'g2_env.html' });
    else if (vpd != null && vpd < 0.6) items.push({ severity:'info', title:`VPD ${vpd.toFixed(1)} kPa — 과습 주의`,
      why:'습도가 높아 결로·곰팡이병 위험이 올라갑니다. 환기 강화를 검토하세요.',
      action:'환기 단계 ↑ · 제습', confidence:66, source:'live', updatedMin:age,
      evidence:'VPD<0.6 kPa 지속은 잿빛곰팡이 등 병해 발생 환경. 환기로 포차를 높이는 것이 효과적.',
      applyLabel:'환기 조정 기록', target:'g5_disease.html' });
    if (recs.length) {
      const r = recs[0]; const conf = Math.round((r.confidence ?? 0) * 100);
      const isStd = opts.modelLayer === '농진청표준';
      items.push({ severity:'info', title: r.title_ko || 'AI 관수·양액 추천',
        why: r.action_ko || (isStd ? '농진청 표준 기준값을 적용 중입니다.' : 'AI 모델 추천입니다.'),
        action: r.action_ko || r.title_ko, confidence: conf || 60,
        source: isStd ? 'standard' : 'model', updatedMin: env._ageMin ?? 3,
        evidence:`추천 근거: ${r.title_ko||'관수 최적화'} · 모델 레이어 ${opts.modelLayer||'KAASA'}`,
        applyLabel:'추천 적용 기록', target:'g3_period.html' });
    }
    return items;
  }

  // 노지용 (기상 기반: 강풍·강우·고온·관개)
  function buildField(env, wx, opts) {
    env = env || {}; wx = wx || {}; opts = opts || {};
    const items = [];
    const age = env._ageMin ?? 5;
    const wind = wx.wind_speed ?? env.wind_speed_ext ?? null;
    const rain = wx.precip_mm ?? wx.rain_mm ?? null;
    const tmax = wx.temp_max ?? env.temp_ext ?? null;
    if (wind != null && wind >= 9) items.push({ severity:'danger', title:`강풍 ${wind.toFixed(0)} m/s 예보 — 시설·작물 피해 위험`,
      why:'지주·피복 점검과 방풍 조치가 필요합니다. 약제 살포는 연기하세요.',
      action:'지주 보강 · 살포 연기', confidence:80, source:'model', updatedMin:age,
      evidence:'순간풍속 9 m/s↑은 비닐·지주 탈락 위험 구간. 기상청 예보 기반.',
      applyLabel:'대비 조치 기록', target:'f3_weather.html' });
    if (rain != null && rain >= 20) items.push({ severity:'warn', title:`강우 ${rain.toFixed(0)} mm 예보 — 관개 보류 권장`,
      why:'예정된 관개를 보류하고 배수로를 점검하세요. 침수 우려 필지를 우선 확인합니다.',
      action:'관개 보류 · 배수로 점검', confidence:76, source:'model', updatedMin:age,
      evidence:'일 강우 20 mm↑ 예보 시 관개 중복은 과습·뿌리 장해 유발.',
      applyLabel:'관개 보류 기록', target:'f4_soil.html' });
    else if (rain != null && rain < 1 && tmax != null && tmax >= 28) items.push({ severity:'info', title:`고온 건조 — 관개 필요`,
      why:`최고 ${tmax.toFixed(0)}℃·무강우 예보. 증발산이 커 토양수분 보충이 필요합니다.`,
      action:'관개 1회 실시 (오전 권장)', confidence:68, source:'model', updatedMin:age,
      evidence:'고온·무강우 조합은 ETc 상승으로 토양수분 급감. 오전 관개가 증발 손실 최소.',
      applyLabel:'관개 기록', target:'f4_soil.html' });
    // ET₀ 증발산 기반 관개 (강우 적고 증발산 높을 때)
    const et0 = wx.et0 ?? null;
    if (!items.some(i=>i.target==='f4_soil.html') && et0 != null && et0 >= 6 && (rain == null || rain < 5))
      items.push({ severity:'info', title:`증발산(ET₀) ${et0.toFixed(1)} mm — 관개 검토`,
        why:'주간 증발산이 높고 강우가 적습니다. 토양수분 소모가 빨라 관개 계획이 필요합니다.',
        action:'관개량 산정 · 우선 필지부터 관개', confidence:67, source:'model', updatedMin:age,
        evidence:`ET₀ ${et0.toFixed(1)} mm·강우 ${(rain??0).toFixed(0)} mm 기준, 작물계수(Kc) 적용한 ETc만큼 보충 권장.`,
        applyLabel:'관개 계획 기록', target:'f4_soil.html' });
    return items;
  }

  // 16일 장기예보(Open-Meteo) 재해 → 선행 의사결정 카드
  // hazards: [{date:'2026-06-22', type:'호우'|'폭염'|'강풍'|'서리/저온', value:48.4}]
  function buildFieldHazards(hazards, opts) {
    opts = opts || {}; const items = [];
    const arr = (hazards || []).slice(0, 4);
    const _md = d => { try { const p = String(d).split('-'); return `${+p[1]}/${+p[2]}`; } catch (e) { return d; } };
    const _dleft = d => { try { const t = new Date(d + 'T00:00:00'), n = new Date();
      return Math.max(0, Math.round((t - new Date(n.getFullYear(), n.getMonth(), n.getDate())) / 86400000)); } catch (e) { return null; } };
    for (const h of arr) {
      const dl = _dleft(h.date), when = dl === 0 ? '오늘' : dl === 1 ? '내일' : (dl != null ? `${dl}일 뒤` : _md(h.date));
      const lead = `${_md(h.date)} (${when})`;
      if (h.type === '호우') items.push({ severity:'danger', title:`${lead} 호우 ${Number(h.value).toFixed(0)}mm 예보 — 사전 대비`,
        why:'장기예보 기준 집중호우 예상. 배수로 정비·관개 일정 조정·침수 우려 필지를 선점검하세요.',
        action:'배수로 정비 · 관개 보류 · 멀칭 점검', confidence:62, source:'model', updatedMin:opts.age ?? 60,
        evidence:`Open-Meteo 16일 예보 일강수 ${Number(h.value).toFixed(1)}mm(호우 임계 30mm↑). 선행 대비로 피해 경감.`,
        applyLabel:'대비 조치 기록', target:'f3_weather.html' });
      else if (h.type === '폭염') items.push({ severity:'warn', title:`${lead} 폭염 ${Number(h.value).toFixed(0)}℃ 예보 — 관개·차광 대비`,
        why:'고온 스트레스 예상. 관개량 상향·차광·환기 계획을 미리 세우세요. 노약 작물 우선.',
        action:'관개 증량 · 차광/환기 준비', confidence:60, source:'model', updatedMin:opts.age ?? 60,
        evidence:`예보 최고기온 ${Number(h.value).toFixed(0)}℃(폭염 임계 33℃↑). 증발산 급증 대비.`,
        applyLabel:'폭염 대비 기록', target:'f4_soil.html' });
      else if (h.type === '강풍') items.push({ severity:'danger', title:`${lead} 강풍 ${Number(h.value).toFixed(0)}m/s 예보 — 시설 보강`,
        why:'강풍 예상. 지주·피복 보강과 방풍 조치를 사전 시행하고 약제 살포는 연기하세요.',
        action:'지주·피복 보강 · 살포 연기', confidence:64, source:'model', updatedMin:opts.age ?? 60,
        evidence:`예보 최대풍속 ${Number(h.value).toFixed(0)}m/s. 비닐·지주 탈락 위험 구간 선제 대비.`,
        applyLabel:'대비 조치 기록', target:'f3_weather.html' });
      else if (h.type && h.type.indexOf('서리') >= 0) items.push({ severity:'warn', title:`${lead} 서리/저온(${Number(h.value).toFixed(0)}℃) 예보 — 보온 대비`,
        why:'저온·서리 예상. 보온커튼·방상팬·관수 보온 등 동해 예방 조치를 준비하세요.',
        action:'보온 자재 점검 · 야간 관수 검토', confidence:60, source:'model', updatedMin:opts.age ?? 60,
        evidence:`예보 최저기온 ${Number(h.value).toFixed(0)}℃(서리 임계 0℃↓). 정식·개화기 동해 위험.`,
        applyLabel:'보온 대비 기록', target:'f3_weather.html' });
    }
    return items;
  }

  // 노지 클러스터 작황 이상알림(/field/cluster) → 위치특정 의사결정 카드
  // alerts: [{location,type,ndvi,deviation_pct,severity,action,target,record}]
  function buildFieldCluster(alerts, opts) {
    opts = opts || {}; const items = [];
    for (const a of (alerts || []).slice(0, 3)) {
      const sev = a.severity === 'danger' ? 'danger' : 'warn';
      items.push({ severity: sev,
        title: `📍 ${a.location} — ${a.type} (Δ${Number(a.deviation_pct).toFixed(0)}%)`,
        why: `위성 식생지수 NDVI ${Number(a.ndvi).toFixed(2)} · 클러스터 평균 대비 ${Number(a.deviation_pct).toFixed(1)}%. ${a.action || '현장 확인 권장'}.`,
        action: a.action || '현장 확인', confidence: 64, source: 'model', updatedMin: opts.age ?? 30,
        evidence: '무센서 위성·기상 작황진단. 평균 대비 음(-)편차가 큰 필지를 우선 점검.',
        applyLabel: '현장확인 기록', target: a.target || 'f8_cluster.html' });
    }
    return items;
  }

  global.DecisionDeck = { render, buildGreenhouse, buildField, buildFieldHazards, buildFieldCluster };
})(window);
