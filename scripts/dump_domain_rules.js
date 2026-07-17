/* components/data.js 의 도메인 규칙 상수를 JSON 으로 덤프 (지식베이스 소재).
 *
 * 왜 코드에서 뽑는가:
 *   P1~P6 관수 Period·일사적산 트리거·PDCA 임계는 제품의 검증된 자산이며 교재에 없다
 *   (교재 실측: 배액률 0회·슬랩 0회·dry-back 0회·일사적산 0회·P1~P6 0회·DLI 0회).
 *   손으로 옮겨 적으면 코드가 바뀔 때 지식베이스가 조용히 어긋난다 → 코드를 단일 출처로 둔다.
 *
 * data.js 는 브라우저 코드라 window/document/localStorage 를 만지므로 vm + shim 으로 실행한다.
 *
 * 사용: node scripts/dump_domain_rules.js > out/kb_rules_raw.json
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', 'components', 'data.js');
const src = fs.readFileSync(SRC, 'utf8');

const noop = () => {};
const store = {};
const el = () => ({
  style: {}, classList: { add: noop, remove: noop, contains: () => false },
  addEventListener: noop, querySelector: () => null, querySelectorAll: () => [],
  appendChild: noop, setAttribute: noop, insertBefore: noop, remove: noop,
  innerHTML: '', textContent: '', firstChild: null,
});

const ctx = {
  window: {
    addEventListener: noop, removeEventListener: noop,
    matchMedia: () => ({ matches: false, addEventListener: noop }),
    location: { origin: 'http://localhost', pathname: '/' },
  },
  console,
  localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
  sessionStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  document: {
    createElement: el, querySelector: () => null, querySelectorAll: () => [],
    addEventListener: noop, head: el(), body: el(), documentElement: el(),
  },
  location: { origin: 'http://localhost', pathname: '/', href: '/', search: '' },
  navigator: { onLine: true, serviceWorker: { register: () => Promise.resolve() } },
  fetch: () => Promise.reject(new Error('offline-dump')),
  setTimeout, clearTimeout, setInterval, clearInterval,
  AbortController: class { constructor() { this.signal = null; } abort() {} },
  WebSocket: class {},
};
ctx.global = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx);

const K = ctx.window.KaasaData;
if (!K) { console.error('KaasaData 로드 실패'); process.exit(1); }

const out = {
  _source: 'components/data.js',
  PERIODS: K.PERIODS,
  IRRIGATION_START: K.IRRIGATION_START,
  IRRIGATION_STRUCTURE: K.IRRIGATION_STRUCTURE,
  PDCA_THRESHOLDS: K.PDCA_THRESHOLDS,
  ENV_PERIODS: K.ENV_PERIODS,
};
process.stdout.write(JSON.stringify(out, null, 2));
