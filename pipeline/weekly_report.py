"""주간 운영 리포트 — Smart Farm AI Platform.

매주 월요일 08:00 실행 → Slack + HTML 이메일로 운영 요약 발송.

포함 내용:
  1. 모델 성능 요약 (작물별 MAPE, R², 버전)
  2. KAMIS 도매가격 주간 동향 (등락률)
  3. ETL 파이프라인 상태 (신규 행 수, done 파일)
  4. 재학습 이력 (지난 7일)
  5. MQTT 연결 상태 요약

환경변수:
    SLACK_WEBHOOK_URL, NOTIFY_EMAIL_TO, SMTP_* (notifier.py와 공유)
    NOTIFY_ENV

사용:
    python -m pipeline.weekly_report
    python -m pipeline.weekly_report --dry-run
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT         = Path(__file__).parent.parent
ARTIFACTS    = ROOT / "models" / "artifacts"
REGISTRY     = ROOT / "models" / "registry.json"
STATE_FILE   = ROOT / "pipeline" / "state" / "new_rows_since_retrain.json"
RETRAIN_LOG  = ROOT / "pipeline" / "state" / "retrain_history.json"
KAMIS_CACHE  = ROOT / "api" / "data" / "kamis_price_cache.json"
ETL_DATA_DIR = Path(os.environ.get("ETL_DATA_DIR", str(ROOT / "etl_data")))
_ENV_NAME    = os.environ.get("NOTIFY_ENV", "production")

CROP_EN = {
    "딸기":       "strawberry",
    "완숙토마토":  "tomato",
    "방울토마토":  "cherry_tomato",
    "참외":        "melon",
    "파프리카":    "paprika",
    "오이":        "cucumber",
}


# ── 데이터 수집 ────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _collect_model_summary() -> list[dict]:
    """작물별 최신 활성 모델 지표 수집."""
    registry = _load_json(REGISTRY)
    rows = []
    for crop_ko, crop_en in CROP_EN.items():
        if crop_en == "cucumber":
            continue
        entry = registry.get(crop_en, {})
        active_num = entry.get("active_version")
        versions   = entry.get("versions", [])
        active_v   = next((v for v in versions if v["version"] == active_num), None)

        # pipeline_meta.json에서 추가 지표
        meta_path  = ARTIFACTS / crop_en / "pipeline_meta.json"
        meta       = _load_json(meta_path)
        s2         = meta.get("stage2", {})

        rows.append({
            "crop_ko":    crop_ko,
            "crop_en":    crop_en,
            "version":    active_num,
            "mape":       active_v.get("mape_stage2") if active_v else s2.get("mape"),
            "cv_r2":      active_v.get("cv_r2")       if active_v else s2.get("cv_r2_mean"),
            "gate":       s2.get("gate_passed", False),
            "n_train":    s2.get("n_train"),
            "updated_at": active_v.get("timestamp") if active_v else None,
        })
    return rows


def _collect_price_summary() -> list[dict]:
    """KAMIS 가격 캐시 + 7일 이력에서 주간 동향 계산."""
    cache = _load_json(KAMIS_CACHE)
    prices  = cache.get("prices", {})
    history = cache.get("history", {})
    rows = []

    today      = datetime.now(tz=timezone.utc).date()
    week_ago   = (today - timedelta(days=7)).isoformat()

    for crop_ko, crop_en in CROP_EN.items():
        if crop_en == "cucumber":
            continue
        current = prices.get(crop_ko)
        hist    = history.get(crop_ko, {})

        # 7일 전 가격 (가장 가까운 과거 날짜)
        past_dates = sorted(d for d in hist if d >= week_ago)
        price_7d_ago = hist.get(past_dates[0]) if past_dates else None

        delta_pct = None
        if current and price_7d_ago and price_7d_ago > 0:
            delta_pct = round((current - price_7d_ago) / price_7d_ago * 100, 1)

        rows.append({
            "crop_ko":     crop_ko,
            "price":       current,
            "price_7d_ago": price_7d_ago,
            "delta_pct":   delta_pct,
            "source":      cache.get("source", "rda_static"),
        })
    return rows


def _collect_pipeline_summary() -> dict:
    """파이프라인 상태 요약."""
    state = _load_json(STATE_FILE)
    env_rows  = int(state.get("new_env_rows",  0))
    prod_rows = int(state.get("new_prod_rows", 0))
    env_thresh  = int(os.environ.get("RETRAIN_ENV_ROWS",  "500"))
    prod_thresh = int(os.environ.get("RETRAIN_PROD_ROWS", "200"))

    done_dir  = ETL_DATA_DIR / "done"
    done_cnt  = len(list(done_dir.glob("*.csv"))) if done_dir.exists() else 0

    return {
        "env_rows":    env_rows,
        "prod_rows":   prod_rows,
        "env_thresh":  env_thresh,
        "prod_thresh": prod_thresh,
        "env_pct":     min(round(env_rows  / env_thresh  * 100, 1), 100.0),
        "prod_pct":    min(round(prod_rows / prod_thresh * 100, 1), 100.0),
        "done_files":  done_cnt,
        "last_updated": state.get("last_updated"),
    }


def _collect_retrain_history(days: int = 7) -> list[dict]:
    """최근 N일 재학습 이력 수집."""
    raw = _load_json(RETRAIN_LOG) if RETRAIN_LOG.exists() else []
    if not isinstance(raw, list):
        return []

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    recent = [ev for ev in raw if ev.get("timestamp", "") >= cutoff]
    return recent[-20:]


# ── 보고서 포맷 ────────────────────────────────────────────────────────────────

def _fmt_price(p: Optional[float]) -> str:
    return f"{p:,.0f}원/kg" if p is not None else "—"


def _delta_emoji(pct: Optional[float]) -> str:
    if pct is None: return "➡️"
    if pct >  3: return "📈"
    if pct < -3: return "📉"
    return "➡️"


def _gate_emoji(ok: bool) -> str:
    return "✅" if ok else "❌"


def build_slack_blocks(
    models: list[dict],
    prices: list[dict],
    pipeline: dict,
    retrain: list[dict],
    report_ts: str,
) -> tuple[str, list]:
    env = _ENV_NAME
    week_str = datetime.now(tz=timezone.utc).strftime("%Y년 %m월 %d일")
    text = f"📊 [{env}] 주간 운영 리포트 — {week_str}"

    # ── 모델 성능 ─────────────────────────────────────────────────────────────
    model_lines = []
    for m in models:
        mape_str = f"{m['mape']:.1f}%" if m['mape'] is not None else "—"
        r2_str   = f"{m['cv_r2']:.3f}" if m['cv_r2']  is not None else "—"
        gate     = _gate_emoji(m['gate'])
        ver_str  = f"v{m['version']}" if m['version'] else "—"
        model_lines.append(
            f"• *{m['crop_ko']}* ({ver_str}) MAPE={mape_str} R²={r2_str} {gate}"
        )

    # ── 가격 동향 ─────────────────────────────────────────────────────────────
    price_lines = []
    for p in prices:
        em    = _delta_emoji(p["delta_pct"])
        delta = f"{p['delta_pct']:+.1f}%" if p["delta_pct"] is not None else ""
        price_lines.append(
            f"• *{p['crop_ko']}*  {_fmt_price(p['price'])}  {em} {delta}"
        )

    # ── 파이프라인 ────────────────────────────────────────────────────────────
    env_bar  = "█" * int(pipeline["env_pct"]  / 10) + "░" * (10 - int(pipeline["env_pct"]  / 10))
    prod_bar = "█" * int(pipeline["prod_pct"] / 10) + "░" * (10 - int(pipeline["prod_pct"] / 10))
    retrain_cnt = len(retrain)

    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"📊 [{env}] 주간 운영 리포트 — {week_str}"}},
        {"type": "divider"},

        # 모델 성능
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": "*🤖 모델 성능 (작물별 최신 버전)*\n" + "\n".join(model_lines)}},
        {"type": "divider"},

        # 가격 동향
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": "*💰 도매가격 동향 (KAMIS, 전주 대비)*\n" + "\n".join(price_lines)}},
        {"type": "divider"},

        # 파이프라인 상태
        {"type": "section",
         "fields": [
             {"type": "mrkdwn",
              "text": f"*📦 파이프라인 상태*\n"
                      f"환경 데이터: `{env_bar}` {pipeline['env_rows']}/{pipeline['env_thresh']}행\n"
                      f"생산량 데이터: `{prod_bar}` {pipeline['prod_rows']}/{pipeline['prod_thresh']}행"},
             {"type": "mrkdwn",
              "text": f"*📁 처리 완료 CSV*\n{pipeline['done_files']}개\n\n"
                      f"*🔄 지난 7일 재학습*\n{retrain_cnt}건"},
         ]},
        {"type": "divider"},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                        "text": f"생성 시각: {report_ts} | Smart Farm AI Platform"}]},
    ]
    return text, blocks


def build_html_email(
    models: list[dict],
    prices: list[dict],
    pipeline: dict,
    retrain: list[dict],
    report_ts: str,
) -> str:
    env = _ENV_NAME
    week_str = datetime.now(tz=timezone.utc).strftime("%Y년 %m월 %d일")

    def _row_color(mape):
        if mape is None: return "#1a1d2e"
        return "#0d2b1a" if mape <= 60 else "#2b1a0d" if mape <= 100 else "#2b0d0d"

    model_rows = ""
    for m in models:
        mape_str = f"{m['mape']:.1f}%" if m['mape'] is not None else "—"
        r2_str   = f"{m['cv_r2']:.3f}"  if m['cv_r2']  is not None else "—"
        gate     = "✅ PASS" if m['gate'] else "❌ FAIL"
        ver_str  = f"v{m['version']}" if m['version'] else "—"
        bg       = _row_color(m['mape'])
        model_rows += f"""
<tr style="background:{bg}">
  <td style="padding:8px 12px;color:#e2e8f0">{m['crop_ko']}</td>
  <td style="padding:8px 12px;color:#8892a4">{ver_str}</td>
  <td style="padding:8px 12px;color:#e2e8f0">{mape_str}</td>
  <td style="padding:8px 12px;color:#e2e8f0">{r2_str}</td>
  <td style="padding:8px 12px">{gate}</td>
</tr>"""

    price_rows = ""
    for p in prices:
        em    = _delta_emoji(p["delta_pct"])
        delta = f"{p['delta_pct']:+.1f}%" if p["delta_pct"] is not None else "—"
        color = "#3ecf8e" if (p["delta_pct"] or 0) > 0 else "#f2645a" if (p["delta_pct"] or 0) < 0 else "#8892a4"
        price_rows += f"""
<tr>
  <td style="padding:8px 12px;color:#e2e8f0">{p['crop_ko']}</td>
  <td style="padding:8px 12px;color:#e2e8f0">{_fmt_price(p['price'])}</td>
  <td style="padding:8px 12px;color:#8892a4">{_fmt_price(p['price_7d_ago'])}</td>
  <td style="padding:8px 12px;color:{color}">{em} {delta}</td>
</tr>"""

    retrain_rows = ""
    for ev in retrain[-5:]:
        ts     = ev.get("timestamp", "")[:16].replace("T", " ")
        crops  = ", ".join(ev.get("crops", []))
        by     = ev.get("triggered_by", "")
        retrain_rows += f"""
<tr>
  <td style="padding:6px 12px;color:#8892a4">{ts}</td>
  <td style="padding:6px 12px;color:#4f8ef7">{crops}</td>
  <td style="padding:6px 12px;color:#8892a4">{by}</td>
</tr>"""
    if not retrain_rows:
        retrain_rows = '<tr><td colspan="3" style="padding:8px 12px;color:#8892a4">지난 7일 재학습 없음</td></tr>'

    th_style = "padding:8px 12px;text-align:left;color:#8892a4;font-size:11px;text-transform:uppercase;border-bottom:1px solid #2a2d3e"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8">
<title>Smart Farm 주간 리포트 — {week_str}</title>
</head>
<body style="background:#0f1117;color:#e2e8f0;font-family:'Segoe UI',sans-serif;margin:0;padding:24px">
<div style="max-width:700px;margin:0 auto">

<h1 style="color:#4f8ef7;font-size:22px;margin-bottom:4px">📊 Smart Farm 주간 리포트</h1>
<p style="color:#8892a4;font-size:13px;margin-bottom:28px">{env} · {week_str} · {report_ts}</p>

<!-- 모델 성능 -->
<h2 style="font-size:16px;color:#e2e8f0;margin-bottom:12px">🤖 모델 성능</h2>
<table style="width:100%;border-collapse:collapse;background:#1a1d2e;border-radius:8px;overflow:hidden;margin-bottom:28px">
<tr><th style="{th_style}">작물</th><th style="{th_style}">버전</th>
    <th style="{th_style}">MAPE</th><th style="{th_style}">R²</th>
    <th style="{th_style}">게이트</th></tr>
{model_rows}
</table>

<!-- 가격 동향 -->
<h2 style="font-size:16px;color:#e2e8f0;margin-bottom:12px">💰 도매가격 (KAMIS)</h2>
<table style="width:100%;border-collapse:collapse;background:#1a1d2e;border-radius:8px;overflow:hidden;margin-bottom:28px">
<tr><th style="{th_style}">작물</th><th style="{th_style}">현재가</th>
    <th style="{th_style}">7일 전</th><th style="{th_style}">변동</th></tr>
{price_rows}
</table>

<!-- 파이프라인 상태 -->
<h2 style="font-size:16px;color:#e2e8f0;margin-bottom:12px">📦 파이프라인 상태</h2>
<div style="background:#1a1d2e;border-radius:8px;padding:16px;margin-bottom:28px">
  <div style="margin-bottom:10px">
    <span style="color:#8892a4;font-size:12px">환경 데이터</span>
    <div style="background:#2a2d3e;border-radius:4px;height:8px;margin-top:4px">
      <div style="background:#4f8ef7;width:{pipeline['env_pct']}%;height:8px;border-radius:4px"></div>
    </div>
    <span style="font-size:12px;color:#e2e8f0">{pipeline['env_rows']} / {pipeline['env_thresh']} 행 ({pipeline['env_pct']}%)</span>
  </div>
  <div>
    <span style="color:#8892a4;font-size:12px">생산량 데이터</span>
    <div style="background:#2a2d3e;border-radius:4px;height:8px;margin-top:4px">
      <div style="background:#3ecf8e;width:{pipeline['prod_pct']}%;height:8px;border-radius:4px"></div>
    </div>
    <span style="font-size:12px;color:#e2e8f0">{pipeline['prod_rows']} / {pipeline['prod_thresh']} 행 ({pipeline['prod_pct']}%)</span>
  </div>
  <p style="font-size:12px;color:#8892a4;margin-top:12px">처리 완료 CSV: <strong style="color:#e2e8f0">{pipeline['done_files']}개</strong></p>
</div>

<!-- 재학습 이력 -->
<h2 style="font-size:16px;color:#e2e8f0;margin-bottom:12px">🔄 지난 7일 재학습 이력</h2>
<table style="width:100%;border-collapse:collapse;background:#1a1d2e;border-radius:8px;overflow:hidden;margin-bottom:28px">
<tr><th style="{th_style}">시각</th><th style="{th_style}">작물</th><th style="{th_style}">트리거</th></tr>
{retrain_rows}
</table>

<p style="font-size:11px;color:#4a5568;text-align:center;margin-top:24px">
Smart Farm AI Platform · 자동 생성 리포트 · {report_ts}
</p>
</div>
</body>
</html>"""


# ── 발송 ──────────────────────────────────────────────────────────────────────

def send_report(dry_run: bool = False) -> None:
    """주간 리포트 데이터 수집 후 Slack + 이메일 발송."""
    from pipeline.notifier import _send_slack, _send_email

    report_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("[weekly] 주간 리포트 생성 시작 — %s", report_ts)

    # 데이터 수집
    models   = _collect_model_summary()
    prices   = _collect_price_summary()
    pipeline = _collect_pipeline_summary()
    retrain  = _collect_retrain_history(days=7)

    logger.info("[weekly] 모델 %d개, 가격 %d개, 재학습 %d건",
                len(models), len(prices), len(retrain))

    # Slack 발송
    slack_text, blocks = build_slack_blocks(models, prices, pipeline, retrain, report_ts)
    if dry_run:
        print("=== [DRY-RUN] Slack 메시지 ===")
        print(slack_text)
        for b in blocks:
            if b.get("type") == "section":
                t = b.get("text", {})
                if t:
                    print(t.get("text", ""))
    else:
        ok = _send_slack(slack_text, blocks)
        logger.info("[weekly] Slack 발송 %s", "OK" if ok else "SKIP(설정 없음)")

    # HTML 이메일 발송
    html_body  = build_html_email(models, prices, pipeline, retrain, report_ts)
    week_str   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    subject    = f"[Smart Farm] 주간 운영 리포트 — {week_str}"
    plain_body = f"Smart Farm 주간 리포트 ({week_str})\n\n" \
                 f"모델: {len(models)}개 작목, 재학습: {len(retrain)}건\n" \
                 f"파이프라인: 환경 {pipeline['env_pct']}%, 생산량 {pipeline['prod_pct']}%"

    if dry_run:
        print("\n=== [DRY-RUN] 이메일 제목 ===")
        print(subject)
        print("\n=== HTML 미리보기 (앞 500자) ===")
        print(html_body[:500])
    else:
        ok = _send_email(subject, html_body, plain_body)
        logger.info("[weekly] 이메일 발송 %s", "OK" if ok else "SKIP(설정 없음)")

    logger.info("[weekly] 주간 리포트 완료")


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

def _main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Smart Farm 주간 리포트 발송")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 발송 없이 리포트 내용 출력")
    args = parser.parse_args()
    send_report(dry_run=args.dry_run)


if __name__ == "__main__":
    _main()
