"""이메일 발송 유틸 — SMTP 환경변수 주입 시 실발송, 미설정 시 안전 스텁.

환경변수:
  SMTP_HOST, SMTP_PORT(기본 587), SMTP_USER, SMTP_PASSWORD(=SMTP_PASS),
  SMTP_FROM(기본 SMTP_USER), SMTP_TLS(기본 true)

미설정이면 send_email 은 발송하지 않고 (False, 사유) 를 반환한다.
→ 호출부에서 '이메일 미설정' 을 정직하게 안내할 수 있다.
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _smtp_pass() -> str:
    # .env 는 SMTP_PASSWORD, 일부 환경은 SMTP_PASS — 둘 다 허용
    return os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS") or ""


def is_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER")
                and _smtp_pass())


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """이메일 발송. (성공여부, 메시지) 반환. SMTP 미설정 시 (False, '미설정')."""
    if not is_configured():
        logger.info("[mailer] SMTP 미설정 — 발송 생략 (to=%s, subj=%s)", to, subject)
        return False, "SMTP 미설정"

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    pwd  = _smtp_pass()
    sender = os.environ.get("SMTP_FROM") or user
    if not sender or sender == "smartfarm@localhost":
        sender = user   # 기본 플레이스홀더면 발신자=계정
    use_tls = os.environ.get("SMTP_TLS", "true").lower() in ("1", "true", "yes")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            if use_tls:
                s.starttls()
            s.login(user, pwd)
            s.sendmail(sender, [to], msg.as_string())
        logger.info("[mailer] 발송 완료 to=%s", to)
        return True, "발송 완료"
    except Exception as e:
        logger.error("[mailer] 발송 실패: %s", e)
        return False, f"발송 실패: {e}"
