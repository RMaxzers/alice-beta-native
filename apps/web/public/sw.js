// Alice service worker: shows Web Push reminders and opens the matching task.
// It never calls the API itself (no session/CSRF here): actions open the app, which acts with the user's session.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data && e.data.text() }; }
  const url = d.url || "/#today";
  e.waitUntil(self.registration.showNotification(d.title || "Recordatorio de Alice", {
    body: d.body || "Tienes un aviso pendiente.",
    tag: d.tag || (d.reminder_id ? `reminder-${d.reminder_id}` : undefined),
    icon: "/favicon.svg", badge: "/favicon.svg",
    data: { url },
    actions: d.reminder_id ? [{ action: "open", title: "Ver tarea" }, { action: "snooze10", title: "Posponer 10 min" }] : [],
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  let url = (e.notification.data && e.notification.data.url) || "/#today";
  if (e.action === "snooze10") url += (url.includes("?") ? "&" : "?") + "snooze=10";
  const target = new URL(url, self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const win = wins.find((w) => new URL(w.url).origin === self.location.origin);
    if (win) { await win.focus(); win.postMessage({ type: "alice-open", url: target }); return; }
    await self.clients.openWindow(target);
  })());
});
