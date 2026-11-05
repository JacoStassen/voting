/* Know your ballot service worker. It doesn't cache anything (results change every
   minute, and the page already falls back to its own copy); it exists so the site can
   be installed and can show alerts for areas you track. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || '/?tab=results', self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    const open = list.find(c => new URL(c.url).origin === self.location.origin);
    if (open) { open.focus(); open.postMessage({ type: 'open', url }); return; }
    return self.clients.openWindow(url);
  }));
});
