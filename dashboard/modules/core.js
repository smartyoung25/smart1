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
async function apiFetch(path, opts = {}) {
  let r;
  try {
    r = await fetch(`${_apiBase}${path}`, {
      ...opts,
      headers: { Authorization: `Bearer ${_token}`, ...(opts.headers||{}) },
      signal: AbortSignal.timeout(15000),
    });
  } catch(netErr) {
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
