# SEO_GUIDE — 구글 검색 최적화 (farmingsight.org)

## 적용된 기술 (코드로 반영됨)
1. **메타 태그**(`screens/intro.html` head): keyword-rich `title`·`description`·`keywords`, `robots: index,follow,max-image-preview:large`, `canonical=https://farmingsight.org/`.
2. **Open Graph / Twitter Card**: 카톡·페북·트위터 공유 시 제목·설명·이미지 카드 노출.
3. **구조화 데이터(JSON-LD `SoftwareApplication`)**: 구글 리치결과·지식그래프 인식(기능목록·무료·발행처).
4. **robots.txt**(`/robots.txt`): 크롤 허용 + `/api/` 차단 + 사이트맵 위치 명시.
5. **sitemap.xml**(`/sitemap.xml`): 핵심 11개 URL(우선순위·갱신주기) — 색인 가속.
6. 라우트: `api/main.py` `/robots.txt`·`/sitemap.xml` 공개 서빙, 인증 미들웨어 화이트리스트.

## ⚠️ 사용자 조치 (검색 노출까지 필수)
1. **Google Search Console 등록**: search.google.com/search-console → `farmingsight.org` 속성 추가 → **소유권 확인**(DNS TXT 또는 HTML 메타). Cloudflare DNS라 TXT 레코드 추가가 쉬움.
2. **사이트맵 제출**: Search Console → 색인 → Sitemaps → `https://farmingsight.org/sitemap.xml` 제출.
3. **색인 요청**: URL 검사 → `https://farmingsight.org/` → 색인 생성 요청.
4. (권장) **OG 이미지 교체**: 현재 `/icon.svg` → 1200×630 PNG 권장(카드 썸네일 품질↑). 만들면 intro의 `og:image`·`twitter:image`를 PNG URL로 교체.

## 한계·주의
- `/` → `/intro` 307 리다이렉트 구조라 canonical을 `/`로 통일해 신호 일관화함. 색인이 안정되면 `/`를 200 직접서빙으로 바꾸는 것이 더 강함(선택).
- SPA가 아니라 정적 HTML이라 크롤링 우호적(JS 렌더 불필요).
- 콘텐츠 신선도·외부 백링크·실사용 트래픽이 순위의 핵심 — 기술 SEO는 토대일 뿐.

## 점검 명령
```
curl -s https://farmingsight.org/robots.txt
curl -s https://farmingsight.org/sitemap.xml
curl -s https://farmingsight.org/intro | grep -E 'og:|description|ld\+json'
```
구글 리치결과 테스트: https://search.google.com/test/rich-results?url=https://farmingsight.org/
