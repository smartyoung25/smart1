/* ─────────────────────────────────────────────────────────────
 * BandChart — setpoint 밴드(목표대) 음영 + 시계열 라인 (의존성 0, SVG)
 *  벤치마킹: Climate FieldView / iFarm "off-recipe" 편차 시각화
 *
 * BandChart.render(el, {
 *   series: [{t:'05-31', v:24.5}, ...],   // 시계열
 *   band:   { lo:20, hi:30, label:'목표 20~30%' },  // 목표대
 *   unit:'%', color:'#2563eb',
 *   yMin, yMax,   // 생략 시 자동
 *   height:140
 * })
 *  · 밴드 안=정상(녹색 점), 밴드 밖=편차(주황/빨강 점)로 3중 코딩
 * ───────────────────────────────────────────────────────────── */
(function (global) {
  function render(el, cfg) {
    if (!el) return;
    cfg = cfg || {};
    const series = (cfg.series || []).filter(p => p && p.v != null);
    const band = cfg.band || null;
    const unit = cfg.unit || '';
    const color = cfg.color || '#2563eb';
    const H = cfg.height || 140;
    const W = 320;                  // viewBox 폭 (반응형 width:100%)
    const padL = 34, padR = 12, padT = 12, padB = 22;
    const iw = W - padL - padR, ih = H - padT - padB;

    if (!series.length) {
      el.innerHTML = `<div style="text-align:center;padding:20px;color:var(--muted);font-size:12px;">표시할 시계열 데이터가 없습니다.</div>`;
      return;
    }

    const vals = series.map(p => p.v);
    let yMin = cfg.yMin, yMax = cfg.yMax;
    const dataMin = Math.min(...vals, band ? band.lo : Infinity);
    const dataMax = Math.max(...vals, band ? band.hi : -Infinity);
    if (yMin == null) yMin = Math.floor((dataMin - (dataMax - dataMin || 1) * 0.15));
    if (yMax == null) yMax = Math.ceil((dataMax + (dataMax - dataMin || 1) * 0.15));
    if (yMax === yMin) yMax = yMin + 1;

    const x = i => padL + (series.length === 1 ? iw / 2 : (i / (series.length - 1)) * iw);
    const y = v => padT + ih - ((v - yMin) / (yMax - yMin)) * ih;
    const inBand = v => band ? (v >= band.lo && v <= band.hi) : true;
    const dotColor = v => inBand(v) ? 'var(--green,#1f7a4d)' : (band && (v < band.lo * 0.6 || v > band.hi * 1.4) ? 'var(--red,#dc2626)' : 'var(--orange,#ea8a00)');

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="시계열 밴드 차트">`;
    // 밴드 음영
    if (band) {
      const by = y(band.hi), bh = Math.max(0, y(band.lo) - y(band.hi));
      svg += `<rect x="${padL}" y="${by}" width="${iw}" height="${bh}" fill="rgba(31,122,77,.12)" />`;
      svg += `<line x1="${padL}" y1="${by}" x2="${padL+iw}" y2="${by}" stroke="rgba(31,122,77,.45)" stroke-dasharray="3 3"/>`;
      svg += `<line x1="${padL}" y1="${y(band.lo)}" x2="${padL+iw}" y2="${y(band.lo)}" stroke="rgba(31,122,77,.45)" stroke-dasharray="3 3"/>`;
    }
    // Y축 눈금 (min/mid/max)
    [yMin, (yMin+yMax)/2, yMax].forEach(t => {
      svg += `<text x="${padL-5}" y="${y(t)+3}" text-anchor="end" font-size="9" fill="var(--muted,#888)">${Math.round(t)}</text>`;
      svg += `<line x1="${padL}" y1="${y(t)}" x2="${padL+iw}" y2="${y(t)}" stroke="var(--border,#e5e7eb)" stroke-width=".5"/>`;
    });
    // 라인 path
    if (series.length > 1) {
      const d = series.map((p,i)=>`${i===0?'M':'L'}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ');
      svg += `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
    }
    // 점 + 마지막 값 라벨
    series.forEach((p,i)=>{
      svg += `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="3.2" fill="${dotColor(p.v)}"/>`;
      if (p.t) svg += `<text x="${x(i).toFixed(1)}" y="${H-7}" text-anchor="middle" font-size="8" fill="var(--muted,#888)">${p.t}</text>`;
    });
    const last = series[series.length-1];
    svg += `<text x="${(x(series.length-1)).toFixed(1)}" y="${(y(last.v)-7).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="800" fill="${dotColor(last.v)}">${last.v.toFixed(1)}${unit}</text>`;
    svg += `</svg>`;

    const legend = band
      ? `<div style="display:flex;align-items:center;gap:10px;font-size:10px;color:var(--muted);margin-top:2px;">
           <span><span style="display:inline-block;width:10px;height:8px;background:rgba(31,122,77,.25);border-radius:2px;vertical-align:middle;"></span> ${band.label||'목표 범위'}</span>
           <span>● 정상 / ● 편차</span>
         </div>` : '';
    el.innerHTML = svg + legend;
  }
  global.BandChart = { render };
})(window);
