"""Smart Farm — 운영 알림 모듈 (Slack 웹훅 + SMTP 이메일 + SMS + 카카오 알림톡)

환경변수:
    SLACK_WEBHOOK_URL   : Slack Incoming Webhook URL (없으면 비활성화)
    NOTIFY_EMAIL_TO     : 수신 이메일 (쉼표 구분 가능)
    SMTP_HOST           : SMTP 서버 호스트 (기본: localhost)
    SMTP_PORT           : SMTP 포트 (기본: 587)
    SMTP_USER           : SMTP 인증 사용자명 (없으면 인증 생략)
    SMTP_PASSWORD       : SMTP 패스워드
    SMTP_FROM           : 발신 이메일 (기본: smartfarm@localhost)
    NOTIFY_ENV          : 환경 이름 — 메시지에 포함 (기본: production)

    # SMS / 카카오 알림톡 (CoolSMS)
    COOLSMS_API_KEY     : CoolSMS API Key
    COOLSMS_API_SECRET  : CoolSMS API Secret
    NOTIFY_PHONE_FROM   : 발신 번호 (등록된 번호, 예: 01012345678)
    NOTIFY_PHONE_TO     : 수신 번호 목록 (쉼표 구분, 예: 01011112222,01033334444)
    KAKAO_PFID          : 카카오 플러스친구 ID (알림톡용, 없으면 SMS 대체)
    KAKAO_TEMPLATE_ID   : 카카오 알림톡 템플릿 코드

사용 예:
    from pipeline.notifier import notify_retrain, notify_etl_error, notify_threshold
    from pipeline.notifier import notify_crop_advice

    notify_retrain(crop="딸기", success=True, mape_before=58.2, mape_after=51.4)
    notify_etl_error(farm_id="farm001", error_msg="CSV 파싱 실패")
    notify_threshold(env_rows=520, prod_rows=80, env_threshold=500)
    notify_crop_advice(farm_id="farm_001", crop_ko="딸기", advices=[...])
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import smtplib
import time
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 환경변수 읽기 ─────────────────────────────────────────────────────────────
_SLACK_URL    = os.environ.get("SLACK_WEBHOOK_URL", "")
_EMAIL_TO     = [e.strip() for e in os.environ.get("NOTIFY_EMAIL_TO", "").split(",") if e.strip()]
_SMTP_HOST    = os.environ.get("SMTP_HOST", "localhost")
_SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
_SMTP_USER    = os.environ.get("SMTP_USER", "")
_SMTP_PASS    = os.environ.get("SMTP_PASSWORD", "")
_SMTP_FROM    = os.environ.get("SMTP_FROM", "smartfarm@localhost")
_ENV_NAME     = os.environ.get("NOTIFY_ENV", "production")

# SMS / 카카오 알림톡 (CoolSMS)
_COOLSMS_KEY    = os.environ.get("COOLSMS_API_KEY", "")
_COOLSMS_SECRET = os.environ.get("COOLSMS_API_SECRET", "")
_PHONE_FROM     = os.environ.get("NOTIFY_PHONE_FROM", "")
_PHONE_TO       = [p.strip() for p in os.environ.get("NOTIFY_PHONE_TO", "").split(",") if p.strip()]
_KAKAO_PFID     = os.environ.get("KAKAO_PFID", "")
_KAKAO_TPL_ID   = os.environ.get("KAKAO_TEMPLATE_ID", "")


# ── CoolSMS HMAC 서명 ────────────────────────────────────────────────────────

def _coolsms_auth_header() -> dict:
    """CoolSMS REST API HMAC-SHA256 인증 헤더 생성."""
    date    = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    salt    = os.urandom(16).hex()
    msg     = f"{date}{salt}".encode()
    sig     = hmac.new(_COOLSMS_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"HMAC-SHA256 apiKey={_COOLSMS_KEY}, date={date}, salt={salt}, signature={sig}",
        "Content-Type":  "application/json",
    }


# ── 저수준 전송 함수 ──────────────────────────────────────────────────────────

def _send_sms(text: str) -> bool:
    """CoolSMS REST API로 SMS 일괄 발송. 수신자 없거나 키 없으면 False."""
    if not (_COOLSMS_KEY and _COOLSMS_SECRET and _PHONE_FROM and _PHONE_TO):
        return False

    messages = [
        {"to": num, "from": _PHONE_FROM, "text": text[:90], "type": "SMS"}
        for num in _PHONE_TO
    ]
    payload = json.dumps({"messages": messages}).encode()
    try:
        req = urllib.request.Request(
            "https://api.coolsms.co.kr/messages/v4/send-many",
            data=payload, headers=_coolsms_auth_header(), method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 201)
            if not ok:
                logger.warning("[notifier] SMS 전송 실패: HTTP %d", resp.status)
            return ok
    except Exception as e:
        logger.warning("[notifier] SMS 오류: %s", e)
        return False


def _send_kakao(text: str, template_vars: dict | None = None) -> bool:
    """CoolSMS 알림톡 발송. KAKAO_PFID·KAKAO_TEMPLATE_ID 없으면 SMS 대체.

    카카오 알림톡은 사전 승인된 템플릿만 사용 가능합니다.
    템플릿 미등록 시 자동으로 SMS로 전환합니다.
    """
    if not (_COOLSMS_KEY and _COOLSMS_SECRET and _PHONE_FROM and _PHONE_TO):
        return False

    # 알림톡 템플릿 미설정 시 SMS 대체
    if not (_KAKAO_PFID and _KAKAO_TPL_ID):
        logger.info("[notifier] 카카오 알림톡 미설정 — SMS 대체 발송")
        return _send_sms(text)

    messages = [
        {
            "to":   num,
            "from": _PHONE_FROM,
            "type": "ATA",          # 알림톡
            "kakaoOptions": {
                "pfId":        _KAKAO_PFID,
                "templateId":  _KAKAO_TPL_ID,
                "variables":   template_vars or {},
                "disableSms":  False,   # 알림톡 실패 시 SMS 자동 대체
            },
        }
        for num in _PHONE_TO
    ]
    payload = json.dumps({"messages": messages}).encode()
    try:
        req = urllib.request.Request(
            "https://api.coolsms.co.kr/messages/v4/send-many",
            data=payload, headers=_coolsms_auth_header(), method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 201)
            if not ok:
                logger.warning("[notifier] 알림톡 전송 실패: HTTP %d", resp.status)
            return ok
    except Exception as e:
        logger.warning("[notifier] 알림톡 오류: %s → SMS 대체", e)
        return _send_sms(text)


def _send_slack(text: str, blocks: list | None = None) -> bool:
    """Slack Incoming Webhook으로 메시지 전송. 실패 시 False 반환."""
    if not _SLACK_URL:
        return False
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            _SLACK_URL, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            if not ok:
                logger.warning("[notifier] Slack 전송 실패: HTTP %d", resp.status)
            return ok
    except Exception as e:
        logger.warning("[notifier] Slack 오류: %s", e)
        return False


def _send_email(subject: str, body_html: str, body_text: str) -> bool:
    """SMTP로 이메일 전송. 수신자 없거나 실패 시 False 반환."""
    if not _EMAIL_TO:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = _SMTP_FROM
        msg["To"]      = ", ".join(_EMAIL_TO)
        msg.attach(MIMEText(body_text, "plain",  "utf-8"))
        msg.attach(MIMEText(body_html, "html",   "utf-8"))

        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            if _SMTP_PORT == 587:
                smtp.starttls()
            if _SMTP_USER:
                smtp.login(_SMTP_USER, _SMTP_PASS)
            smtp.sendmail(_SMTP_FROM, _EMAIL_TO, msg.as_string())
        logger.info("[notifier] 이메일 전송 완료 → %s", _EMAIL_TO)
        return True
    except Exception as e:
        logger.warning("[notifier] 이메일 오류: %s", e)
        return False


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ── 공개 알림 함수 ────────────────────────────────────────────────────────────

def notify_retrain(
    crop: str,
    success: bool,
    mape_before: float | None = None,
    mape_after:  float | None = None,
    duration_s:  float | None = None,
    error_msg:   str   | None = None,
) -> None:
    """재학습 완료/실패 알림."""
    icon   = "✅" if success else "❌"
    status = "완료" if success else "실패"
    env    = _ENV_NAME

    # ── Slack ────────────────────────────────────────────────────────────────
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{icon} [{env}] {crop} 재학습 {status}"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*작물*\n{crop}"},
                {"type": "mrkdwn", "text": f"*환경*\n{env}"},
                {"type": "mrkdwn", "text": f"*시각*\n{_ts()}"},
                {"type": "mrkdwn", "text": f"*소요*\n{f'{duration_s:.0f}초' if duration_s else '—'}"},
            ],
        },
    ]

    if success and mape_before is not None and mape_after is not None:
        delta = mape_before - mape_after
        arrow = "↓" if delta > 0 else "↑"
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*MAPE (이전)*\n{mape_before:.1f}%"},
                {"type": "mrkdwn", "text": f"*MAPE (이후)*\n{mape_after:.1f}% {arrow}{abs(delta):.1f}%p"},
            ],
        })
    elif not success and error_msg:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*오류*\n```{error_msg[:300]}```"},
        })

    slack_text = f"{icon} [{env}] {crop} 재학습 {status} ({_ts()})"
    _send_slack(slack_text, blocks)

    # ── 이메일 ───────────────────────────────────────────────────────────────
    subject = f"[Smart Farm] {crop} 재학습 {status} — {_ts()}"
    if success:
        mape_info = (
            f"MAPE: {mape_before:.1f}% → {mape_after:.1f}%"
            if mape_before is not None and mape_after is not None else ""
        )
        body_text = f"{crop} 재학습이 완료됐습니다.\n{mape_info}\n시각: {_ts()}"
        body_html = f"""<h2>{icon} {crop} 재학습 완료</h2>
<p>{mape_info}</p><p>시각: {_ts()} | 환경: {env}</p>"""
    else:
        body_text = f"{crop} 재학습이 실패했습니다.\n오류: {error_msg or '—'}\n시각: {_ts()}"
        body_html = f"""<h2>{icon} {crop} 재학습 실패</h2>
<pre>{error_msg or '—'}</pre><p>시각: {_ts()} | 환경: {env}</p>"""
    _send_email(subject, body_html, body_text)

    logger.info("[notifier] 재학습 알림 발송 — %s %s", crop, status)


def notify_etl_error(
    farm_id:   str,
    error_msg: str,
    filename:  str | None = None,
) -> None:
    """ETL 처리 오류 알림."""
    env = _ENV_NAME
    label = f"`{filename}`" if filename else f"farm={farm_id}"

    slack_text = f"⚠️ [{env}] ETL 오류 — {label} ({_ts()})"
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"⚠️ [{env}] ETL 처리 오류"}},
        {"type": "divider"},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*농가 ID*\n{farm_id}"},
             {"type": "mrkdwn", "text": f"*파일*\n{filename or '—'}"},
             {"type": "mrkdwn", "text": f"*시각*\n{_ts()}"},
             {"type": "mrkdwn", "text": f"*환경*\n{env}"},
         ]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*오류 내용*\n```{error_msg[:300]}```"}},
    ]
    _send_slack(slack_text, blocks)

    subject = f"[Smart Farm] ETL 오류 — {farm_id} ({_ts()})"
    body_text = f"ETL 오류 발생\n농가: {farm_id}\n파일: {filename or '—'}\n오류: {error_msg}\n시각: {_ts()}"
    body_html = f"""<h2>⚠️ ETL 오류</h2>
<p>농가: {farm_id} | 파일: {filename or '—'} | 시각: {_ts()}</p>
<pre>{error_msg}</pre>"""
    _send_email(subject, body_html, body_text)

    logger.info("[notifier] ETL 오류 알림 발송 — farm=%s", farm_id)


def notify_threshold(
    env_rows:       int,
    prod_rows:      int,
    env_threshold:  int,
    prod_threshold: int,
) -> None:
    """재학습 임계값 초과 알림 (재학습 시작 전 사전 알림)."""
    env = _ENV_NAME
    triggered = []
    if env_rows  >= env_threshold:  triggered.append(f"환경 데이터 {env_rows}/{env_threshold}행")
    if prod_rows >= prod_threshold: triggered.append(f"생산량 데이터 {prod_rows}/{prod_threshold}행")
    reason = ", ".join(triggered)

    slack_text = f"🔁 [{env}] 재학습 트리거 — {reason} ({_ts()})"
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🔁 [{env}] 자동 재학습 트리거"}},
        {"type": "divider"},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*트리거 사유*\n{reason}"},
             {"type": "mrkdwn", "text": f"*시각*\n{_ts()}"},
         ]},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                        "text": "재학습이 시작됩니다. 완료 후 결과 알림이 전송됩니다."}]},
    ]
    _send_slack(slack_text, blocks)

    subject = f"[Smart Farm] 자동 재학습 트리거 — {reason}"
    body_text = f"재학습 트리거 발동\n사유: {reason}\n시각: {_ts()}"
    body_html = f"<h2>🔁 자동 재학습 트리거</h2><p>사유: {reason}</p><p>시각: {_ts()}</p>"
    _send_email(subject, body_html, body_text)

    logger.info("[notifier] 임계값 초과 알림 발송 — %s", reason)


def notify_sensor_anomaly(
    farm_id:   str,
    anomalies: list[dict],
    ts:        str | None = None,
) -> None:
    """IoT 센서 이상값 감지 즉시 알림.

    Args:
        farm_id:   농장 ID
        anomalies: [{"field": "temp_internal", "value": 65.0, "range": (-5, 55)}, ...]
        ts:        센서 타임스탬프 (ISO-8601)
    """
    if not anomalies:
        return

    env = _ENV_NAME
    detected_at = ts or _ts()

    # 이상값 요약 텍스트
    anom_lines = "\n".join(
        f"  • {a['field']}: {a['value']} (정상 범위 {a['range'][0]}~{a['range'][1]})"
        for a in anomalies
    )

    slack_text = f"🚨 [{env}] {farm_id} 센서 이상값 감지 — {len(anomalies)}개 항목"
    fields = []
    for a in anomalies:
        fields.append({
            "type": "mrkdwn",
            "text": f"*{a['field']}*\n{a['value']} (정상 {a['range'][0]}~{a['range'][1]})",
        })

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"🚨 [{env}] 센서 이상값 감지"}},
        {"type": "divider"},
        {"type": "section",
         "fields": [
             {"type": "mrkdwn", "text": f"*농장*\n{farm_id}"},
             {"type": "mrkdwn", "text": f"*감지 시각*\n{detected_at}"},
         ]},
    ]
    # 이상값 항목 (최대 10개)
    for i in range(0, min(len(fields), 10), 2):
        chunk = fields[i:i+2]
        blocks.append({"type": "section", "fields": chunk})

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn",
                       "text": "센서 장치 상태를 즉시 확인하세요."}],
    })
    _send_slack(slack_text, blocks)

    subject = f"[Smart Farm] {farm_id} 센서 이상값 — {len(anomalies)}개 항목"
    body_text = f"농장: {farm_id}\n감지 시각: {detected_at}\n이상값:\n{anom_lines}"
    body_html = f"""
<h2>🚨 센서 이상값 감지</h2>
<p><strong>농장:</strong> {farm_id}</p>
<p><strong>감지 시각:</strong> {detected_at}</p>
<h3>이상 항목</h3>
<ul>
{"".join(f"<li><strong>{a['field']}</strong>: {a['value']} (정상 {a['range'][0]}~{a['range'][1]})</li>" for a in anomalies)}
</ul>
<p style="color:#888;font-size:12px">센서 장치 상태를 즉시 확인하세요.</p>
"""
    _send_email(subject, body_html, body_text)

    logger.warning("[notifier] 이상값 알림 발송 — farm=%s 항목=%d", farm_id, len(anomalies))


def notify_crop_advice(
    farm_id:  str,
    crop_ko:  str,
    advices:  list[dict],
    ts:       str | None = None,
) -> None:
    """작물 재배 최적화 권고 알림 — 이메일 + SMS + 카카오 알림톡.

    이상값(센서 고장 의심)과 달리, 작물 생육에 불리한 환경을 감지해
    구체적인 조정 권고를 농가에 전달합니다.

    Args:
        farm_id : 농장 ID
        crop_ko : 작물명 (한국어)
        advices : [{"field":"temp_internal","value":28.5,"optimal":(20,26),"action":"차광막 점검"}, ...]
        ts      : 센서 타임스탬프 (ISO-8601)
    """
    if not advices:
        return

    env          = _ENV_NAME
    detected_at  = ts or _ts()
    n            = len(advices)

    # ── 메시지 본문 구성 ──────────────────────────────────────────────────────
    advice_lines = "\n".join(
        f"  • {a['field']}: {a['value']} → 최적 {a['optimal'][0]}~{a['optimal'][1]} | 권고: {a['action']}"
        for a in advices
    )
    sms_body = (
        f"[스마트팜] {farm_id} {crop_ko} 재배 권고\n"
        f"감지: {detected_at[:16]}\n"
        + "\n".join(
            f"{a['field']} {a['value']}→{a['optimal'][0]}~{a['optimal'][1]} {a['action']}"
            for a in advices[:3]          # SMS는 90자 제한으로 3개까지
        )
    )

    # ── 이메일 ───────────────────────────────────────────────────────────────
    subject   = f"[Smart Farm] {farm_id} {crop_ko} 재배 환경 조정 권고 — {_ts()}"
    body_text = (
        f"농장: {farm_id} | 작물: {crop_ko}\n"
        f"감지 시각: {detected_at}\n\n"
        f"권고 사항 ({n}개):\n{advice_lines}\n\n"
        "자동으로 생성된 권고입니다. 실제 조치 전 현장 상태를 확인하세요."
    )
    rows_html = "".join(
        f"""<tr>
          <td style="padding:8px 12px;border-bottom:1px solid #2a2d3e">{a['field']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #2a2d3e;color:#f5c842">{a['value']}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #2a2d3e;color:#3ecf8e">{a['optimal'][0]} ~ {a['optimal'][1]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #2a2d3e">{a['action']}</td>
        </tr>"""
        for a in advices
    )
    body_html = f"""
<div style="font-family:sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;border-radius:10px">
  <h2 style="color:#f5c842;margin-bottom:4px">🌿 재배 환경 조정 권고</h2>
  <p style="color:#8892a4;font-size:13px">농장: <strong>{farm_id}</strong> | 작물: <strong>{crop_ko}</strong> | 감지: {detected_at}</p>
  <table style="width:100%;border-collapse:collapse;margin-top:16px;font-size:13px">
    <thead>
      <tr style="background:#1a1d2e">
        <th style="padding:8px 12px;text-align:left;color:#8892a4">항목</th>
        <th style="padding:8px 12px;text-align:left;color:#8892a4">현재값</th>
        <th style="padding:8px 12px;text-align:left;color:#8892a4">최적 범위</th>
        <th style="padding:8px 12px;text-align:left;color:#8892a4">권고 조치</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="color:#8892a4;font-size:11px;margin-top:16px">자동으로 생성된 권고입니다. 실제 조치 전 현장 상태를 확인하세요.</p>
</div>"""

    # ── 카카오 알림톡 템플릿 변수 (승인된 템플릿과 일치해야 함) ─────────────────
    kakao_vars = {
        "#{farm_id}":   farm_id,
        "#{crop}":      crop_ko,
        "#{count}":     str(n),
        "#{summary}":   "\n".join(f"{a['field']}: {a['value']} → {a['action']}" for a in advices[:3]),
        "#{ts}":        detected_at[:16],
    }

    # ── 발송 ────────────────────────────────────────────────────────────────
    _send_email(subject, body_html, body_text)
    _send_kakao(sms_body[:300], template_vars=kakao_vars)

    logger.info("[notifier] 재배 권고 알림 발송 — farm=%s crop=%s 항목=%d", farm_id, crop_ko, n)
