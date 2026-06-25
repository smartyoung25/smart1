# -*- coding: utf-8 -*-
"""시도명 정규화 — 약칭·개편 전후 표기를 정식 17개 시도명으로 통일.

farm_registry에 "충남"·"충청남도"가 혼재 저장되어 클러스터 집계 시 별도 행으로
중복 집계되던 문제를 집계 시점 정규화로 해소(원본 데이터는 보존).

단일 소스 — api/main.py serve_regions(), api/services/cluster_overview.py 공용.
"""
from __future__ import annotations

# 2글자 약칭 → 정식 시도명(2026 행정구역 기준)
_CANON: dict[str, str] = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
    "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도",
}

# 정식 시도명 표시 순서(중복 제거)
SIDO_ORDER: list[str] = list(dict.fromkeys(_CANON.values()))


def _base(sido: str) -> str | None:
    """임의 시도 표기 → 2글자 약칭 키. ('충청남도'·'충남'·'충청남' → '충남')"""
    s = (sido or "").replace("특별자치도", "").replace("특별자치시", "") \
        .replace("특별시", "").replace("광역시", "").replace("도", "")
    if s.startswith("충청"):   s = "충" + s[2:3]
    elif s.startswith("전라"): s = "전" + s[2:3]
    elif s.startswith("경상"): s = "경" + s[2:3]
    return s[:2] if s else None


def canonical_sido(sido: str, default: str = "미상") -> str:
    """약칭·정식·개편 전후 표기를 정식 17개 시도명으로 통일.

    유효 시도는 닫힌 17개 집합이므로, 매핑 불가 값(빈값·플레이스홀더 '—'·영문/테스트
    표기 등)은 모두 default('미상')로 통합한다. 가짜 지역 행 난립 방지.
    """
    return _CANON.get(_base(sido) or "", default)


def canonical_sido_or_none(sido: str) -> str | None:
    """정식 17개 시도에 매핑되는 경우만 정식명 반환, 그 외(미지·빈값)는 None.

    행정구역 트리(시군구) 구성처럼 '정식 시도만 채택'해야 하는 경로용.
    """
    return _CANON.get(_base(sido) or "")
