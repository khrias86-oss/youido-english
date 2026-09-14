/* 오프라인 지원.
 *
 * 화면을 구성하는 파일(셸)만 캐시한다. 빈자리 현황(data.json)은 늘 네트워크에서
 * 받아야 하므로 캐시하지 않고, 받지 못했을 때 마지막 값을 보여주는 일은 앱이
 * localStorage 로 처리한다. 덕분에 "오래된 현황을 새 것처럼 보여주는" 사고가 없다.
 */
const CACHE = 'umppa-shell-v1';
const SHELL = ['./', './index.html', './app.js', './style.css', './config.js',
               './icon.svg', './manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // 하나라도 실패하면 설치가 깨지므로 개별로 담는다
      .then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;      // 외부 데이터 사본은 건드리지 않는다
  if (url.pathname.endsWith('/data.json')) return;      // 현황은 항상 네트워크

  // config.js 는 접속 설정이라 바뀌면 바로 반영돼야 한다: 네트워크 우선
  if (url.pathname.endsWith('/config.js')) {
    e.respondWith(fetch(req).catch(() => caches.match(req, { ignoreSearch: true })));
    return;
  }

  // 나머지 셸: 캐시를 먼저 돌려주고 뒤에서 갱신한다
  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      });
      return hit || net;
    }),
  );
});
