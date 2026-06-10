# -*- coding: utf-8 -*-
"""엣지 러너 — 농장 게이트웨이에서 야간 실행: 로컬 보정 산출 → 파라미터만 업로드.

원본(실수확·환경)은 농장 로컬 파일에서만 읽고, 서버로는 스칼라 파라미터만 전송한다.

사용:
    python -m pipeline.federated.edge_runner \
        --crop_en strawberry --crop_ko 딸기 \
        --farm_id 경남_거창_051 --records local_yield.json \
        --server http://localhost:8000 --token <JWT>

local_yield.json 형식(농장 내부 파일): [{"actual": 7.0, "pred": 5.8}, ...]
--dry_run 이면 업로드 없이 페이로드만 출력.
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request

from pipeline.federated.local_correction import compute_local_correction


def _post(server: str, token: str, body: dict) -> dict:
    req = urllib.request.Request(
        server.rstrip("/") + "/api/federated/correction",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop_en", required=True)
    ap.add_argument("--crop_ko", default="")
    ap.add_argument("--farm_id", required=True)
    ap.add_argument("--records", required=True, help="농장 로컬 (actual,pred) JSON")
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--token", default="")
    ap.add_argument("--dry_run", action="store_true")
    a = ap.parse_args(argv)

    with open(a.records, encoding="utf-8") as f:
        recs = json.load(f)
    pairs = [(r["actual"], r["pred"]) for r in recs if "actual" in r and "pred" in r]
    payload = compute_local_correction(a.farm_id, pairs)   # 원본은 여기서만 사용
    body = {"crop_en": a.crop_en, "crop_ko": a.crop_ko, "corrections": [payload]}

    print("로컬 산출 페이로드(업로드 대상, 원본 미포함):", json.dumps(payload, ensure_ascii=False))
    if a.dry_run or not a.token:
        print("dry_run/토큰 없음 — 업로드 생략")
        return 0
    res = _post(a.server, a.token, body)
    print("서버 병합 결과:", json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
