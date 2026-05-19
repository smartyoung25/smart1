"""notifier.py 단위 테스트 — Slack/이메일 외부 호출을 mock으로 대체."""
from __future__ import annotations

import importlib
import json
import os
from unittest.mock import MagicMock, patch


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _reload_notifier(env: dict):
    """환경변수를 교체 후 notifier 모듈을 재로드."""
    with patch.dict(os.environ, env, clear=False):
        import pipeline.notifier as n
        importlib.reload(n)
        return n


# ── Slack 비활성화 (SLACK_WEBHOOK_URL 미설정) ─────────────────────────────────

class TestSlackDisabled:
    def test_no_url_returns_false(self):
        env = {"SLACK_WEBHOOK_URL": "", "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        result = n._send_slack("hello")
        assert result is False

    def test_notify_etl_error_does_not_raise(self):
        env = {"SLACK_WEBHOOK_URL": "", "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        # 외부 호출 없이 조용히 반환돼야 함
        n.notify_etl_error(farm_id="farm_001", error_msg="some error", filename="test.csv")

    def test_notify_retrain_does_not_raise(self):
        env = {"SLACK_WEBHOOK_URL": "", "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        n.notify_retrain(crop="tomato", success=True, mape_before=8.2, mape_after=5.1)

    def test_notify_threshold_does_not_raise(self):
        env = {"SLACK_WEBHOOK_URL": "", "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        n.notify_threshold(env_rows=550, prod_rows=0, env_threshold=500, prod_threshold=200)


# ── Slack 활성화 (URL 설정, HTTP mock) ────────────────────────────────────────

class TestSlackEnabled:
    FAKE_URL = "https://hooks.slack.com/test"

    def _make_mock_response(self, status=200, body=b"ok"):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_send_slack_calls_urlopen(self):
        env = {"SLACK_WEBHOOK_URL": self.FAKE_URL, "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
            result = n._send_slack("test message")
        assert result is True
        mock_open.assert_called_once()

    def test_send_slack_posts_json(self):
        env = {"SLACK_WEBHOOK_URL": self.FAKE_URL, "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        captured = {}
        def fake_urlopen(req, timeout=None):
            captured["data"] = json.loads(req.data.decode())
            return self._make_mock_response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            n._send_slack("hello slack")

        assert "text" in captured["data"] or "blocks" in captured["data"]

    def test_send_slack_returns_false_on_http_error(self):
        import urllib.error
        env = {"SLACK_WEBHOOK_URL": self.FAKE_URL, "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = n._send_slack("fail")
        assert result is False

    def test_notify_retrain_sends_message(self):
        env = {"SLACK_WEBHOOK_URL": self.FAKE_URL, "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
            n.notify_retrain(crop="lettuce", success=True, mape_before=7.0, mape_after=4.5)
        mock_open.assert_called_once()

    def test_notify_etl_error_sends_message(self):
        env = {"SLACK_WEBHOOK_URL": self.FAKE_URL, "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        with patch("urllib.request.urlopen", return_value=self._make_mock_response()) as mock_open:
            n.notify_etl_error(farm_id="f1", error_msg="ETL 실패", filename="data.csv")
        mock_open.assert_called_once()


# ── 이메일 비활성화 ───────────────────────────────────────────────────────────

class TestEmailDisabled:
    def test_empty_recipients_returns_false(self):
        env = {"SLACK_WEBHOOK_URL": "", "NOTIFY_EMAIL_TO": ""}
        n = _reload_notifier(env)
        result = n._send_email("subject", "<p>body</p>", "body")
        assert result is False


# ── 이메일 활성화 (SMTP mock) ─────────────────────────────────────────────────

class TestEmailEnabled:
    def test_send_email_calls_smtp(self):
        env = {
            "SLACK_WEBHOOK_URL": "",
            "NOTIFY_EMAIL_TO":   "ops@example.com",
            "SMTP_HOST":         "smtp.example.com",
            "SMTP_PORT":         "587",
            "SMTP_USER":         "user@example.com",
            "SMTP_PASSWORD":     "secret",
            "SMTP_FROM":         "farm@example.com",
        }
        n = _reload_notifier(env)

        mock_smtp_instance = MagicMock()
        mock_smtp_cls = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("smtplib.SMTP", mock_smtp_cls):
            result = n._send_email("Test Subject", "<p>hello</p>", "hello")

        assert result is True
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once()
        mock_smtp_instance.sendmail.assert_called_once()
