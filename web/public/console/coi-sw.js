// Cross-origin isolation for static hosts without custom headers (human console, 2026-10-12).
// Re-serves same-scope responses with COOP/COEP so the page gets SharedArrayBuffer. Scope: this directory only.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()))
self.addEventListener('fetch', e => {
  const r = e.request
  if (r.cache === 'only-if-cached' && r.mode !== 'same-origin') return
  e.respondWith(fetch(r).then(res => {
    if (res.status === 0) return res
    const h = new Headers(res.headers)
    h.set('Cross-Origin-Embedder-Policy', 'require-corp')
    h.set('Cross-Origin-Opener-Policy', 'same-origin')
    h.set('Cross-Origin-Resource-Policy', 'cross-origin')
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h })
  }))
})
