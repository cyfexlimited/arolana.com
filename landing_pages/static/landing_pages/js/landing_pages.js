(function () {
    "use strict";

    const page = document.querySelector(".arolana-landing-page");
    if (!page) return;

    const miniNav = page.querySelector(".lp-mini-nav");
    const navToggle = page.querySelector(".lp-mobile-nav-toggle");
    const navLinks = Array.from(page.querySelectorAll("[data-lp-nav]"));
    const backToTop = page.querySelector(".lp-back-to-top");
    const videoModal = page.querySelector(".lp-video-modal");
    const videoFrame = videoModal ? videoModal.querySelector("iframe") : null;
    const videoClose = videoModal ? videoModal.querySelector(".lp-video-modal-close") : null;

    if (navToggle && miniNav) {
        navToggle.addEventListener("click", function () {
            miniNav.classList.toggle("is-open");
        });
    }

    navLinks.forEach(function (link) {
        link.addEventListener("click", function (event) {
            const target = document.getElementById(this.dataset.lpNav);
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({ behavior: "smooth", block: "start" });
            if (miniNav) miniNav.classList.remove("is-open");
        });
    });

    page.querySelectorAll(".lp-faq-question").forEach(function (button) {
        button.addEventListener("click", function () {
            const item = this.closest(".lp-faq-item");
            if (item) item.classList.toggle("is-open");
        });
    });

    function setActiveNav() {
        let activeId = "";
        navLinks.forEach(function (link) {
            const section = document.getElementById(link.dataset.lpNav);
            if (!section) return;
            const rect = section.getBoundingClientRect();
            if (rect.top <= 140 && rect.bottom > 140) activeId = link.dataset.lpNav;
        });
        navLinks.forEach(function (link) {
            link.classList.toggle("is-active", link.dataset.lpNav === activeId);
        });
    }

    function syncBackToTop() {
        if (!backToTop) return;
        backToTop.classList.toggle("is-visible", window.scrollY > 700);
    }

    window.addEventListener("scroll", function () {
        setActiveNav();
        syncBackToTop();
    }, { passive: true });

    if (backToTop) {
        backToTop.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    }

    function openVideo(card) {
        const embedUrl = card.dataset.videoEmbed || "";
        const videoUrl = card.dataset.videoUrl || "";
        if (!embedUrl) {
            window.open(videoUrl, "_blank", "noopener,noreferrer");
            return;
        }
        if (!videoModal || !videoFrame) return;
        videoFrame.src = embedUrl;
        videoModal.classList.add("is-open");
        videoModal.setAttribute("aria-hidden", "false");
        document.documentElement.style.overflow = "hidden";
    }

    function closeVideo() {
        if (!videoModal || !videoFrame) return;
        videoModal.classList.remove("is-open");
        videoModal.setAttribute("aria-hidden", "true");
        videoFrame.src = "about:blank";
        document.documentElement.style.overflow = "";
    }

    page.querySelectorAll(".lp-video-card").forEach(function (card) {
        card.addEventListener("click", function () {
            openVideo(card);
        });
    });

    if (videoClose) videoClose.addEventListener("click", closeVideo);
    if (videoModal) {
        videoModal.addEventListener("click", function (event) {
            if (event.target === videoModal) closeVideo();
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") closeVideo();
    });

    setActiveNav();
    syncBackToTop();
})();
