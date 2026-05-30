// ── 전역 상태 ─────────────────────────────────────────────────────────────────
let _token   = sessionStorage.getItem('sf_token') || '';
let _apiBase = sessionStorage.getItem('sf_api') ||
  (location.protocol !== 'file:' ? location.origin : 'http://localhost:8000');

let _myFarmId  = sessionStorage.getItem('sf_farm_id') || '';
let _myTier    = sessionStorage.getItem('sf_tier')    || 'basic';
let _planCache = null;
let _featCache = {};
let _chatHistory = [];
let _chatFarmId  = '';

// 로그인 폼 API URL 초기화
{ const _el = document.getElementById('login-api-url'); if (_el) _el.value = _apiBase; }

// ── JWT 디코드 ────────────────────────────────────────────────────────────────
function _decodeJwt(token) {
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(b64));
  } catch { return {}; }
}

// ── getElementById 단축 ───────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

// ── 폼 결과 메시지 헬퍼 ──────────────────────────────────────────────────────
function _setResult(elId, status, msg) {
  const el = $(elId);
  if (!el) return;
  // form-feedback 클래스 패턴 지원 (새 디자인)
  if (el.classList.contains('form-feedback')) {
    const icon = status === 'ok' ? '✅' : status === 'err' ? '❌' : '⚠️';
    el.className = `form-feedback ${status}`;
    el.textContent = `${icon} ${msg}`;
    if (status === 'ok') setTimeout(() => { el.className = 'form-feedback'; }, 5000);
    return;
  }
  // 레거시 패턴
  const cls = status === 'ok' ? 'result-ok' : status === 'err' ? 'result-err' : 'result-warn';
  el.innerHTML = `<span class="${cls}">${_esc(msg)}</span>`;
}

// ── API 헬퍼 ─────────────────────────────────────────────────────────────────
// GET 요청 중복 취소: 같은 path로 진행 중인 요청이 있으면 이전 요청 abort
const _inflightGet = new Map();

async function apiFetch(path, opts = {}) {
  const isGet = !opts.method || opts.method.toUpperCase() === 'GET';
  let controller;
  if (isGet) {
    if (_inflightGet.has(path)) _inflightGet.get(path).abort();
    controller = new AbortController();
    _inflightGet.set(path, controller);
  }

  let r;
  try {
    const timeoutSignal = AbortSignal.timeout(15000);
    const signal = isGet
      ? (controller.signal.aborted ? timeoutSignal
          : (typeof AbortSignal.any === 'function'
            ? AbortSignal.any([controller.signal, timeoutSignal])
            : timeoutSignal))
      : timeoutSignal;
    r = await fetch(`${_apiBase}${path}`, {
      ...opts,
      headers: { Authorization: `Bearer ${_token}`, ...(opts.headers||{}) },
      signal,
    });
    if (isGet) _inflightGet.delete(path);
  } catch(netErr) {
    if (isGet) _inflightGet.delete(path);
    if (netErr.name === 'AbortError') {
      const e = new Error('요청 취소됨');
      e.code = 'ABORTED';
      throw e;
    }
    const e = new Error(netErr.name === 'TimeoutError' ? '응답 시간 초과 (15초)' : '서버에 연결할 수 없음');
    e.code = netErr.name === 'TimeoutError' ? 'TIMEOUT' : 'NETWORK';
    e.cause = netErr;
    throw e;
  }
  if (r.status === 401) { doLogout(); const e = new Error('인증 만료'); e.code = 401; throw e; }
  if (!r.ok) {
    let detail = '';
    try {
      const errBody = await r.json();
      detail = errBody.detail || errBody.message || errBody.msg || '';
      if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    } catch (_) {}
    const e = new Error(detail ? `HTTP ${r.status}: ${detail}` : `HTTP ${r.status}`);
    e.code = r.status;
    throw e;
  }
  return r.json();
}

// ── HTML 특수문자 이스케이프 ──────────────────────────────────────────────────
function _esc(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── API 오류 → 사용자 친화적 한국어 원인 + 조치 안내 ───────────────────────
function _errReason(e) {
  if (!e) return { msg: '알 수 없는 오류', action: null };
  const code = e.code;
  if (code === 'ABORTED')  return { msg: '', action: null };
  if (code === 'NETWORK')  return { msg: '🔴 서버에 연결할 수 없습니다', action: 'API 서버(uvicorn)가 실행 중인지 확인하세요.' };
  if (code === 'TIMEOUT')  return { msg: '⏱️ 응답 시간 초과 (15초)', action: '서버 부하 또는 네트워크 문제. 잠시 후 새로고침하세요.' };
  if (code === 401)        return { msg: '🔑 로그인 세션이 만료되었습니다', action: null };
  if (code === 403)        return { msg: '🔒 이 기능은 상위 구독 등급이 필요합니다', action: '설정 탭에서 플랜 업그레이드를 확인하세요.' };
  if (code === 404)        return { msg: '📭 데이터가 없습니다', action: '농장이 등록되었는지, 센서 데이터가 수집 중인지 확인하세요.' };
  if (code === 422)        return { msg: '⚠️ 요청 파라미터 오류', action: '농장 선택 후 다시 시도하세요.' };
  if (code === 500)        return { msg: '🔧 서버 내부 오류가 발생했습니다', action: '잠시 후 재시도하거나 관리자에게 문의하세요.' };
  return { msg: `⚠️ 오류: ${_esc(e.message)}`, action: null };
}

// ── 에러 박스 HTML ────────────────────────────────────────────────────────────
function _errBoxHtml(e, contextTitle = '데이터 조회 실패') {
  if (e?.code === 'ABORTED') return '';   // 중복 요청 취소 — 조용히 무시
  const { msg, action } = _errReason(e);
  return `<div class="data-err-box">
    <span>❌ ${contextTitle}</span>
    <span class="data-err-reason">${msg}</span>
    ${action ? `<span class="data-err-reason" style="color:var(--muted)">${action}</span>` : ''}
  </div>`;
}

// ── null 값 이유 박스 HTML ────────────────────────────────────────────────────
function _nullReasonHtml(nullFields) {
  if (!nullFields || !nullFields.length) return '';
  return `<div class="data-reason-box">
    <span class="data-reason-title">ℹ️ 일부 수치가 표시되지 않는 이유</span>
    ${nullFields.map(([label, reason]) =>
      `<span class="data-reason-item">· <strong>${label}</strong>: ${reason}</span>`
    ).join('')}
  </div>`;
}

// ── 토스트 알림 ───────────────────────────────────────────────────────────────
function showAnomalyToast(msg) {
  const toast = $('anomaly-toast');
  toast.textContent = `🚨 ${msg.farm_id} 이상값 감지`;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 5000);
}

let _toastTimer = null;
function showToast(msg, durationMs = 3000) {
  let el = $('general-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'general-toast';
    el.style.cssText = [
      'position:fixed', 'bottom:80px', 'left:50%', 'transform:translateX(-50%)',
      'background:rgba(30,35,50,.96)', 'color:#fff', 'padding:10px 20px',
      'border-radius:10px', 'font-size:13px', 'font-weight:600',
      'z-index:500', 'box-shadow:0 4px 16px rgba(0,0,0,.4)',
      'opacity:0', 'transition:opacity .2s', 'pointer-events:none',
      'max-width:320px', 'text-align:center',
    ].join(';');
    document.body.appendChild(el);
  }
  const isOk  = msg.startsWith('✅');
  const isErr = msg.startsWith('❌');
  el.style.borderLeft = isOk ? '3px solid var(--green)' : isErr ? '3px solid var(--red)' : '3px solid var(--accent)';
  el.textContent = msg;
  el.style.opacity = '1';
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.opacity = '0'; }, durationMs);
}

// ── UI 헬퍼 ──────────────────────────────────────────────────────────────────
function setText(id, val) { const el = $(id); if (el) el.textContent = val; }
function setBar(barId, pct, valId, label) {
  const b = $(barId); if (b) b.style.width = Math.min(100, pct) + '%';
  if (valId) { const v = $(valId); if (v) v.textContent = label != null ? label : pct + '%'; }
}

// ── 숫자 카운터 애니메이션 ─────────────────────────────────────────────────────
// el: DOM element, to: 목표값, opts: {decimals, unit, duration, suffix}
function animateNumber(el, to, opts = {}) {
  if (!el) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const d = opts.decimals ?? 0;
    const raw = d > 0 ? to.toFixed(d) : Math.round(to);
    el.textContent = (opts.format === 'locale' ? Math.round(to).toLocaleString('ko-KR') : raw) + (opts.suffix || '');
    return;
  }
  const from = parseFloat(el.textContent.replace(/[^0-9.\-]/g, '')) || 0;
  const dur  = opts.duration ?? 500;
  const dec  = opts.decimals ?? 0;
  const sfx  = opts.suffix || '';
  const start = performance.now();
  const isLocale = opts.format === 'locale';
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const step = (now) => {
    const t = Math.min((now - start) / dur, 1);
    const v = from + (to - from) * easeOut(t);
    const raw = dec > 0 ? v.toFixed(dec) : Math.round(v);
    el.textContent = (isLocale ? Math.round(v).toLocaleString('ko-KR') : raw) + sfx;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── VPD 계산 (kPa) ─────────────────────────────────────────────────────────
// 포화수증기압 Tetens: 0.6108 × exp(17.27 × T / (T + 237.3))
function calcVpd(tempC, humidityPct) {
  if (tempC == null || humidityPct == null) return null;
  const svp = 0.6108 * Math.exp(17.27 * tempC / (tempC + 237.3));
  const vpd = svp * (1 - humidityPct / 100);
  return Math.max(0, vpd);
}

// ── VPD 상태 등급 반환 ─────────────────────────────────────────────────────
function vpdStatus(vpd) {
  if (vpd === null) return 'none';
  if (vpd < 0.3 || vpd > 2.0) return 'critical';
  if (vpd < 0.5 || vpd > 1.5) return 'warning';
  return 'optimal';
}

// ── 알림 배지 업데이트 ─────────────────────────────────────────────────────
// sectionId: 'dashboard'|'environ'|'control' 등
// count: 알림 수
function setNavBadge(sectionId, count) {
  // 사이드바 nav-item 배지
  const navBtn = document.querySelector(`.nav-item[onclick*="'${sectionId}'"]`);
  if (navBtn) {
    let badge = navBtn.querySelector('.nav-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'nav-badge';
      navBtn.appendChild(badge);
    }
    badge.textContent = count > 99 ? '99+' : count;
    badge.dataset.count = count;
    badge.style.display = count > 0 ? '' : 'none';
  }
  // 하단 탭 bn-tab 배지
  const bnTab = document.querySelector(`#bn-${sectionId}, .bn-tab[data-section="sec-${sectionId}"]`);
  if (bnTab) {
    let badge = bnTab.querySelector('.nav-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'nav-badge';
      bnTab.appendChild(badge);
    }
    badge.textContent = count > 99 ? '99+' : count;
    badge.dataset.count = count;
    badge.style.display = count > 0 ? '' : 'none';
  }
}

// ── 스켈레톤 ON/OFF 헬퍼 ──────────────────────────────────────────────────
function skelOn(el)  { if (el) el.classList.add('skeleton'); }
function skelOff(el) { if (el) el.classList.remove('skeleton'); }

// ── 공통 Empty State HTML ─────────────────────────────────────────────────
// icon: 이모지 문자열, title: 짧은 제목, desc: 부제목(옵션), actionHtml: 버튼(옵션)
function _emptyHtml(icon = '📭', title = '데이터 없음', desc = '', actionHtml = '') {
  return `<div class="empty-state">
    <div class="empty-state-icon">${icon}</div>
    <div class="empty-state-title">${_esc(title)}</div>
    ${desc ? `<div class="empty-state-desc">${_esc(desc)}</div>` : ''}
    ${actionHtml || ''}
  </div>`;
}
