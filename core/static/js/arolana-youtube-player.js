(function (window, document) {
    "use strict";

    const PLAYER_SELECTOR = "iframe[src*='youtube.com/embed/'], iframe[src*='youtube-nocookie.com/embed/']";
    const players = new Map();
    let apiPromise;
    let sequence = 0;

    function safeInternalUrl(value) {
        try {
            const url = new URL(String(value || ""), window.location.origin);
            return url.origin === window.location.origin ? url.pathname + url.search + url.hash : "";
        } catch (error) {
            return "";
        }
    }

    function playerUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            url.searchParams.set("rel", "0");
            url.searchParams.set("playsinline", "1");
            url.searchParams.set("enablejsapi", "1");
            if (!url.searchParams.has("origin") && window.location.origin.indexOf("http") === 0) {
                url.searchParams.set("origin", window.location.origin);
            }
            return url.toString();
        } catch (error) {
            return value;
        }
    }

    function emit(name, detail) {
        window.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
        if (Array.isArray(window.dataLayer)) {
            window.dataLayer.push(Object.assign({ event: name }, detail || {}));
        }
    }

    function classifyPlayerError(code) {
        if (code === 101 || code === 150) return "embedding_disabled";
        if (code === 153) return "client_identity_missing";
        if (code === 100) return "missing_private_or_deleted";
        if (code === 5) return "html5_playback_error";
        if (code === 2) return "invalid_video_parameter";
        return "youtube_playback_error";
    }

    function youtubeVideoId(iframe) {
        try {
            const url = new URL(iframe.src, window.location.origin);
            const match = url.pathname.match(/\/embed\/([A-Za-z0-9_-]+)/);
            return match ? match[1] : "";
        } catch (error) {
            return "";
        }
    }

    function exitFullscreenForOverlay() {
        try {
            if (document.fullscreenElement && document.exitFullscreen) {
                document.exitFullscreen().catch(function () {});
            } else if (document.webkitFullscreenElement && document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            }
        } catch (error) {}
    }

    function inferContext(iframe) {
        const configuredUrl = safeInternalUrl(iframe.dataset.arolanaContextUrl);
        const path = window.location.pathname;
        if (configuredUrl) {
            return { url: configuredUrl, label: iframe.dataset.arolanaContextLabel || "View details", type: iframe.dataset.arolanaContextType || "general" };
        }
        if (/\/products?\//i.test(path)) return { url: path, label: "View Product", type: "product" };
        if (/\/(services?|providers?|installers?|projects?)\//i.test(path)) return { url: path, label: "View Service", type: "service" };
        return null;
    }

    function recommendationLinks(iframe) {
        const scope = iframe.closest("main, article, section") || document;
        return Array.from(scope.querySelectorAll("[data-recommendation-section] a[href], a[data-recommendation-section][href]"))
            .map(function (anchor) {
                return { url: safeInternalUrl(anchor.href), label: (anchor.textContent || "View recommendation").trim().slice(0, 80) };
            })
            .filter(function (item) { return item.url; })
            .slice(0, 3);
    }

    function action(url, label, className, onClick) {
        const element = document.createElement(url ? "a" : "button");
        element.className = className;
        element.textContent = label;
        if (url) element.href = url;
        else element.type = "button";
        element.addEventListener("click", onClick);
        return element;
    }

    function buildOverlay(iframe, replay) {
        const overlay = document.createElement("div");
        overlay.className = "arolana-youtube-end-screen";
        overlay.hidden = true;
        overlay.setAttribute("aria-live", "polite");

        const title = document.createElement("strong");
        title.textContent = "Keep exploring on Arolana";
        overlay.appendChild(title);

        const actions = document.createElement("div");
        actions.className = "arolana-youtube-end-screen__actions";
        actions.appendChild(action("", "Replay Video", "arolana-youtube-end-screen__primary", replay));

        const context = inferContext(iframe);
        if (context) {
            actions.appendChild(action(context.url, context.label, "arolana-youtube-end-screen__secondary", function () {
                emit(context.type === "product" ? "youtube_end_screen_view_product" : "youtube_end_screen_view_service");
            }));
        }
        recommendationLinks(iframe).forEach(function (item) {
            actions.appendChild(action(item.url, item.label, "arolana-youtube-end-screen__recommendation", function () {
                emit("youtube_end_screen_recommendation_click", { url: item.url });
            }));
        });
        overlay.appendChild(actions);
        return overlay;
    }

    function buildErrorFallback(iframe) {
        const fallback = document.createElement("div");
        fallback.className = "arolana-youtube-fallback";
        fallback.hidden = true;
        const message = document.createElement("strong");
        message.textContent = "This video cannot be played here.";
        fallback.appendChild(message);
        try {
            const url = new URL(iframe.src, window.location.origin);
            const match = url.pathname.match(/\/embed\/([A-Za-z0-9_-]+)/);
            if (match && match[1]) {
                const link = document.createElement("a");
                link.href = "https://www.youtube.com/watch?v=" + encodeURIComponent(match[1]);
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = "Watch on YouTube";
                fallback.appendChild(link);
            }
        } catch (error) {}
        return fallback;
    }

    function loadApi() {
        if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
        if (apiPromise) return apiPromise;
        apiPromise = new Promise(function (resolve, reject) {
            let settled = false;
            function finish() {
                if (settled || !window.YT || !window.YT.Player) return;
                settled = true;
                window.clearInterval(poll);
                window.clearTimeout(timeout);
                resolve(window.YT);
            }
            const previous = window.onYouTubeIframeAPIReady;
            window.onYouTubeIframeAPIReady = function () {
                if (typeof previous === "function") previous();
                finish();
            };
            const poll = window.setInterval(finish, 25);
            const timeout = window.setTimeout(function () {
                if (settled) return;
                settled = true;
                window.clearInterval(poll);
                reject(new Error("youtube_iframe_api_timeout"));
            }, 15000);
            if (!document.querySelector("script[src*='youtube.com/iframe_api']")) {
                const script = document.createElement("script");
                script.src = "https://www.youtube.com/iframe_api";
                script.async = true;
                document.head.appendChild(script);
            }
        });
        return apiPromise;
    }

    function enhance(iframe) {
        if (!iframe || iframe.dataset.arolanaYoutubeEnhanced === "true") return;
        iframe.dataset.arolanaYoutubeEnhanced = "true";
        const normalizedSrc = playerUrl(iframe.src);
        if (normalizedSrc !== iframe.src) iframe.src = normalizedSrc;
        if (!iframe.id) iframe.id = "arolana-youtube-player-" + (++sequence);

        const wrapper = document.createElement("div");
        wrapper.className = "arolana-youtube-player";
        iframe.parentNode.insertBefore(wrapper, iframe);
        wrapper.appendChild(iframe);

        const state = {
            iframe: iframe,
            wrapper: wrapper,
            overlay: null,
            player: null,
            destroyed: false,
            started: false,
            completed: false,
            replayPending: false,
            fallback: null
        };
        const overlay = buildOverlay(iframe, function () {
            if (state.replayPending || !state.player) return;
            state.replayPending = true;
            state.started = false;
            state.completed = false;
            overlay.hidden = true;
            state.player.seekTo(0, true);
            state.player.playVideo();
            emit("youtube_video_replayed");
        });
        state.overlay = overlay;
        wrapper.appendChild(overlay);
        state.fallback = buildErrorFallback(iframe);
        wrapper.appendChild(state.fallback);
        players.set(iframe.id, state);

        loadApi().then(function (YT) {
            if (state.destroyed || !iframe.isConnected) return;
            state.player = new YT.Player(iframe, {
                events: {
                    onStateChange: function (event) {
                        if (event.data === YT.PlayerState.ENDED) {
                            if (state.completed) return;
                            state.completed = true;
                            state.replayPending = false;
                            exitFullscreenForOverlay();
                            state.fallback.hidden = true;
                            overlay.hidden = false;
                            emit("youtube_video_completed");
                        } else if (event.data === YT.PlayerState.PLAYING) {
                            overlay.hidden = true;
                            state.fallback.hidden = true;
                            state.replayPending = false;
                            if (!state.started) {
                                state.started = true;
                                emit("youtube_video_started");
                            }
                        }
                    },
                    onError: function (event) {
                        const errorCode = Number(event.data || 0);
                        const details = {
                            error_code: errorCode,
                            category: classifyPlayerError(errorCode),
                            video_id: youtubeVideoId(iframe)
                        };
                        emit("youtube_video_error", details);
                        if (/^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname)) {
                            window.console.warn(
                                "Arolana YouTube playback failed " +
                                JSON.stringify(details)
                            );
                        }
                        overlay.hidden = true;
                        state.fallback.hidden = false;
                    }
                }
            });
        }).catch(function () { overlay.hidden = true; });
    }

    function destroy(iframe) {
        if (!iframe || !iframe.id) return;
        const state = players.get(iframe.id);
        if (!state) return;
        state.destroyed = true;
        try {
            if (state.player && typeof state.player.destroy === "function") state.player.destroy();
        } catch (error) {}
        players.delete(iframe.id);
        if (state.wrapper && state.wrapper.isConnected) state.wrapper.remove();
    }

    function cleanupRemoved(root) {
        if (!root || root.nodeType !== 1) return;
        if (root.isConnected) return;
        if (root.matches && root.matches("iframe[data-arolana-youtube-enhanced='true']")) destroy(root);
        if (root.querySelectorAll) {
            root.querySelectorAll("iframe[data-arolana-youtube-enhanced='true']").forEach(destroy);
        }
    }

    function scan(root) {
        if (root.matches && root.matches(PLAYER_SELECTOR)) enhance(root);
        if (root.querySelectorAll) root.querySelectorAll(PLAYER_SELECTOR).forEach(enhance);
    }

    function start() {
        scan(document);
        new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                if (mutation.type === "attributes") {
                    scan(mutation.target);
                    return;
                }
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) scan(node);
                });
                mutation.removedNodes.forEach(cleanupRemoved);
            });
        }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
    }

    window.ArolanaYouTubePlayer = { enhance: enhance, scan: scan, destroy: destroy, safeInternalUrl: safeInternalUrl, classifyPlayerError: classifyPlayerError };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})(window, document);
