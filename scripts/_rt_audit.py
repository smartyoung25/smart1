# -*- coding: utf-8 -*-
"""읽기전용 런타임 점검 — 전 화면 로드 시 콘솔에러·실패 네트워크 수집(클릭/쓰기 없음)."""
import os, glob, json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
screens = sorted(os.path.basename(p) for p in glob.glob("screens/*.html"))

report = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width":390,"height":844}, device_scale_factor=1, locale="ko-KR")
    for name in screens:
        page = ctx.new_page()
        errs, neterr = [], []
        page.on("pageerror", lambda e: errs.append(str(e).split("\n")[0][:160]))
        page.on("console", lambda m: errs.append("console.error: "+m.text[:140]) if m.type=="error" else None)
        def on_resp(r):
            try:
                if r.status >= 400 and ("/api/" in r.url or r.url.endswith(".js") or r.url.endswith(".css")):
                    neterr.append(f"{r.status} {r.request.method} {r.url.replace(BASE,'')[:90]}")
            except Exception: pass
        page.on("response", on_resp)
        url = BASE + "/screens/" + name
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            try: page.goto(url, wait_until="load", timeout=20000)
            except Exception as e:
                report.append((name, ["GOTO FAIL "+str(e)[:80]], [])); page.close(); continue
        page.wait_for_timeout(2200)
        # 중복 제거
        report.append((name, sorted(set(errs)), sorted(set(neterr))))
        page.close()
    browser.close()

print("== 런타임 점검 결과 (콘솔에러 / 4xx·5xx) ==\n")
clean = 0
for name, errs, neterr in report:
    if not errs and not neterr:
        clean += 1; continue
    print(f"■ {name}")
    for e in errs:    print("   JS:", e)
    for n in neterr:  print("   NET:", n)
print(f"\n정상(에러 없음): {clean}/{len(report)} · 문제 화면: {len(report)-clean}")
