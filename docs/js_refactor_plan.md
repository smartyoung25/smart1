# main.js 모듈 분리 계획

**작성**: 2026-05-29 | **상태**: 진행 중 (CSS 분리 완료)

---

## 전략: 일반 <script> 순차 로딩 (ES 모듈 아님)

**이유**: HTML에 onclick="fn()" 속성이 200개 이상. ES 모듈로 전환하면
모든 함수를 window.fn = fn으로 재노출해야 하는 2차 작업 발생.
일반 스크립트 순차 로딩으로 동일한 컨텍스트 이점 + 위험 없음.

---

## 로딩 순서 (index.html 하단)

```html
<script src="/dashboard/modules/core.js"></script>       <!-- 의존성 없음 -->
<script src="/dashboard/modules/auth.js"></script>        <!-- core 필요 -->
<script src="/dashboard/modules/admin.js"></script>       <!-- core, auth 필요 -->
<script src="/dashboard/modules/environ.js"></script>     <!-- core 필요 -->
<script src="/dashboard/modules/harvest.js"></script>     <!-- core, environ 필요 -->
<script src="/dashboard/modules/market.js"></script>      <!-- core 필요 -->
<script src="/dashboard/modules/irrigation.js"></script>  <!-- core, environ 필요 -->
<script src="/dashboard/modules/chat.js"></script>        <!-- core 필요 -->
<script src="/dashboard/modules/nav.js"></script>         <!-- 모두 필요, 마지막 -->
```

---

## 파일별 함수 목록

### core.js (예상 ~150줄)
전역 상태, 유틸리티 함수

```
전역변수: _token, _myFarmId, _farmsData, _wsActive, _wsRetryTimer, _toastTimer
함수 목록:
  $() - getElementById 단축
  _decodeJwt()
  _setResult()
  apiFetch()
  _esc()
  _errReason()
  _errBoxHtml()
  _nullReasonHtml()
  showToast()
  showAnomalyToast()
  setText()
  setBar()
  wsBadge()
```

### auth.js (예상 ~250줄)
인증, 온보딩

```
함수 목록:
  switchAuthTab()
  _applyAuthSuccess()
  doLogin()
  doLogout()
  doRegister()
  startOnboarding(), obRender(), obSelectCrop(), obTogglePain()
  obCollectStep(), obNext(), obPrev(), obSkip(), obSubmit()
  _refreshChatQuota()
  loadPlanBadge()
  tierGuard(), _applyLockBanner()
  _tierRankClient(), _tierColor(), _tierNameKo()
  openUpgradeModal(), closeUpgradeModal()
  _renderUpgradeCards(), _tierFeatureHint(), submitUpgrade()
```

### admin.js (예상 ~400줄)
어드민 패널, 농장 관리, 센서 차트

```
함수 목록:
  loadHealth()
  loadOverview()
  loadCropModels()
  loadPipelineState()
  triggerRetrainManual()
  loadEtlStatus()
  loadRetrainHistory()
  loadFarmsOverview()
  sortFarms(), renderFarmsTable()
  openChartPanel(), setDetailTab(), closeChartPanel()
  setChartMetric(), reloadChart()
  loadFarmRecommendations(), _renderRecoItems(), applyRecommendations()
  loadFarmHarvestRevenue()
  loadFarmDiseaseRisk()
  loadModelPerformance()
  loadApiStatus()
```

### environ.js (예상 ~350줄)
환경 탭 (실내·외 환경, 이상감지, LED, 날씨)

```
함수 목록:
  loadCurrentEnv()
  submitManualEnv()
  loadWeatherForecast()
  loadWeatherEt0()
  loadEnvAnomalies()
  loadLEDSpectrum()
  wsConnect(), scheduleWsRetry()
  switchFarm(), applyEnvMessage()
  loadDiseaseDetect()
```

### harvest.js (예상 ~450줄)
생육·수확·AI 권고·What-if·Hero 대시보드

```
함수 목록:
  loadGrowthHarvestRevenue()
  setGrowthModel()
  runWhatIf(), resetWhatIf()
  loadAdvisoryHistory(), renderAdvisoryFeed()
  loadAdvisorySummary(), renderHeatmap()
  loadSfropScenarios()
  loadAdvisorOptimal()
  loadHeroDashboard()
  loadCtrlRecommendations(), applyCtrlRecommendations()
```

### market.js (예상 ~400줄)
손익·비용·KAMIS·ERP·공동출하

```
함수 목록:
  loadProfitForecast()
  loadCostBreakdown()
  loadCostManualForm(), submitManualCost(), deleteManualCost()
  loadERPRealtime()
  loadMarketPrices(), loadPriceHistory()
  loadMarketHarvest()
  loadPricesLatest()
  loadWholesaleMarket()
```

### irrigation.js (예상 ~300줄)
관수·Priva·ET₀·일정

```
함수 목록:
  submitIrrigation()
  loadPrivaSchedule()
  loadIrrigationSchedule()
  submitIrrigationP4()
  renderIrrigationAnomalies(), checkIrrigationAnomalies()
  loadIrrigationAnalysis()
```

### chat.js (예상 ~130줄)
AI 채팅 플로팅 패널

```
함수 목록:
  toggleChat(), clearChat(), sendChat()
```

### nav.js (예상 ~280줄)
섹션 전환, SECTION_LOADERS, 농장 select, 모바일 드로어

```
함수 목록:
  showSection()
  SECTION_LOADERS (객체)
  _defaultFarm(), _autoSel()
  populateSelectWithFarms(), populateAllFarmSels()
  populateProfitFarmSel(), populateGrowthSel()
  toggleDrawer(), closeDrawer()
  toggleAccordion()
  refreshAll()
  [초기화 코드: setInterval, DOMContentLoaded]
```

---

## 작업 프로토콜

### 분리 순서 (안전한 순서)
1. core.js 추출 (전역변수 + 유틸)
2. auth.js 추출
3. admin.js 추출
4. environ.js 추출
5. harvest.js 추출
6. market.js 추출
7. irrigation.js 추출
8. chat.js 추출
9. nav.js 추출 (SECTION_LOADERS + 초기화, 마지막)
10. main.js 삭제 (모든 함수 이전 확인 후)
11. index.html 하단 script 태그 업데이트

### 검증 기준 (각 파일 추출 후)
- 로그인 → 대시보드 진입 OK
- 환경 탭 전환 OK
- API 호출 응답 OK
- 브라우저 콘솔 에러 없음

---

## 완료 후 파일 크기 목표

| 파일 | 현재 | 목표 |
|------|------|------|
| index.html | 1453줄 ✅ | <500줄 |
| style.css | 1507줄 ✅ | 유지 |
| main.js | 3841줄 | 삭제 |
| modules/*.js | - | 각 <500줄 |
