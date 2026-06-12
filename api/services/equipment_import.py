"""견적서/시방서 파일 → 기자재 초안 목록 파서.

지원: .xlsx/.xls/.csv(pandas·openpyxl), .pdf(pdfplumber 텍스트/표),
      이미지/스캔(pytesseract OCR — 테서랙트 바이너리 있을 때만).
반환: {"items":[{device_type,maker,model,protocol,category,qty,raw}], "source":..., "note":...}
※ 저장은 하지 않음(초안). 사용자가 C16에서 검토·수정 후 일괄 등록.
"""
from __future__ import annotations

import io
import logging
import re

logger = logging.getLogger(__name__)

# 헤더 키워드 → 표준 필드 매핑 (한/영 혼용 휴리스틱)
_COLMAP = {
    "device_type": ["품명", "품목", "장비", "기자재", "자재명", "name", "item", "설비", "규격명"],
    "maker":       ["제조사", "제조", "메이커", "maker", "manufacturer", "브랜드", "brand"],
    "model":       ["모델", "형식", "모델명", "model", "규격", "spec", "사양"],
    "protocol":    ["프로토콜", "통신", "protocol", "interface", "통신방식"],
    "qty":         ["수량", "qty", "ea", "개수", "수 량"],
}
_PROTO_HINT = ["modbus", "bacnet", "mqtt", "rs485", "rs-485", "rs232", "tcp", "opc", "can"]


def _cell(v) -> str:
    """셀값 안전 변환 — None/NaN(float)/'nan' → ''."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and v != v:   # NaN
            return ""
    except Exception:
        pass
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _norm(s) -> str:
    return re.sub(r"\s+", "", _cell(s)).lower()


def _match_field(header: str) -> str | None:
    h = _norm(header)
    for field, kws in _COLMAP.items():
        if any(_norm(k) in h for k in kws):
            return field
    return None


def _rows_to_items(rows: list[dict]) -> list[dict]:
    """행(dict, 표준필드 키) 리스트 → 기자재 초안. 수량>1이면 안내만(복제는 프론트)."""
    items = []
    for r in rows:
        dt = _cell(r.get("device_type"))
        if not dt:
            continue
        proto = _cell(r.get("protocol"))
        if not proto:  # model/규격에서 프로토콜 힌트 추출
            blob = _norm(r.get("model", "")) + _norm(dt)
            for p in _PROTO_HINT:
                if p in blob:
                    proto = p.upper(); break
        try:
            qty = int(float(_cell(r.get("qty")) or 1))
        except Exception:
            qty = 1
        items.append({
            "device_type": dt[:64],
            "maker": _cell(r.get("maker"))[:64],
            "model": _cell(r.get("model"))[:64],
            "protocol": proto[:40],
            "category": "",
            "qty": max(1, qty),
        })
    return items


def _parse_table(df) -> list[dict]:
    """pandas DataFrame → 표준필드 행. 헤더 자동 매핑."""
    colmap = {}
    for c in df.columns:
        f = _match_field(str(c))
        if f and f not in colmap.values():
            colmap[c] = f
    rows = []
    if colmap:
        for _, row in df.iterrows():
            rows.append({colmap[c]: row[c] for c in colmap})
    else:
        # 헤더 매핑 실패 → 첫 열을 품명으로 폴백
        first = df.columns[0]
        for _, row in df.iterrows():
            rows.append({"device_type": row[first]})
    return rows


def parse(filename: str, content: bytes) -> dict:
    name = (filename or "").lower()
    try:
        # ── 표(엑셀/CSV) ──────────────────────────────────────────────
        if name.endswith((".xlsx", ".xls", ".csv")):
            import pandas as pd
            if name.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(content))
            else:
                df = pd.read_excel(io.BytesIO(content))
            df = df.dropna(how="all")
            items = _rows_to_items(_parse_table(df))
            return {"items": items, "source": "excel" if not name.endswith(".csv") else "csv",
                    "note": f"{len(items)}개 항목 파싱(표 헤더 자동매핑). 검토 후 등록하세요."}

        # ── PDF(디지털 텍스트/표) ─────────────────────────────────────
        if name.endswith(".pdf"):
            import pdfplumber
            rows = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    for tbl in (page.extract_tables() or []):
                        if not tbl or len(tbl) < 2:
                            continue
                        hdr = tbl[0]
                        cmap = {i: _match_field(h) for i, h in enumerate(hdr)}
                        if not any(cmap.values()):
                            continue
                        for tr in tbl[1:]:
                            rows.append({cmap[i]: tr[i] for i in range(len(tr)) if cmap.get(i)})
            items = _rows_to_items(rows)
            if not items:
                return {"items": [], "source": "pdf",
                        "note": "표 인식 실패 — 텍스트형 PDF/Excel 권장(스캔본은 이미지 업로드)."}
            return {"items": items, "source": "pdf",
                    "note": f"{len(items)}개 항목 파싱(PDF 표). 검토 후 등록하세요."}

        # ── 이미지(스캔) OCR ─────────────────────────────────────────
        if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
            try:
                import pytesseract
                from PIL import Image
                txt = pytesseract.image_to_string(Image.open(io.BytesIO(content)), lang="kor+eng")
            except Exception as e:
                return {"items": [], "source": "image",
                        "note": f"OCR 미설치/실패 — 테서랙트(kor) 설치 필요. Excel/텍스트PDF 권장. ({str(e)[:50]})"}
            lines = [l.strip() for l in txt.splitlines() if len(l.strip()) > 1]
            items = _rows_to_items([{"device_type": l} for l in lines[:40]])
            return {"items": items, "source": "image-ocr",
                    "note": f"OCR {len(items)}줄 추출(정확도 낮을 수 있음). 반드시 검토·수정하세요."}

    except Exception as e:
        logger.error("[equipment_import] 파싱 오류: %s", e)
        return {"items": [], "source": "error", "note": f"파싱 실패: {str(e)[:80]}"}

    return {"items": [], "source": "unsupported",
            "note": "지원 형식: .xlsx/.csv/.pdf/이미지(png·jpg). 다른 형식은 변환 후 업로드."}
