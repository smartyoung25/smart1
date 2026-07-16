"""스마트농업컨설턴트 교재 → 의미 단위 청킹 (RAG 지식베이스 소재).

저작권: 본 교재의 저작권은 ㈜이암허브·한국스마트농업AI협회에 있다(자사 자료).

설계 근거(실측):
  · 449쪽 / 491,380자 / 그림전용 빈 페이지 0%
  · 목차 p1~14, 본문 p15~
  · 계층: Ⅰ(8) > 1.(52) > 가.(332) > 1)(480) > 가)(537), ❍ 불릿 504
  · 병해충 항목이 '가) 특징적인 증상 / 나) 발생 원인 / 다) 관리 방법' 구조 → Q&A 에 직결
  · ★ 추출은 반드시 get_text(sort=True) — 기본 추출은 문장부호가 뒤로 밀려 문장이 깨진다
    (예: "침입하며 / 유발한다 / 이 / , / . / 들의" → sort=True 로 정상 복원)

청킹 원칙:
  · 고정 길이가 아니라 '1)' 목 단위를 1차 경계로 삼아 의미를 보존
  · 너무 길면 '가)' → '❍' 순으로 하위 분할, 너무 짧으면 형제와 병합
  · 각 청크에 계층 경로·페이지·작목·표/그림 참조를 메타데이터로 부착 → 출처 인용 가능

사용:
  python scripts/chunk_textbook.py                # 미리보기(통계 + 샘플)
  python scripts/chunk_textbook.py --write        # out/kb_textbook_chunks.json 저장
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "outputs" / "스마트농업컨설턴트 교재_250630.pdf"
OUT = ROOT / "out" / "kb_textbook_chunks.json"

MIN_CHARS, MAX_CHARS = 400, 1800
CROPS = ["방울토마토", "완숙토마토", "토마토", "딸기", "파프리카", "오이", "멜론", "참외", "수박", "고추"]

# 계층 패턴 (우선순위 순)
RE_ROMAN = re.compile(r"^\s*([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]{1,4})\s*[\.\s]\s*(.{2,60})$")
RE_SEC   = re.compile(r"^\s*(\d{1,2})\.\s+(\S.{1,60})$")
RE_SUB   = re.compile(r"^\s*([가-힣])\.\s+(\S.{1,60})$")
RE_ITEM  = re.compile(r"^\s*(\d{1,2})\)\s*(\S.{0,60})$")
RE_PAGE  = re.compile(r"^\s*-\s*\d+\s*-\s*$")
RE_FIG   = re.compile(r"\[?(그림|표)\s*\[?\s*(\d+-\d+-\d+)")


def load_pages() -> list[str]:
    import fitz
    d = fitz.open(PDF)
    pages = [d[i].get_text(sort=True) for i in range(len(d))]
    d.close()
    return pages


def find_toc_end(pages: list[str]) -> int:
    end = 0
    for i, t in enumerate(pages[:30]):
        if t.count("····") > 3:
            end = i
    return end


def build_chunks(pages: list[str], toc_end: int) -> list[dict]:
    ctx = {"roman": "", "sec": "", "sub": ""}
    chunks: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur and len("".join(cur["lines"]).strip()) >= 40:
            body = "\n".join(l for l in cur["lines"] if l.strip())
            cur["text"] = body
            del cur["lines"]
            chunks.append(cur)
        cur = None

    def start(title: str, page: int, atomic: bool = False):
        nonlocal cur
        flush()
        # atomic=True: 제목이 붙은 독립 항목(1)·가.·1. 등). 짧아도 병합 금지 —
        #   병해 항목 하나가 곧 하나의 검색 단위이기 때문. (구: MIN_CHARS 미만이면
        #   직전 청크에 흡수돼 '9) 협엽증'(약 200자)이 '8) 붕소 과잉' 청크에 섞였고,
        #   협엽증을 물으면 붕소 과잉 청크가 검색되는 오검색이 발생했다.)
        cur = {"title": title, "page": page, "lines": [], "atomic": atomic,
               "chapter": ctx["roman"], "section": ctx["sec"], "subsection": ctx["sub"]}

    for pno in range(toc_end + 1, len(pages)):
        for raw in pages[pno].split("\n"):
            line = raw.rstrip()
            if not line.strip() or RE_PAGE.match(line):
                continue
            if (m := RE_ROMAN.match(line)):
                ctx.update(roman=f"{m.group(1)}. {m.group(2).strip()}", sec="", sub="")
                start(ctx["roman"], pno + 1, atomic=True); continue
            if (m := RE_SEC.match(line)):
                ctx.update(sec=f"{m.group(1)}. {m.group(2).strip()}", sub="")
                start(ctx["sec"], pno + 1, atomic=True); continue
            if (m := RE_SUB.match(line)):
                ctx["sub"] = f"{m.group(1)}. {m.group(2).strip()}"
                start(ctx["sub"], pno + 1, atomic=True); continue
            if (m := RE_ITEM.match(line)):
                start(f"{m.group(1)}) {m.group(2).strip()}", pno + 1, atomic=True); continue
            if cur is None:
                start(ctx["sub"] or ctx["sec"] or ctx["roman"] or "(본문)", pno + 1)
            cur["lines"].append(line)
            # 과대 청크 방지: 상한 초과 시 같은 제목으로 이어서 분할
            if sum(len(l) for l in cur["lines"]) > MAX_CHARS:
                t, p = cur["title"], cur["page"]
                flush(); start(t + " (계속)", p, atomic=True)
    flush()

    # 너무 짧은 청크는 직전 청크에 병합(같은 절 안에서만)
    # ★ atomic(제목 있는 독립 항목)은 짧아도 병합하지 않는다 — 항목 하나가 곧 검색 단위.
    #   제목 없는 파편(그림 캡션·잔여 줄)만 직전 청크에 흡수한다.
    merged: list[dict] = []
    for c in chunks:
        if (merged and not c.get("atomic") and len(c["text"]) < MIN_CHARS
                and merged[-1]["section"] == c["section"]
                and len(merged[-1]["text"]) + len(c["text"]) <= MAX_CHARS):
            merged[-1]["text"] += "\n" + c["text"]
        else:
            merged.append(c)

    # 메타데이터 부착
    for i, c in enumerate(merged):
        blob = f'{c["chapter"]} {c["section"]} {c["subsection"]} {c["title"]} {c["text"]}'
        c["id"] = f"kb_tb_{i:04d}"
        c["source"] = "스마트농업컨설턴트 교재(2025-06-30)"
        c["copyright"] = "㈜이암허브·한국스마트농업AI협회"
        c["crops"] = sorted({x for x in CROPS if x in blob})
        c["refs"] = sorted({f"{a}{b}" for a, b in RE_FIG.findall(blob)})
        c["chars"] = len(c["text"])
        c["path"] = " > ".join(x for x in [c["chapter"], c["section"], c["subsection"]] if x)
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    pages = load_pages()
    toc_end = find_toc_end(pages)
    chunks = build_chunks(pages, toc_end)

    sizes = [c["chars"] for c in chunks]
    sizes.sort()
    n = len(chunks)
    print(f"청크 {n}개 | 총 {sum(sizes):,}자")
    print(f"  길이: 최소 {sizes[0]} · 중앙 {sizes[n//2]} · 평균 {sum(sizes)//n} · 최대 {sizes[-1]}")
    print(f"  {MIN_CHARS}자 미만: {sum(1 for s in sizes if s < MIN_CHARS)}개 "
          f"| {MAX_CHARS}자 초과: {sum(1 for s in sizes if s > MAX_CHARS)}개")
    print(f"  작목 태그 보유: {sum(1 for c in chunks if c['crops'])}개")
    print(f"  표/그림 참조 보유: {sum(1 for c in chunks if c['refs'])}개")

    print("\n=== 병해충 Q&A 후보(증상+원인+관리 동시 포함) ===")
    qa = [c for c in chunks if all(k in c["text"] for k in ("증상", "원인")) and
          any(k in c["text"] for k in ("관리 방법", "방제"))]
    print(f"  {len(qa)}개")
    for c in qa[:3]:
        print(f"\n  [{c['id']}] p{c['page']} · {c['title']}  (작목: {', '.join(c['crops']) or '-'})")
        print(f"    경로: {c['path'][:70]}")
        print(f"    {c['text'][:150].replace(chr(10), ' ')}…")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {OUT}  ({OUT.stat().st_size:,} bytes)")
    else:
        print("\n(미리보기 — 저장하려면 --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
