"""외부 데이터 통합 실행 스크립트.

사용법:
    # AIHub 데이터 통합 (파프리카 — 승인 후 압축 해제된 폴더 지정)
    python scripts/data_integration/run_integration.py \\
        --source aihub --crop 파프리카 \\
        --aihub-dir 기초자료/aihub/파프리카

    # Wageningen 방울토마토 다운로드 + 통합 (무료, 자동)
    python scripts/data_integration/run_integration.py \\
        --source wageningen --edition 2

    # KAMIS 가격 데이터 확인
    python scripts/data_integration/run_integration.py \\
        --source kamis --crop 딸기

    # 전체 통합 후 M2 모델 재학습
    python scripts/data_integration/run_integration.py \\
        --source all --retrain
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = ROOT / "기초자료"
OUT_DIR  = BASE_DIR / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"


def integrate_aihub(crop_ko: str, aihub_dir: Path) -> bool:
    """AIHub 데이터를 RDA 포맷으로 변환 후 기초자료 폴더에 병합."""
    from scripts.data_integration.aihub_adapter import convert_aihub_to_rda

    if not aihub_dir.exists():
        logger.error("AIHub 폴더 없음: %s", aihub_dir)
        logger.info("  → https://aihub.or.kr 에서 해당 작목 데이터셋 신청/다운로드 후")
        logger.info("    %s 에 압축 해제 후 재실행하세요.", aihub_dir)
        return False

    out_year_dir = OUT_DIR / "스마트팜_aihub"
    result = convert_aihub_to_rda(
        aihub_dir=aihub_dir,
        crop_ko=crop_ko,
        out_dir=out_year_dir,
    )

    if result["env"].empty and result["prod"].empty:
        logger.warning("[AIHub] 변환 결과 없음 — 폴더 구조 확인 필요")
        return False

    logger.info("[AIHub] 통합 완료 → %s", out_year_dir)
    return True


def integrate_wageningen(edition: int, force_download: bool = False) -> bool:
    """Wageningen 데이터 자동 다운로드 + 변환 + 기초자료 병합."""
    from scripts.data_integration.wageningen_adapter import download_and_convert

    wag_cache = BASE_DIR / "wageningen"
    _CROP_MAP = {1: "오이", 2: "방울토마토", 4: "완숙토마토"}
    crop_ko = _CROP_MAP.get(edition, "방울토마토")

    logger.info("[Wageningen] Edition %d (%s) 다운로드 + 변환 시작", edition, crop_ko)

    try:
        result = download_and_convert(
            edition=edition,
            out_dir=wag_cache,
            force=force_download,
        )
    except Exception as e:
        logger.error("[Wageningen] 다운로드 실패: %s", e)
        logger.info("  수동 다운로드 방법:")
        logger.info("  1. https://data.4tu.nl/ 방문")
        logger.info("  2. Edition %d zip 다운로드 → %s/ed%d/ 에 압축 해제", edition, wag_cache, edition)
        logger.info("  3. run_integration.py --source wageningen --edition %d 재실행", edition)
        return False

    # 생성된 CSV를 기초자료 폴더에 복사
    out_crop_dir = OUT_DIR / f"스마트팜_wag_ed{edition}"
    out_crop_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for key in ("env_monthly", "prod_monthly"):
        df = result.get(key, pd.DataFrame())
        if not df.empty:
            prefix = "환경" if "env" in key else "생산"
            out_path = out_crop_dir / f"{prefix}_wageningen_ed{edition}_{crop_ko}.csv"
            df.to_csv(out_path, index=False, encoding="utf-8-sig")
            logger.info("  저장: %s (%d행)", out_path.name, len(df))
            copied += 1

    if copied == 0:
        logger.warning("[Wageningen] 저장된 파일 없음")
        return False

    logger.info("[Wageningen] 통합 완료 → %s", out_crop_dir)
    return True


def show_kamis_prices(crop_ko: str) -> None:
    """KAMIS 현재 가격 및 월별 추이 출력."""
    from scripts.data_integration.kamis_api import KamisPriceClient

    client = KamisPriceClient()

    current = client.get_current_price(crop_ko)
    logger.info("[KAMIS] %s 현재 도매가: %.0f 원/kg", crop_ko, current)

    monthly = client.get_monthly_prices(crop_ko)
    if not monthly.empty:
        logger.info("[KAMIS] %s 월별 가격 (원/kg):", crop_ko)
        for _, row in monthly.iterrows():
            logger.info("  %d월: %,.0f원", int(row["month"]), row["price_krw_per_kg"])


def retrain_models(crops: list[str]) -> None:
    """지정 작목 M2 모델 재학습."""
    import subprocess

    for crop in crops:
        logger.info("[재학습] %s 시작...", crop)
        ret = subprocess.run(
            [sys.executable, "scripts/train_stage2_yield.py", "--crop", crop, "--no-cache"],
            cwd=str(ROOT), capture_output=False,
        )
        if ret.returncode != 0:
            logger.error("  재학습 실패: %s", crop)
        else:
            logger.info("  재학습 완료: %s", crop)


def main():
    parser = argparse.ArgumentParser(
        description="외부 데이터 통합 파이프라인",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", choices=["aihub", "wageningen", "kamis", "all"],
                        required=True)
    parser.add_argument("--crop", default="파프리카",
                        help="작목명 (aihub, kamis 소스에서 사용)")
    parser.add_argument("--aihub-dir", type=Path,
                        help="AIHub 압축 해제 폴더 경로")
    parser.add_argument("--edition", type=int, default=2,
                        help="Wageningen 데이터셋 버전 (1, 2, 4)")
    parser.add_argument("--force-download", action="store_true",
                        help="이미 있어도 재다운로드")
    parser.add_argument("--retrain", action="store_true",
                        help="통합 완료 후 M2 모델 재학습")
    parser.add_argument("--retrain-crops", nargs="+",
                        default=["딸기", "방울토마토", "완숙토마토", "참외", "파프리카"],
                        help="재학습 대상 작목")
    args = parser.parse_args()

    success_crops: list[str] = []

    if args.source in ("aihub", "all"):
        aihub_dir = args.aihub_dir or (BASE_DIR / "aihub" / args.crop)
        ok = integrate_aihub(args.crop, aihub_dir)
        if ok:
            success_crops.append(args.crop)

    if args.source in ("wageningen", "all"):
        editions = [1, 2, 4] if args.source == "all" else [args.edition]
        for ed in editions:
            integrate_wageningen(ed, args.force_download)

    if args.source in ("kamis", "all"):
        crops = args.retrain_crops if args.source == "all" else [args.crop]
        for crop in crops:
            show_kamis_prices(crop)

    if args.retrain and success_crops:
        retrain_models(success_crops)
    elif args.retrain:
        retrain_models(args.retrain_crops)


if __name__ == "__main__":
    main()
