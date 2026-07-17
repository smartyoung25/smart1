"""지식베이스 검색 (BM25) — 챗봇 근거 제공.

지식베이스(api/data/kb/):
  kb_textbook_chunks.json  스마트농업컨설턴트 교재 449쪽 → 735청크 (병해충·환경·재배)
  kb_rules_chunks.json     제품 도메인 규칙 → 15청크 (P1~P6 관수·일사적산·PDCA 임계·VPD)
  두 소스는 상호보완이다 — 교재엔 관수(배액률·dry-back·일사적산·P1~P6)가 0회 등장하고,
  제품 규칙엔 병해충이 없다.

  ★ 왜 out/ 이 아니라 api/data/kb/ 인가: out/ 은 .gitignore 대상(생성 문서 폴더)이라
    거기 두면 배포 서버에 파일이 없고, 검색이 조용히 0건이 되어 기능이 죽은 채로
    정상처럼 보인다. 지식베이스는 생성물이 아니라 API 런타임 의존물이므로 추적한다.
    (같은 유형의 사고: 모델 pkl 이 LFS 포인터로 배포돼 11일간 stub 예측을 뱉었다.)
    빌드 스크립트는 out/ 에 쓰고, 서빙본은 api/data/kb/ 로 복사한다.

왜 BM25 인가:
  임베딩·벡터DB 없이 동작한다(현재 LLM 크레딧 소진 상태에서도 검색은 유효).
  ★ 길이 정규화가 핵심 — 원시 빈도로는 짧은 규칙 청크(200~500자)가 긴 교재 청크(1000자+)에
    밀려 "배액률 EC 관리" 질의에 교재 '데이터 관리하기'가 1위로 나왔다. BM25 적용 후
    P4·P3·P1 관수 Period 가 정상 상위. (실측 검증됨)

정직성 규약:
  · 검색 결과가 없으면 빈 리스트를 반환한다 — 호출측은 근거 없음을 사용자에게 알려야 한다.
  · 반환 청크의 source/page 를 그대로 노출해 출처 인용이 가능하게 한다.
    (없는 출처를 표기하지 않기 위함 — 화면이 'RAG·농진청 DB'를 허위 표기하던 문제의 재발 방지)
"""
from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "api" / "data" / "kb"
FILES = [KB_DIR / "kb_textbook_chunks.json",
         KB_DIR / "kb_rules_chunks.json"]

_K1, _B = 1.5, 0.75

# ★ 무관한 질의에 자료를 붙이지 않기 위한 하한 (정직성 규약의 핵심)
#   근거: 실측 점수 분포가 깨끗하게 갈린다 —
#     유효 질의 1위: 배액률 17.5 · 딸기반점 21.3 · 오이온도 19.2 · 정오관수 15.5 · VPD 18.0
#     잡담   1위: "오늘 기분이 어때" 6.2 · "점심 뭐 먹지" 6.7 · 나머지 0.0
#   하한이 없을 때 "오늘 기분이 어때"에 진딧물 교재 6건이 '관련 자료'로 붙었다.
_MIN_SCORE = 10.0
# 1위 대비 이만큼 못 미치는 꼬리는 버린다 — 상위가 강할수록 약한 근거를 섞지 않는다
_REL_FLOOR = 0.45
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL = re.compile(r"^[가-힣]+$")
_NGRAM = 2          # 한글 문자 bi-gram
# 검색 신호가 없는 상투어 — 자연어 질문에서 이들이 점수를 지배하는 것을 막는다
_STOP = {"어떻게", "하나요", "인가요", "какой", "무엇", "뭐야", "뭔가요", "알려줘", "알려주세요",
         "해야", "하면", "되나요", "인데", "입니다", "습니다", "하는", "있는", "지금", "우리",
         "저희", "제가", "좀", "요즘", "얼마나", "얼마", "정도", "관련", "대해", "대한", "그리고"}

_index: dict | None = None
_lock = Lock()


def _toks(s: str) -> list[str]:
    """한글은 문자 bi-gram 으로도 색인한다.

    ★ 왜: 한국어는 조사가 붙어 어절 단위로는 매칭이 실패한다 —
      '배액률이' ≠ '배액률', '관수를' ≠ '관수', '정오에' ≠ '정오'.
      실제로 "배액률이 40%인데 어떻게 하나요" 질의가 풍향풍속 센서 문서를 최상위로
      끌어올렸다(원형 매칭 0). 형태소 분석기(konlpy/mecab)는 무거운 의존성이라,
      bi-gram 색인으로 조사 문제를 우회한다('배액률이' → 배액,액률,률이 … '배액률' →
      배액,액률 이 겹쳐 매칭됨).
      영문·숫자는 어절 그대로 둔다(P4·EC·VPD 같은 식별자 보존).
    """
    out: list[str] = []
    for t in _TOKEN.findall(s or ""):
        if len(t) < 2:
            continue
        if t in _STOP:
            continue
        out.append(t)
        if _HANGUL.match(t) and len(t) > _NGRAM:
            out.extend(t[i:i + _NGRAM] for i in range(len(t) - _NGRAM + 1))
    return out


def _load() -> dict:
    """청크 로드 + BM25 인덱스 1회 구축(프로세스 캐시)."""
    global _index
    if _index is not None:
        return _index
    with _lock:
        if _index is not None:
            return _index
        docs = []
        for fp in FILES:
            if not fp.exists():
                logger.warning("[kb_search] 지식베이스 없음: %s", fp.name)
                continue
            try:
                for c in json.loads(fp.read_text(encoding="utf-8")):
                    # 제목·태그·경로에 가중(3배/2배) — 고유명사(협엽증·P4)가 본문 빈도에 묻히지 않게
                    blob = " ".join([(c.get("title", "") + " ") * 3,
                                     " ".join(c.get("tags", []) or []) * 2,
                                     c.get("path", ""), c.get("text", "")])
                    docs.append({"c": c, "tf": {}, "len": len(blob), "blob": blob})
            except Exception as e:
                logger.error("[kb_search] 로드 실패 %s: %s", fp.name, e)
        df: dict[str, int] = {}
        for d in docs:
            seen = set()
            for t in _toks(d["blob"]):
                d["tf"][t] = d["tf"].get(t, 0) + 1
                if t not in seen:
                    df[t] = df.get(t, 0) + 1
                    seen.add(t)
            del d["blob"]
        n = len(docs)
        if not n:
            # 조용히 0건으로 지나가면 챗봇이 '근거 없음' 답변만 하면서도 정상처럼 보인다.
            # 배포에 KB 가 누락된 상황이므로 눈에 띄게 남긴다.
            logger.error("[kb_search] ★ 지식베이스가 비어 있다 — %s 확인 필요. "
                         "챗봇이 문헌 근거 없이 답한다.", KB_DIR)
        # 색인에 실재하는 작목명 — 질문에서 작목을 알아채는 데 쓴다(하드코딩 목록 두지 않기 위함).
        # 긴 이름 우선(방울토마토가 토마토보다 먼저 잡히게).
        crops = sorted({c for d in docs for c in (d["c"].get("crops") or []) if c},
                       key=len, reverse=True)
        _index = {"docs": docs, "df": df, "n": n, "crops": crops,
                  "avgdl": (sum(d["len"] for d in docs) / n) if n else 1.0}
        logger.info("[kb_search] 지식베이스 %d청크 인덱싱", n)
        return _index


def search(query: str, k: int = 6, crop: str | None = None) -> list[dict]:
    """BM25 검색. 반환: [{id,title,text,source,page,path,score}] — 없으면 [].

    k 기본 6: BM25 만으로는 특정 규칙 청크가 일반 문서에 밀릴 수 있다(실측: "정오에 관수를
    얼마나" 질의에서 P4 가 5위 — '관수'는 df 82 로 IDF 가 낮아 언급 많은 일반 문서가 tf 로
    이긴다). 근거를 넉넉히 넘겨 LLM 이 고르게 한다. 토큰은 format_for_prompt 상한이 막는다."""
    idx = _load()
    if not idx["n"] or not (query or "").strip():
        return []
    n, avgdl, df = idx["n"], idx["avgdl"], idx["df"]
    q = _toks(query)

    # ★ 질문이 작목을 명시하면 농장 작목보다 우선한다.
    #   실측: 오이 농장(farm_001)에서 "딸기 잎에 반점이 생겼어요" 질의에 오이 가산이 걸려
    #   오이·멜론 바이러스(MNSV)가 딸기 TSWV 를 제치고 1위였다 — 남의 작목 병해를 답할 뻔했다.
    named = [c for c in idx["crops"] if c in query]
    if named:
        crop = named[0]
    scored = []
    for d in idx["docs"]:
        s = 0.0
        for t in q:
            f = d["tf"].get(t, 0)
            if not f:
                continue
            dfi = df.get(t, 0)
            idf = math.log(1 + (n - dfi + 0.5) / (dfi + 0.5))
            s += idf * (f * (_K1 + 1)) / (f + _K1 * (1 - _B + _B * d["len"] / avgdl))
        if s <= 0:
            continue
        # 작목이 특정되면 해당 작목 청크를 소폭 가산(타 작목 지식 오인용 방지)
        if crop:
            cr = d["c"].get("crops") or []
            if cr and any(c in crop or crop in c for c in cr):
                s *= 1.25
        scored.append((s, d["c"]))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < _MIN_SCORE:
        return []                       # 무관한 질의 — 없는 근거를 지어내지 않는다
    floor = max(_MIN_SCORE, scored[0][0] * _REL_FLOOR)
    scored = [x for x in scored if x[0] >= floor]
    out = []
    for s, c in scored[:k]:
        out.append({"id": c.get("id"), "title": c.get("title"), "text": c.get("text", ""),
                    "source": c.get("source"), "page": c.get("page"),
                    "path": c.get("path"), "score": round(s, 2)})
    return out


def cite(hit: dict) -> str:
    """출처 표기 문자열 — 실제 검색된 청크에만 사용."""
    src = hit.get("source") or "출처 미상"
    return f"{src} p{hit['page']}" if hit.get("page") else src


def format_for_prompt(hits: list[dict], max_chars: int = 2400) -> str:
    """system prompt 에 넣을 근거 블록. 길이 상한으로 토큰 폭주 방지."""
    if not hits:
        return ""
    parts, total = [], 0
    for i, h in enumerate(hits, 1):
        body = (h.get("text") or "").strip()
        block = f"[근거{i}] {h.get('title')} ({cite(h)})\n{body}"
        if total + len(block) > max_chars:
            block = block[: max(0, max_chars - total)]
            if not block.strip():
                break
        parts.append(block)
        total += len(block)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


def stats() -> dict:
    idx = _load()
    return {"chunks": idx["n"], "files": [f.name for f in FILES if f.exists()]}
