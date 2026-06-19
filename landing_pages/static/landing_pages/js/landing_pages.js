/*!
 * Arolana Landing Pages — Perfect Polish
 * Handles mini nav, smooth section scroll, FAQ accordion, in-page video modal,
 * duplicate-load protection, and dynamically rendered admin sections.
 */
(function () {
    "use strict";

    const page = document.querySelector(".arolana-landing-page");
    if (!page) return;

    if (page.dataset.lpScriptReady === "true") return;
    page.dataset.lpScriptReady = "true";

    const miniNav = page.querySelector(".lp-mini-nav");
    const navToggle = page.querySelector(".lp-mobile-nav-toggle");
    const navLinks = Array.from(page.querySelectorAll("[data-lp-nav]"));
    const backToTop = page.querySelector(".lp-back-to-top");
    const videoModal = page.querySelector(".lp-video-modal");
    const videoFrame = videoModal ? videoModal.querySelector("iframe") : null;
    const videoClose = videoModal ? videoModal.querySelector(".lp-video-modal-close") : null;

    function prefersReducedMotion() {
        return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function getHeaderHeight() {
        const headerSelectors = [
            ".luxury-header",
            ".site-header",
            "header[role='banner']",
            "header"
        ];

        for (const selector of headerSelectors) {
            const header = document.querySelector(selector);
            if (!header) continue;

            const style = window.getComputedStyle(header);
            const isVisible = style.display !== "none" && style.visibility !== "hidden";
            const isFixedOrSticky = style.position === "fixed" || style.position === "sticky";

            if (isVisible && isFixedOrSticky) {
                return header.offsetHeight || 0;
            }
        }

        return 0;
    }

    function getStickyOffset() {
        const miniNavHeight = miniNav ? miniNav.offsetHeight : 0;
        return getHeaderHeight() + miniNavHeight + 18;
    }

    function scrollToSection(section) {
        if (!section) return;

        const targetTop = section.getBoundingClientRect().top + window.pageYOffset - getStickyOffset();

        window.scrollTo({
            top: Math.max(targetTop, 0),
            behavior: prefersReducedMotion() ? "auto" : "smooth"
        });
    }

    function closeMobileNav() {
        if (!miniNav) return;
        miniNav.classList.remove("is-open");
        if (navToggle) navToggle.setAttribute("aria-expanded", "false");
    }

    function setupMiniNav() {
        if (navToggle && miniNav) {
            navToggle.setAttribute("aria-expanded", "false");

            navToggle.addEventListener("click", function () {
                const isOpen = miniNav.classList.toggle("is-open");
                navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
            });
        }

        navLinks.forEach(function (link) {
            link.addEventListener("click", function (event) {
                const targetId = this.dataset.lpNav;
                const target = targetId ? document.getElementById(targetId) : null;

                if (!target) return;

                event.preventDefault();
                scrollToSection(target);
                closeMobileNav();

                if (history.pushState) {
                    history.pushState(null, "", "#" + targetId);
                }
            });
        });
    }

    function setupFaqs() {
        const faqButtons = page.querySelectorAll(".lp-faq-question");

        faqButtons.forEach(function (button) {
            const item = button.closest(".lp-faq-item");
            const answer = item ? item.querySelector(".lp-faq-answer") : null;

            button.setAttribute("aria-expanded", item && item.classList.contains("is-open") ? "true" : "false");

            if (answer && !answer.id) {
                answer.id = "lp-faq-answer-" + Math.random().toString(36).slice(2, 9);
                button.setAttribute("aria-controls", answer.id);
            }

            button.addEventListener("click", function () {
                if (!item) return;

                const faqList = item.closest(".lp-faq-list");

                if (faqList) {
                    faqList.querySelectorAll(".lp-faq-item").forEach(function (otherItem) {
                        if (otherItem !== item) {
                            otherItem.classList.remove("is-open");
                            const otherButton = otherItem.querySelector(".lp-faq-question");
                            if (otherButton) otherButton.setAttribute("aria-expanded", "false");
                        }
                    });
                }

                const isOpen = item.classList.toggle("is-open");
                button.setAttribute("aria-expanded", isOpen ? "true" : "false");
            });
        });
    }

    function setActiveNav() {
        if (!navLinks.length) return;

        let activeId = "";
        const offset = getStickyOffset() + 35;

        navLinks.forEach(function (link) {
            const section = document.getElementById(link.dataset.lpNav);
            if (!section) return;

            const rect = section.getBoundingClientRect();

            if (rect.top <= offset && rect.bottom > offset) {
                activeId = link.dataset.lpNav;
            }
        });

        if (!activeId && navLinks[0]) {
            const firstTarget = document.getElementById(navLinks[0].dataset.lpNav);
            if (firstTarget && firstTarget.getBoundingClientRect().top > offset) {
                activeId = navLinks[0].dataset.lpNav;
            }
        }

        navLinks.forEach(function (link) {
            link.classList.toggle("is-active", link.dataset.lpNav === activeId);
        });
    }

    function syncBackToTop() {
        if (!backToTop) return;
        backToTop.classList.toggle("is-visible", window.scrollY > 600);
    }

    function normalizeYouTubeEmbed(url) {
        if (!url) return "";

        try {
            const parsedUrl = new URL(url, window.location.origin);
            let videoId = "";
            const host = parsedUrl.hostname.replace(/^www\./, "");
            const path = parsedUrl.pathname || "";

            if (host.includes("youtu.be")) {
                videoId = path.replace(/^\//, "");
            }

            if (host.includes("youtube.com") || host.includes("youtube-nocookie.com")) {
                videoId = parsedUrl.searchParams.get("v") || "";

                if (!videoId && path.includes("/embed/")) {
                    videoId = path.split("/embed/")[1] || "";
                }

                if (!videoId && path.includes("/shorts/")) {
                    videoId = path.split("/shorts/")[1] || "";
                }

                if (!videoId && path.includes("/live/")) {
                    videoId = path.split("/live/")[1] || "";
                }
            }

            if (!videoId) return "";

            videoId = videoId.split("?")[0].split("&")[0].split("/")[0];

            return "https://www.youtube.com/embed/" + encodeURIComponent(videoId) + "?autoplay=1&rel=0&modestbranding=1&playsinline=1";
        } catch (error) {
            return "";
        }
    }

    function normalizeVimeoEmbed(url) {
        if (!url) return "";

        try {
            const parsedUrl = new URL(url, window.location.origin);
            if (!parsedUrl.hostname.includes("vimeo.com")) return "";

            const parts = parsedUrl.pathname.split("/").filter(Boolean);
            const videoId = parts.find(function (part) {
                return /^\d+$/.test(part);
            });

            if (!videoId) return "";

            return "https://player.vimeo.com/video/" + encodeURIComponent(videoId) + "?autoplay=1";
        } catch (error) {
            return "";
        }
    }

    function normalizeDirectVideo(url) {
        if (!url) return "";
        if (/\.(mp4|webm|ogg)(\?.*)?$/i.test(url)) return url;
        return "";
    }

    function getEmbedUrl(card) {
        const explicitEmbed = card.dataset.videoEmbed || "";
        const videoUrl = card.dataset.videoUrl || "";

        if (explicitEmbed) return explicitEmbed;

        return normalizeYouTubeEmbed(videoUrl) || normalizeVimeoEmbed(videoUrl) || normalizeDirectVideo(videoUrl);
    }

    function openVideo(card) {
        if (!card) return;

        const embedUrl = getEmbedUrl(card);
        const videoUrl = card.dataset.videoUrl || embedUrl || "";
        const videoTitle = card.dataset.videoTitle || "Arolana landing page video";

        if (!embedUrl) {
            if (videoUrl) window.open(videoUrl, "_blank", "noopener,noreferrer");
            return;
        }

        if (!videoModal || !videoFrame) {
            window.open(videoUrl || embedUrl, "_blank", "noopener,noreferrer");
            return;
        }

        videoFrame.src = embedUrl;
        videoFrame.title = videoTitle;

        videoModal.classList.add("is-open");
        videoModal.setAttribute("aria-hidden", "false");

        document.documentElement.classList.add("lp-video-open");
        document.body.classList.add("lp-video-open");

        if (videoClose) videoClose.focus({ preventScroll: true });
    }

    function closeVideo() {
        if (!videoModal || !videoFrame) return;

        videoModal.classList.remove("is-open");
        videoModal.setAttribute("aria-hidden", "true");
        videoFrame.src = "about:blank";

        document.documentElement.classList.remove("lp-video-open");
        document.body.classList.remove("lp-video-open");
    }

    function setupVideos() {
        page.addEventListener("click", function (event) {
            const trigger = event.target.closest(".lp-video-thumb, .lp-watch-btn");
            if (!trigger || !page.contains(trigger)) return;

            const card = trigger.closest(".lp-video-card");
            if (!card) return;

            event.preventDefault();
            event.stopPropagation();
            openVideo(card);
        });

        if (videoClose) videoClose.addEventListener("click", closeVideo);

        if (videoModal) {
            videoModal.addEventListener("click", function (event) {
                if (event.target === videoModal) closeVideo();
            });
        }
    }

    let scrollTicking = false;

    window.addEventListener("scroll", function () {
        if (scrollTicking) return;
        scrollTicking = true;

        window.requestAnimationFrame(function () {
            setActiveNav();
            syncBackToTop();
            scrollTicking = false;
        });
    }, { passive: true });

    if (backToTop) {
        backToTop.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeVideo();
            closeMobileNav();
        }
    });

    window.addEventListener("resize", function () {
        window.requestAnimationFrame(setActiveNav);
    }, { passive: true });

    window.addEventListener("load", function () {
        if (window.location.hash) {
            const target = document.getElementById(window.location.hash.replace("#", ""));
            if (target) {
                setTimeout(function () {
                    scrollToSection(target);
                }, 150);
            }
        }

        setActiveNav();
        syncBackToTop();
    });

    setupMiniNav();
    setupFaqs();
    setupVideos();
    setActiveNav();
    syncBackToTop();
})();
