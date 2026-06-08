# -*- coding: utf-8 -*-
"""KAASA SmartOS 스모크 테스트 — 회귀 자동 감지.
점검: (1) 핵심 백엔드 라우트 200  (2) 전 화면 콘솔에러 0  (3) 모든 링크 실제해석 200
      (4) 쓰기 경로(가입·관수·활동·기자재) 200
사용: python scripts/smoke_test.py   (서버가 :8000 에서 실행 중이어야 함)
종료코드 0=통과, 1=실패 (CI 연동 가능)
"""
import sys, glob, os, re, json, urllib.request, urllib.error, random
from urllib.parse import urljoin
B = "http://localhost:8000"
FAILS = []
def fail(msg): FAILS.append(msg); print("  ✗", msg)
def ok(msg):   print("  ✓", msg)

def tok():
    r = urllib.request.urlopen(urllib.request.Request(f"{B}/api/v1/auth/token",
        data=json.dumps({"username":"admin","password":"1250"}).encode(),
        headers={"Content-Type":"application/json"}), timeout=10)
    return json.load(r)["access_token"]

def http(path, method="GET", body=None, T=None):
    h = {"Content-Type":"application/json"}
    if T: h["Authorization"] = "Bearer "+T
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = urllib.request.urlopen(urllib.request.Request(f"{B}{path}", data=data, headers=h, method=method), timeout=15)
        return r.status
    except urllib.error.HTTPError as e: return e.code
    except Exception as e: return f"ERR:{type(e).__name__}"

def main():
    try: T = tok()
    except Exception as e: print("토큰 발급 실패 — 서버 미기동?", e); return 1

    print("[1] 핵심 백엔드 라우트")
    for p in ["/intro","/smartos","/index.html",
              "/api/farms/farm_001/environment","/api/farms/farm_001/diagnosis",
              "/api/farms/farm_001/report/monthly","/api/farms/farm_001/irrigation/analysis?days=7",
              "/api/farms/farm_001/billing/plan","/api/farms/farm_001/equipment","/api/farms/farm_001/activity/summary"]:
        s = http(p, T=T); (ok if s==200 else fail)(f"{p} → {s}")

    print("[2] 쓰기 경로")
    u = f"smoke_{random.randint(10000,99999)}"
    cases = [
        ("회원가입", "/api/v1/auth/register", {"username":u,"password":"abcd","name":"QA","email":""}, None),
        ("관수기록", "/api/farms/farm_001/irrigation", {"crop":"오이","date":"2026-06-04","slab_vol_l":15,"max_wt_kg":14.8,"sunset_wt_kg":13.5,"min_wt_kg":11.5,"periods":[{"period":3,"supply_ml":400,"drain_ml":120,"ec":3.2,"ph":6.0}]}, T),
        ("활동적재", "/api/farms/farm_001/activity", {"kind":"irrigation","item":"smoke","value":8,"detail":"smoke"}, T),
        ("기자재",   "/api/farms/farm_smoke/equipment", {"device_id":"S-1","category":"sensor","device_type":"온습도","maker":"QA","protocol":"MQTT","datapoints":[{"tag":"t","canonical_name":"temp_internal"}]}, T),
    ]
    for name, p, b, tk in cases:
        s = http(p, "POST", b, tk); (ok if s==200 else fail)(f"{name} {p} → {s}")

    print("[3] 화면 콘솔에러 + 링크 실제해석 (Playwright)")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  (playwright 미설치 — 화면 검사 건너뜀)")
        return 1 if FAILS else 0
    routes = ["/","/smartos","/intro"] + [f"/screens/{os.path.basename(p)}" for p in sorted(glob.glob("screens/*.html"))]
    seen = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page()
        cerr_total = 0; broken = 0
        for rt in routes:
            ce = []
            h = lambda m, e=ce: (e.append(m.text) if m.type=="error" else None)
            pg.on("console", h)
            try: pg.goto(B+rt, wait_until="load"); pg.wait_for_timeout(1200)
            except Exception as ex: fail(f"PAGE_LOAD {rt}: {ex}")
            hrefs = pg.eval_on_selector_all("a[href]", "e=>e.map(x=>x.getAttribute('href'))")
            clicks = pg.eval_on_selector_all("[onclick]", "e=>e.map(x=>x.getAttribute('onclick'))")
            raw = set(x for x in hrefs if x and not x.startswith(('javascript:','#','mailto:')))
            for oc in clicks:
                for m in re.findall(r"location\.href=['\"]([^'\"]+)['\"]", oc or ""): raw.add(m)
            for link in raw:
                if link.endswith(('.html','/')) or link in ('/smartos','/intro','/','/index.html'):
                    uurl = urljoin(B+rt, link)
                    if uurl.startswith(B):
                        if uurl not in seen: seen[uurl] = http(uurl.replace(B,""))
                        if seen[uurl] != 200: broken += 1; fail(f"링크 {rt} → {link} = {seen[uurl]}")
            pg.remove_listener("console", h)
            if ce: cerr_total += len(ce); fail(f"콘솔에러 {rt}: {ce[:2]}")
        br.close()
        if cerr_total == 0: ok(f"전 {len(routes)}화면 콘솔에러 0")
        if broken == 0:     ok(f"전 링크({len(seen)}) HTTP 200")
    return 1 if FAILS else 0

if __name__ == "__main__":
    code = main()
    print("\n" + ("✅ 스모크 테스트 통과" if code == 0 else f"🔴 실패 {len(FAILS)}건"))
    # smoke 데모 데이터 정리
    try: os.remove("api/data/equipment/farm_smoke.json")
    except Exception: pass
    sys.exit(code)
