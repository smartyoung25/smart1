// ── AI 상담 플로팅 ────────────────────────────────────────────────────────────
function toggleChat() {
  const panel = $('chat-panel');
  if (!panel) return;
  panel.classList.toggle('open');
  if (panel.classList.contains('open')) {
    populateSelectWithFarms('chat-farm-sel');
    $('chat-input')?.focus();
  }
}

function clearChat() {
  _chatHistory = [];
  _chatFarmId  = '';
  const msgs = $('chat-messages');
  if (msgs) {
    msgs.innerHTML = `<div class="chat-msg ai">
      <div class="chat-who">SMART FARM AI</div>
      안녕하세요! 재배 환경, 수확량 예측, 관수 관리에 대해 무엇이든 물어보세요.
    </div>`;
  }
}

async function sendChat() {
  const input  = $('chat-input');
  const sendBtn= $('chat-send');
  const msgs   = $('chat-messages');
  const farmId = $('chat-farm-sel')?.value || '';
  const text   = input?.value.trim();
  if (!text || !msgs) return;

  const target = farmId || (_farmsData[0]?.farm_id || 'farm_001');
  if (target !== _chatFarmId) {
    _chatHistory = [];
    _chatFarmId  = target;
  }

  const userDiv = document.createElement('div');
  userDiv.className = 'chat-msg user';
  userDiv.textContent = text;
  msgs.appendChild(userDiv);
  msgs.scrollTop = msgs.scrollHeight;

  input.value = '';
  if (sendBtn) sendBtn.disabled = true;

  const loadDiv = document.createElement('div');
  loadDiv.className = 'chat-msg ai';
  loadDiv.innerHTML = '<div class="chat-who">SMART FARM AI</div><div class="spinner" style="width:18px;height:18px;border-width:2px"></div>';
  msgs.appendChild(loadDiv);
  msgs.scrollTop = msgs.scrollHeight;

  _chatHistory.push({ role: 'user', content: text });
  if (_chatHistory.length > 20) _chatHistory = _chatHistory.slice(-20);

  try {
    const d = await apiFetch(`/api/farms/${target}/chat`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: text, history: _chatHistory.slice(0, -1) }),
    });
    const reply = d.reply || d.message || d.response || JSON.stringify(d);
    _chatHistory.push({ role: 'assistant', content: reply });

    const whoDiv = document.createElement('div');
    whoDiv.className = 'chat-who';
    whoDiv.textContent = 'SMART FARM AI';
    const replyDiv = document.createElement('div');
    replyDiv.style.whiteSpace = 'pre-wrap';
    replyDiv.textContent = reply;
    loadDiv.innerHTML = '';
    loadDiv.appendChild(whoDiv);
    loadDiv.appendChild(replyDiv);

    if (d.model_used && d.model_used !== 'stub-v1' && d.model_used !== 'rule_based') {
      const metaSpan = document.createElement('div');
      metaSpan.style.cssText = 'font-size:9px;color:var(--muted);margin-top:4px';
      metaSpan.textContent = '모델: ' + d.model_used;
      loadDiv.appendChild(metaSpan);
    }
    if (d.referenced_data && d.referenced_data.length) {
      const refSpan = document.createElement('div');
      refSpan.style.cssText = 'font-size:9px;color:var(--muted)';
      refSpan.textContent = '참조: ' + d.referenced_data.join(', ');
      loadDiv.appendChild(refSpan);
    }
    const suggs = d.suggestions || [];
    if (suggs.length) {
      const suggsWrap = document.createElement('div');
      suggsWrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;margin-top:6px';
      suggs.forEach(s => {
        const btn = document.createElement('button');
        btn.className = 'chat-sugg-chip';
        btn.textContent = s;
        btn.addEventListener('click', () => {
          const inp = $('chat-input');
          if (inp) { inp.value = s; inp.focus(); }
        });
        suggsWrap.appendChild(btn);
      });
      loadDiv.appendChild(suggsWrap);
    }
    _refreshChatQuota();
  } catch(e) {
    const { msg: _em, action: _ea } = _errReason(e);
    const _special = e.code === 402
      ? '💳 현재 플랜에서는 AI 채팅을 사용할 수 없습니다. 설정 탭에서 업그레이드하세요.'
      : e.code === 429
      ? '⏳ 이번 달 AI 채팅 쿼터를 모두 사용했습니다. 다음 달 초 초기화됩니다.'
      : null;
    loadDiv.innerHTML = `<div class="chat-who">SMART FARM AI</div>
      <span style="color:var(--red)">${_special || _em}</span>
      ${_ea && !_special ? `<span style="color:var(--muted);font-size:11px;display:block;margin-top:4px">${_esc(_ea)}</span>` : ''}`;
    if (_chatHistory.length && _chatHistory[_chatHistory.length-1].role === 'user') {
      _chatHistory.pop();
    }
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    msgs.scrollTop = msgs.scrollHeight;
    input?.focus();
  }
}
