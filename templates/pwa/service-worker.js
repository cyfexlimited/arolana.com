{% load static %}
const AROLANA_CACHE = 'arolana-shell-v1';
const AROLANA_ICON = "{% static 'admin/images/arolana-logo.png' %}";
const AROLANA_BADGE = "{% static 'admin/images/favicon.ico' %}";

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(AROLANA_CACHE).then(function (cache) {
            return cache.addAll([
                '/',
                AROLANA_ICON,
                AROLANA_BADGE
            ]).catch(function () {
                return Promise.resolve();
            });
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', function (event) {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('push', function (event) {
    let payload = {};

    if (event.data) {
        try {
            payload = event.data.json();
        } catch (error) {
            payload = {
                title: 'Arolana notification',
                body: event.data.text()
            };
        }
    }

    const title = payload.title || 'Arolana notification';
    const options = {
        body: payload.body || '',
        icon: payload.icon || AROLANA_ICON,
        badge: payload.badge || AROLANA_BADGE,
        tag: payload.tag || 'arolana-notification',
        data: {
            url: payload.url || '/notifications/',
            notification_id: payload.notification_id || null
        },
        renotify: true,
        requireInteraction: Boolean(payload.require_interaction)
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();

    const targetUrl = new URL(
        event.notification.data && event.notification.data.url
            ? event.notification.data.url
            : '/notifications/',
        self.location.origin
    ).href;

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clients) {
            for (const client of clients) {
                if (client.url === targetUrl && 'focus' in client) {
                    return client.focus();
                }
            }

            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }

            return null;
        })
    );
});
