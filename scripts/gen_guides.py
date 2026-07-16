# -*- coding: utf-8 -*-
"""SEO 가이드 페이지 생성기 — screens/guide/*.html (사실 데이터 기반)."""
import io, os, json

BASE = "https://farmingsight.org"
CROPS = "딸기·오이·방울토마토·완숙토마토·파프리카·참외(온실 6작목) + 제주 노지 7작목"

def jstr(s):
    return json.dumps(s, ensure_ascii=False)

def page(slug, title, desc, keywords, h1, lede, body_html, faq, crumb_name):
    canon = BASE + "/screens/guide/" + slug + ".html"
    faq_json = ",\n".join(
        '{ "@type":"Question","name":%s,"acceptedAnswer":{"@type":"Answer","text":%s} }'
        % (jstr(q), jstr(a)) for q, a in faq)
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<meta name="description" content="{desc}"/>
<meta name="keywords" content="{keywords}"/>
<link rel="canonical" href="{canon}"/>
<meta name="robots" content="index,follow,max-image-preview:large"/>
<meta property="og:type" content="article"/>
<meta property="og:site_name" content="KAASA Farmingsight"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{desc}"/>
<meta property="og:url" content="{canon}"/>
<meta property="og:image" content="{BASE}/og-image.png"/>
<meta property="og:locale" content="ko_KR"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:image" content="{BASE}/og-image.png"/>
<script type="application/ld+json">
{{ "@context":"https://schema.org","@type":"Article",
  "headline":{h1j},"description":{descj},
  "inLanguage":"ko","mainEntityOfPage":{canonj},
  "image":"{BASE}/og-image.png",
  "author":{{"@type":"Organization","name":"KAASA"}},
  "publisher":{{"@type":"Organization","name":"KAASA","url":"{BASE}/"}} }}
</script>
<script type="application/ld+json">
{{ "@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[
  {{"@type":"ListItem","position":1,"name":"홈","item":"{BASE}/"}},
  {{"@type":"ListItem","position":2,"name":"가이드","item":"{BASE}/screens/help.html"}},
  {{"@type":"ListItem","position":3,"name":{crumbj},"item":{canonj}}} ]}}
</script>
<script type="application/ld+json">
{{ "@context":"https://schema.org","@type":"FAQPage","mainEntity":[
{faq_json} ]}}
</script>
<link rel="stylesheet" href="../../components/base.css"/>
<style>
  body{{background:var(--bg);}}
  main{{max-width:560px;margin:0 auto;padding:16px 16px 48px;}}
  article{{background:var(--panel);border:1.5px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:18px 16px;}}
  h1{{font-size:20px;font-weight:900;color:var(--green-dark);line-height:1.35;margin:0 0 8px;}}
  .lede{{font-size:13.5px;color:var(--muted);line-height:1.7;margin:0 0 16px;}}
  h2{{font-size:15px;font-weight:800;color:var(--text);margin:20px 0 8px;border-left:4px solid var(--green);padding-left:8px;}}
  p{{font-size:13.5px;color:var(--text);line-height:1.75;margin:8px 0;}}
  table{{width:100%;font-size:12.5px;border-collapse:collapse;margin:10px 0;}}
  th,td{{padding:7px 6px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top;}}
  th{{color:var(--green-dark);font-weight:800;background:var(--green-soft);}}
  td:first-child{{font-weight:700;color:var(--green-dark);white-space:nowrap;}}
  .cta{{display:inline-block;margin:6px 6px 0 0;font-size:12.5px;font-weight:700;background:var(--green-soft);color:var(--green-dark);padding:8px 13px;border-radius:10px;text-decoration:none;}}
  .crumb{{font-size:12px;color:var(--muted);margin-bottom:10px;}}
  .crumb a{{color:var(--green);text-decoration:none;}}
  .rel{{margin-top:22px;padding-top:14px;border-top:1px solid var(--border);}}
  .rel a{{display:block;font-size:13px;color:var(--green-dark);font-weight:700;padding:7px 0;text-decoration:none;}}
</style>
</head>
<body>
<main>
  <nav class="crumb"><a href="../../">홈</a> &rsaquo; <a href="../help.html">가이드</a> &rsaquo; {crumb_name}</nav>
  <article>
    <h1>{h1}</h1>
    <p class="lede">{lede}</p>
    {body_html}
    <div class="rel">
      <b style="font-size:12.5px;color:var(--muted);">관련 가이드</b>
      <a href="irrigation-period.html">&rarr; 스마트팜 관수 P1~P6 가이드</a>
      <a href="environment-strategy.html">&rarr; 스마트팜 환경관리 전략(VPD·DLI·CO₂)</a>
      <a href="disease-early-warning.html">&rarr; 병해 조기경보·IPM 가이드</a>
    </div>
  </article>
</main>
</body>
</html>
""".format(title=title, desc=desc, keywords=keywords, canon=canon, BASE=BASE,
           h1=h1, lede=lede, body_html=body_html, faq_json=faq_json,
           crumb_name=crumb_name, h1j=jstr(h1), descj=jstr(desc),
           canonj=jstr(canon), crumbj=jstr(crumb_name))

p1 = page(
 "irrigation-period",
 "스마트팜 관수 P1~P6 가이드 — 일사적산 기반 급액·배액 제어 | KAASA Farmingsight",
 "스마트팜 관수 자동화 P1~P6 가이드. 시각이 아닌 일사 적산(J/cm²)으로 급액·배액을 제어하는 6단계 일일 곡선, 급액/배액 EC·pH, 배액률, 함수율 dry-back을 정리합니다.",
 "스마트팜 관수,관수 자동화,일사적산 관수,P1 P6 관수,배액률,급액 EC,배액 EC,함수율 dry-back,양액 제어",
 "스마트팜 관수 P1~P6 — 일사적산 기반 급액·배액 제어",
 "관수는 시각이 아니라 <b>일사 적산(J/cm²)</b>으로 제어합니다. 하루를 P1~P6 여섯 단계의 일일 곡선으로 나눠 급액·배액·함수율을 운영하는 방법을 정리했습니다. 대상: " + CROPS + ".",
 """
 <h2>왜 시각이 아니라 일사 적산인가</h2>
 <p>작물의 증산은 들어온 빛의 양에 비례합니다. 그래서 \"오전 9시\"가 아니라 <b>적산 일사 약 400 J/cm²(순간 ≈600 W/m²)</b>에 첫 배액을 시작하는 것이 농학적으로 맞습니다. 흐린 날과 맑은 날의 관수 타이밍이 자동으로 달라집니다. 시각은 폴백 기준일 뿐입니다.</p>
 <h2>P1~P6 일일 관수 곡선</h2>
 <table>
 <tr><th>단계</th><th>시점·트리거</th><th>핵심 지표</th></tr>
 <tr><td>P1</td><td>일출 전(05~07시)</td><td>EC·pH 기준값 점검, 야간 dry-back 10~20% 확인</td></tr>
 <tr><td>P2</td><td>첫 관수(일출+2~3h)</td><td>슬랩 급액 4~6%로 재포화·염류 세척, 배액 前</td></tr>
 <tr><td>P3</td><td>첫 배액(≈400 J/cm²)</td><td>배액률 20~30%, 배액 EC 최저로 유도, VPD 관리</td></tr>
 <tr><td>P4</td><td>정오 고부하(12~15시)</td><td>함수율 64~65% 유지, 12%↓ 즉시 추가</td></tr>
 <tr><td>P5</td><td>오후 dry-down(15시~일몰)</td><td>dry-back 2~5%, EC 상향(생식 유도)</td></tr>
 <tr><td>P6</td><td>야간(일몰~05시)</td><td>dry-back 10~20%, 무관수 기본</td></tr>
 </table>
 <h2>급액·배액 정상 범위(G3 기준)</h2>
 <table>
 <tr><th>항목</th><th>정상</th><th>경보</th></tr>
 <tr><td>급액 EC</td><td>2.5~3.5 dS/m</td><td>&gt;4.0 또는 &lt;2.0</td></tr>
 <tr><td>배액 EC</td><td>3.0~4.5 dS/m</td><td>&gt;5.0</td></tr>
 <tr><td>배액률</td><td>20~30%</td><td>&lt;15 또는 &gt;40</td></tr>
 <tr><td>급액 pH</td><td>5.5~6.5</td><td>&lt;5.0 또는 &gt;7.0</td></tr>
 </table>
 <h2>KAASA에서 실행하기</h2>
 <p>앱의 관수 화면은 위 곡선을 실측 일사·함수율과 대조해 단계별 처방을 제시하고, 조치 이행을 기록해 모델 학습에 반영합니다.</p>
 <a class="cta" href="../g3_period.html">관수·양액 Period 화면 열기 &rarr;</a>
 <a class="cta" href="../../">서비스 둘러보기 &rarr;</a>
 """,
 [("관수는 시간 단위로 정하나요?","아니요. 시각이 아니라 일사 적산(J/cm²)과 순간 일사(W/m²)를 우선 기준으로 P1~P6 단계를 제어합니다. 시각은 폴백입니다."),
  ("첫 배액은 언제 시작하나요?","적산 일사 약 400 J/cm²(순간 약 600 W/m²) 시점에 첫 배액(P3)을 시작하고, 이때 배액률 20~30%를 목표로 합니다."),
  ("배액률 정상 범위는?","20~30%가 정상이며 15% 미만 또는 40% 초과는 경보 구간입니다.")],
 "관수 P1~P6")

p2 = page(
 "environment-strategy",
 "스마트팜 환경관리 전략 — VPD·DLI·CO₂ 광연동 제어 | KAASA Farmingsight",
 "스마트팜 환경관리 전략 가이드. VPD 밴드(0.4~0.6 kPa), DLI(PAR 4.57), CO₂ 시비, 광연동 승온을 생육시기×하루 4구간 전략표로 운영하는 방법.",
 "스마트팜 환경관리,VPD,DLI,CO2 시비,광연동 승온,온실 기후관리,환경 전략표,주야간 온도",
 "스마트팜 환경관리 전략 — VPD·DLI·CO₂ 광연동",
 "온도·습도·CO₂를 따로 보지 않고 <b>VPD</b>로 묶어, 생육시기와 하루 4구간(야간·일출·주간·일몰 전) 전략표로 운영합니다. 대상: " + CROPS + ".",
 """
 <h2>핵심 환경 지표와 목표 밴드</h2>
 <table>
 <tr><th>지표</th><th>의미</th><th>목표</th></tr>
 <tr><td>VPD</td><td>증산 구동력(온·습도 결합)</td><td>0.4~0.6 kPa 밴드</td></tr>
 <tr><td>DLI</td><td>하루 누적 광량(PAR)</td><td>PAR 계수 4.57 mol/m²·d 적용</td></tr>
 <tr><td>CO₂</td><td>광합성 원료</td><td>광량 연동 시비(환기와 균형)</td></tr>
 </table>
 <p><b>주의:</b> DLI 계산 시 PAR 계수 4.57을 빠뜨리면 약 4.6배 과소 오류가 납니다.</p>
 <h2>2축 환경관리 전략표</h2>
 <p>행은 생육시기(정식 기준), 열은 하루 4구간(야간·일출·주간·일몰 전). 각 셀에 온도·습도·CO₂ 목표를 두고 VPD를 자동 계산합니다. 벤치마크는 Priva 광연동 승온, HNT 24시간 평균, Plant Empowerment VPD 밴드입니다.</p>
 <h2>편차 &rarr; AI 처방</h2>
 <p>전략표 목표 대비 실측 편차를 평가해 구간별 처방(승온·환기·가습·CO₂)을 생성합니다. 조치 결과는 기록되어 다음 처방 정확도를 높입니다.</p>
 <a class="cta" href="../g2_env.html">환경·기후 제어 화면 열기 &rarr;</a>
 <a class="cta" href="../g1_home.html">온실 홈 &rarr;</a>
 """,
 [("VPD 목표 범위는 얼마인가요?","일반적으로 0.4 kPa(하한)~0.6 kPa(상한) 밴드를 목표로 합니다. 너무 낮으면 환기를 강화합니다."),
  ("DLI는 어떻게 계산하나요?","PAR 계수 4.57을 적용해 하루 누적 광량(mol/m²·d)을 구합니다. 이 계수를 빠뜨리면 약 4.6배 과소 계산됩니다."),
  ("환경관리는 무엇을 기준으로 하나요?","생육시기×하루 4구간 전략표의 온도·습도·CO₂ 목표와 자동 계산된 VPD를 기준으로 실측 편차를 처방합니다.")],
 "환경관리 전략")

p3 = page(
 "disease-early-warning",
 "병해 조기경보·IPM 가이드 — 결로시간 기반 예방 | KAASA Farmingsight",
 "스마트팜 병해 조기경보·IPM 가이드. 잎 결로(습윤) 시간과 환경 위험을 기반으로 감염 위험을 미리 알리고, 방제 이행을 기록해 품질을 관리하는 방법.",
 "병해 조기경보,IPM,결로시간,잎 습윤,방제 이행,작물 품질관리,곰팡이병 예방",
 "병해 조기경보·IPM — 결로시간 기반 예방",
 "곰팡이성 병해는 잎이 젖어 있는 시간(결로·습윤)이 길수록 위험이 커집니다. 환경 데이터로 위험을 미리 알리고 방제를 기록하는 IPM 폐루프를 정리했습니다. 대상: " + CROPS + ".",
 """
 <h2>왜 결로시간이 중요한가</h2>
 <p>대부분의 곰팡이성 병해(잿빛곰팡이·노균병 등)는 포자가 발아하려면 <b>잎 표면이 젖어 있는 시간</b>이 필요합니다. 야간 습도와 온도로 결로 발생·지속 시간을 추정해, 임계 시간을 넘기 전에 환기·제습으로 차단하는 것이 예방의 핵심입니다.</p>
 <h2>IPM 폐루프(예측 &rarr; 조치 &rarr; 기록)</h2>
 <table>
 <tr><th>단계</th><th>내용</th></tr>
 <tr><td>예측</td><td>결로 시간·환경 위험으로 감염 위험 조기경보</td></tr>
 <tr><td>조치</td><td>환기·제습·예찰·약제 방제 등 대응</td></tr>
 <tr><td>기록</td><td>방제 이행을 기록 &rarr; IPM 이력·모델 피드</td></tr>
 </table>
 <p>화학 방제에만 의존하지 않고 환경관리·예찰·생물적 방제를 함께 쓰는 것이 IPM(종합적 병해충 관리)입니다.</p>
 <a class="cta" href="../g5_disease.html">병해·품질 화면 열기 &rarr;</a>
 <a class="cta" href="environment-strategy.html">환경관리로 결로 줄이기 &rarr;</a>
 """,
 [("결로시간이 왜 병해와 관련 있나요?","곰팡이성 병해 포자는 잎이 젖어 있는 동안 발아합니다. 결로(습윤) 지속 시간이 임계치를 넘기 전에 환기·제습으로 차단하면 예방 효과가 큽니다."),
  ("IPM이 무엇인가요?","종합적 병해충 관리로, 화학 방제에만 의존하지 않고 환경관리·예찰·생물적 방제를 결합해 병해를 줄이는 접근입니다."),
  ("조기경보 후 무엇을 하나요?","환기·제습 등 환경 조치와 예찰·방제를 시행하고, 이행 결과를 기록해 IPM 이력과 모델 학습에 반영합니다.")],
 "병해 조기경보")

os.makedirs("screens/guide", exist_ok=True)
for slug, html in [("irrigation-period", p1), ("environment-strategy", p2), ("disease-early-warning", p3)]:
    io.open("screens/guide/" + slug + ".html", "w", encoding="utf-8").write(html)
    print("OK:", slug, len(html), "bytes")
