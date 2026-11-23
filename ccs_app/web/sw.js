// Service worker : la charpente reste disponible hors ligne (la page affiche alors
// « reconnexion »). L'API n'est jamais mise en cache.
const CACHE = "ccs-v32";
const SHELL = ["/", "/style.css", "/chat.css", "/sessions.css", "/pages.css",
  "/app.js", "/api.js", "/dom.js", "/login.js", "/views.js", "/home.js", "/sessions.js", "/chat.js",
  "/files.js", "/files-manage.js", "/files-browser.js", "/roadmap.js", "/terminal.js", "/analysis.js", "/settings.js", "/git.js",
  "/chat-changes.js", "/chat-complete.js", "/chat-context.js", "/chat-diff.js", "/chat-links.js", "/chat-message.js", "/chat-quote.js", "/chat-saved.js", "/chat-tags.js",
  "/chat-search.js", "/voice.js",
  "/project.js", "/install.js", "/machines.js", "/sessions-conv.js", "/sessions-new.js", "/sessions-manage.js", "/sessions-order.js",
  "/pages-util.js", "/pages-health.js", "/pages-tasks.js", "/pages-phone.js", "/pages-machines.js", "/reseau.js", "/root.js",
  "/vendor/xterm/xterm.js", "/vendor/xterm/xterm.css", "/vendor/xterm/addon-fit.js",
  "/icons/ccs.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // réseau d'abord (toujours la dernière version), cache si hors ligne
  e.respondWith(fetch(e.request)
    .then((r) => { if (r.ok) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); } return r; })
    .catch(() => caches.match(e.request).then((r) => r || caches.match("/"))));
});
