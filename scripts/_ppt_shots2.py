# -*- coding: utf-8 -*-
"""7단계 로드맵용 추가 화면 스크린샷 캡처."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = os.path.join("out", "ppt_shots")
os.makedirs(OUT, exist_ok=True)

SHOTS = [
    ("/screens/c17_diagnosis.html", "c17_diagnosis"),
    ("/screens/c18_checklist.html", "c18_checklist"),
    ("/screens/c21_apply.html",     "c21_apply"),
    ("/screens/c2_consent.html",    "c2_consent"),
    ("/screens/c16_equipment.html", "c16_equipment"),
    ("/screens/c4_diagnosis.html",  "c4_diagnosis"),
    ("/screens/help.html",          "help"),
    ("/screens/c9_benchmark.html",  "c9_benchmark"),
    ("/screens/c10_roi.html",       "c10_roi"),
]

ok = 0
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              device_scale_factor=2, locale="ko-KR")
    page = ctx.new_page()
    for path, name in SHOTS:
        url = BASE + path
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            try: page.goto(url, wait_until="load", timeout=20000)
            except Exception as e:
                print("FAIL goto", name, str(e)[:60]); continue
        page.wait_for_timeout(2600)
        try:
            page.screenshot(path=os.path.join(OUT, name + ".png"))
            ok += 1; print("OK", name)
        except Exception as e:
            print("FAIL shot", name, str(e)[:60])
    browser.close()
print(f"\n캡처 {ok}/{len(SHOTS)}")
