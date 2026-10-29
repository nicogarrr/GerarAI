/*
 * GerarAI — service worker mínimo y honesto.
 *
 * SIN LECTURA OFFLINE: no existe ninguna página pública offline en la app
 * (todo exige sesión y datos vivos de mercado), así que NADA autenticado se
 * cachea: ni '/' (redirige a sign-in o sirve datos por usuario), ni server
 * actions, ni /api/*, ni respuestas con cabecera Set-Cookie. Cachear '/'
 * serviría la sesión de otro usuario o un shell roto: queda prohibido aquí.
 *
 * Alcance deliberado:
 *   1) Caché runtime de estáticos inmutables (/_next/static/, /assets/).
 *   2) Fallback offline: toda navegación que falle por red recibe una página
 *      sintética «sin conexión» que pide reconectar. No pretende ser lectura
 *      offline: lo documenta en el propio mensaje.
 */
const CACHE = 'cavaai-static-v3';
const OFFLINE_HTML =
  '<!doctype html><html lang="es"><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  '<title>GerarAI — sin conexión</title>' +
  '<body style="background:#101010;color:#d1d5db;font-family:system-ui,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0">' +
  // <main>: el aviso es el contenido de la página y debe estar dentro de un
  // landmark (axe «region», visto en el barrido móvil de la ronda 3).
  '<main style="text-align:center;padding:24px">' +
  '<h1 style="font-size:20px;color:#f3f4f6">Sin conexión</h1>' +
  '<p style="font-size:14px;color:#9ca3af">GerarAI necesita red para leer tus tesis y datos de mercado.<br>Sin lectura offline: reconecta y vuelve a intentarlo.</p>' +
  '</main></body></html>';

self.addEventListener('install', (event) => {
  // Sin precache: nada que preinstalar. Activación inmediata.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      // Limpieza total, incluida la caché 'cavaai-shell-v1' que guardaba '/'.
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function isImmutableStatic(url) {
  return (
    url.origin === self.location.origin &&
    (url.pathname.startsWith('/_next/static/') || url.pathname.startsWith('/assets/'))
  );
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // APIs externas: fuera
  if (url.pathname.startsWith('/api/')) return; // datos vivos: nunca cache
  if (isImmutableStatic(url)) {
    // Estáticos con hash en el nombre: cache-first (son inmutables).
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            // Solo se cachean respuestas limpias, sin Set-Cookie.
            if (response.ok && !response.headers.has('set-cookie')) {
              const copy = response.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          })
      )
    );
    return;
  }

  if (request.mode === 'navigate') {
    // Navegaciones: solo red. Sin cache de '/' ni de ninguna ruta autenticada;
    // si la red falla, página sintética honesta (sin lectura offline).
    event.respondWith(
      fetch(request).catch(
        () => new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
      )
    );
  }
});

/*
 * Web Push: avisos de alertas (macro, DCA, filings...). El servidor firma con
 * VAPID y solo envia a quien activo el permiso Y eligio ese tipo de evento.
 * El texto llega ya redactado en español; aqui solo se muestra. Nada se
 * cachea ni se lee de la red.
 */
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_error) {
    data = {};
  }
  const title = typeof data.title === 'string' && data.title ? data.title : 'GerarAI';
  const body = typeof data.body === 'string' ? data.body : '';
  // Solo rutas internas: un payload nunca puede abrir un sitio externo.
  const url = typeof data.url === 'string' && data.url.startsWith('/') && !data.url.startsWith('//') ? data.url : '/alerts';
  const tag = typeof data.tag === 'string' ? data.tag : undefined;
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      tag,
      icon: '/assets/icons/icon-192.png',
      badge: '/assets/icons/icon-192.png',
      data: { url },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/alerts', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (client.url === target && 'focus' in client) return client.focus();
      }
      return self.clients.openWindow(target);
    })
  );
});
