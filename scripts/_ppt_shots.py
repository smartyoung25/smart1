# -*- coding: utf-8 -*-
"""소개서용 화면 스크린샷 캡처 (playwright, 모바일 뷰포트)."""
import os, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = os.path.join("out", "ppt_shots")
os.makedirs(OUT, exist_ok=True)

# (파일경로, 저장명, 설명) — 인트로/네비/핵심 화면
SHOTS = [
    ("/intro",                       "intro",      "랜딩(소개)"),
    ("/smartos",                     "smartos",    "화면 네비게이터"),
    ("/screens/c3_home.html",        "c3_home",    "통합 홈"),
    ("/screens/g1_home.html",        "g1_home",    "온실 홈"),
    ("/screens/g2_env.html",         "g2_env",     "환경관리 전략"),
    ("/screens/g3_period.html",      "g3_period",  "관수 P1~P6"),
    ("/screens/g4_growth.html",      "g4_growth",  "생육·수확량 예측"),
    ("/screens/g5_disease.html",     "g5_disease", "병해 조기경보"),
    ("/screens/f1_field.html",       "f1_field",   "노지 관리"),
    ("/screens/c5_erp.html",         "c5_erp",     "경영·ERP 분석"),
    ("/screens/c12_joint.html",      "c12_joint",  "공동출하"),
    ("/screens/c14_report.html",     "c14_report", "월간 경영성과 리포트"),
    ("/screens/c22_tiers.html",      "c22_tiers",  "등급 비교"),
    ("/screens/c20_cluster_admin.html","c20_cluster","클러스터 관제"),
    ("/screens/c13_chat.html",       "c13_chat",   "AI 영농비서"),
    ("/screens/c8_interop.html",     "c8_interop", "이기종 장비 통합"),
]

results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              device_scale_factor=2, locale="ko-KR")
    page = ctx.new_page()
    for path, name, desc in SHOTS:
        url = BASE + path
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            try: page.goto(url, wait_until="load", timeout=20000)
            except Exception as e:
                print("FAIL goto", name, str(e)[:80]); continue
        page.wait_for_timeout(2600)   # 토큰·차트·데이터 렌더 대기
        out = os.path.join(OUT, name + ".png")
        try:
            page.screenshot(path=out)   # 뷰포트(폰 화면 1면)
            results.append((name, desc, out))
            print("OK", name)
        except Exception as e:
            print("FAIL shot", name, str(e)[:80])
    browser.close()

print(f"\n캡처 완료: {len(results)}/{len(SHOTS)}")
