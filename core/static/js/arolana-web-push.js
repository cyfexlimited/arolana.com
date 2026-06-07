(function () {
    'use strict';

    const state = {
        config: null,
        registration: null,
        busy: false
    };

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    function storageGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (error) {
            return null;
        }
    }

    function storageSet(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (error) {
            return null;
        }
        return value;
    }

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, function (char) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            }[char];
        });
    }

    function isStandaloneIOS() {
        return Boolean(window.navigator.standalone);
    }

    function isIOS() {
        return /iPad|iPhone|iPod/.test(navigator.userAgent) || (
            navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1
        );
    }

    function isSupported() {
        return (
            'serviceWorker' in navigator &&
            'PushManager' in window &&
            'Notification' in window
        );
    }

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; i += 1) {
            outputArray[i] = rawData.charCodeAt(i);
        }

        return outputArray;
    }

    function browserName() {
        const ua = navigator.userAgent;
        if (/Edg\//.test(ua)) return 'Edge';
        if (/Chrome\//.test(ua) && !/Edg\//.test(ua)) return 'Chrome';
        if (/Firefox\//.test(ua)) return 'Firefox';
        if (/Safari\//.test(ua) && !/Chrome\//.test(ua)) return 'Safari';
        return 'Browser';
    }

    async function fetchConfig() {
        const response = await fetch('/notifications/api/push/config/', {
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });

        if (!response.ok) throw new Error('Push configuration could not be loaded.');
        state.config = await response.json();
        return state.config;
    }

    async function getRegistration() {
        if (state.registration) return state.registration;
        if (!state.config) await fetchConfig();

        state.registration = await navigator.serviceWorker.register(
            state.config.service_worker_url || '/service-worker.js',
            { scope: '/' }
        );

        return state.registration;
    }

    async function saveSubscription(subscription) {
        if (!state.config) await fetchConfig();

        const response = await fetch(state.config.subscribe_url || '/notifications/api/push/subscribe/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                subscription: subscription.toJSON(),
                device_name: isIOS() ? 'iPhone or iPad' : 'This device',
                browser_name: browserName()
            })
        });

        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || 'Push subscription could not be saved.');
        }

        return data;
    }

    async function enablePush() {
        if (state.busy) return { success: false, message: 'Already working.' };
        state.busy = true;

        try {
            if (!isSupported()) {
                throw new Error('This browser does not support web push notifications.');
            }

            const config = state.config || await fetchConfig();
            if (!config.authenticated) {
                throw new Error(config.reason || 'Please sign in to enable Arolana phone alerts.');
            }

            if (!config.enabled || !config.public_key) {
                throw new Error(config.reason || 'Arolana push notifications are not configured yet.');
            }

            if (isIOS() && !isStandaloneIOS() && !window.matchMedia('(display-mode: standalone)').matches) {
                throw new Error('On iPhone, add Arolana to your Home Screen first, then enable alerts from the app icon.');
            }

            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                throw new Error('Notification permission was not granted.');
            }

            const registration = await getRegistration();
            let subscription = await registration.pushManager.getSubscription();

            if (!subscription) {
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(config.public_key)
                });
            }

            await saveSubscription(subscription);
            storageSet('arolanaPushEnabled', '1');
            removePrompt();
            return { success: true };
        } catch (error) {
            showPrompt(error.message || 'Could not enable phone alerts.', true);
            return { success: false, message: error.message };
        } finally {
            state.busy = false;
        }
    }

    async function syncExistingSubscription() {
        if (!isSupported()) return;
        const config = state.config || await fetchConfig();
        if (!config.enabled || !config.authenticated || Notification.permission !== 'granted') return;

        const registration = await getRegistration();
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) await saveSubscription(subscription);
    }

    async function disablePush() {
        if (!isSupported()) return { success: true };

        const config = state.config || await fetchConfig();
        const registration = await getRegistration();
        const subscription = await registration.pushManager.getSubscription();
        const endpoint = subscription ? subscription.endpoint : '';

        if (subscription) await subscription.unsubscribe();

        await fetch(config.unsubscribe_url || '/notifications/api/push/unsubscribe/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ endpoint })
        });

        storageSet('arolanaPushEnabled', '0');
        return { success: true };
    }

    function removePrompt() {
        const prompt = document.getElementById('arolana-push-optin');
        if (prompt) prompt.remove();
    }

    function showPrompt(message, isError) {
        if (document.getElementById('arolana-push-optin')) {
            const existing = document.getElementById('arolana-push-optin-message');
            if (existing && message) existing.textContent = message;
            return;
        }

        const prompt = document.createElement('div');
        prompt.id = 'arolana-push-optin';
        prompt.innerHTML = `
            <div class="arolana-push-optin-card ${isError ? 'is-error' : ''}">
                <button type="button" class="arolana-push-optin-close" aria-label="Close phone alerts prompt">&times;</button>
                <strong>Phone alerts</strong>
                <p id="arolana-push-optin-message">${escapeHtml(message || 'Get Arolana chat, order, and admin alerts on this device.')}</p>
                <div class="arolana-push-optin-actions">
                    <button type="button" class="arolana-push-optin-primary">Enable</button>
                    <button type="button" class="arolana-push-optin-secondary">Not now</button>
                </div>
            </div>
        `;

        document.body.appendChild(prompt);

        prompt.querySelector('.arolana-push-optin-primary').addEventListener('click', enablePush);
        prompt.querySelector('.arolana-push-optin-secondary').addEventListener('click', function () {
            storageSet('arolanaPushPromptDismissed', String(Date.now()));
            removePrompt();
        });
        prompt.querySelector('.arolana-push-optin-close').addEventListener('click', function () {
            storageSet('arolanaPushPromptDismissed', String(Date.now()));
            removePrompt();
        });
    }

    function injectStyles() {
        if (document.getElementById('arolana-push-optin-style')) return;

        const style = document.createElement('style');
        style.id = 'arolana-push-optin-style';
        style.textContent = `
            #arolana-push-optin {
                bottom: max(6.25rem, env(safe-area-inset-bottom));
                left: 1rem;
                max-width: 21rem;
                position: fixed;
                z-index: 99998;
            }

            .arolana-push-optin-card {
                background: #111827;
                border: 1px solid rgba(255,255,255,.12);
                border-radius: 14px;
                box-shadow: 0 22px 60px rgba(15,23,42,.28);
                color: #fff;
                padding: .95rem;
                position: relative;
            }

            .arolana-push-optin-card.is-error {
                background: #7f1d1d;
            }

            .arolana-push-optin-card strong {
                display: block;
                font-size: .92rem;
                font-weight: 900;
                margin-bottom: .25rem;
            }

            .arolana-push-optin-card p {
                color: rgba(255,255,255,.82);
                font-size: .82rem;
                line-height: 1.45;
                margin: 0 1.35rem .75rem 0;
            }

            .arolana-push-optin-actions {
                display: flex;
                gap: .5rem;
            }

            .arolana-push-optin-actions button,
            .arolana-push-optin-close {
                border: 0;
                cursor: pointer;
                font: inherit;
            }

            .arolana-push-optin-primary,
            .arolana-push-optin-secondary {
                border-radius: 999px;
                font-size: .78rem;
                font-weight: 900;
                min-height: 34px;
                padding: .45rem .75rem;
            }

            .arolana-push-optin-primary {
                background: #2563eb;
                color: #fff;
            }

            .arolana-push-optin-secondary {
                background: rgba(255,255,255,.12);
                color: #fff;
            }

            .arolana-push-optin-close {
                align-items: center;
                background: rgba(255,255,255,.12);
                border-radius: 999px;
                color: #fff;
                display: flex;
                height: 1.65rem;
                justify-content: center;
                position: absolute;
                right: .65rem;
                top: .65rem;
                width: 1.65rem;
            }

            @media (max-width: 640px) {
                #arolana-push-optin {
                    bottom: max(5.75rem, env(safe-area-inset-bottom));
                    left: .75rem;
                    max-width: none;
                    right: .75rem;
                }
            }
        `;
        document.head.appendChild(style);
    }

    async function maybePrompt() {
        if (!isSupported()) return;

        const config = await fetchConfig();
        if (!config.enabled || !config.authenticated) return;
        if (Notification.permission === 'denied') return;
        if (storageGet('arolanaPushEnabled') === '1') {
            await syncExistingSubscription();
            return;
        }

        const dismissedAt = Number(storageGet('arolanaPushPromptDismissed') || 0);
        const oneDay = 24 * 60 * 60 * 1000;
        if (dismissedAt && Date.now() - dismissedAt < oneDay) return;

        if (Notification.permission === 'granted') {
            await syncExistingSubscription();
            return;
        }

        injectStyles();
        window.setTimeout(function () {
            showPrompt();
        }, 5000);
    }

    window.ArolanaWebPush = {
        enable: enablePush,
        disable: disablePush,
        sync: syncExistingSubscription,
        config: fetchConfig
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', maybePrompt);
    } else {
        maybePrompt();
    }
})();
