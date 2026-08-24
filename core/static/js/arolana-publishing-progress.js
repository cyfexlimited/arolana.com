(function (window, document) {
    "use strict";

    function mount(options) {
        const container = options && options.container;
        if (!container) return null;

        const panel = document.createElement("div");
        panel.className = "arolana-publishing-progress";
        panel.hidden = true;
        panel.setAttribute("role", "status");
        panel.setAttribute("aria-live", "polite");
        panel.innerHTML = [
            '<span class="arolana-publishing-spinner" aria-hidden="true"></span>',
            '<div class="arolana-publishing-copy">',
            '<strong class="arolana-publishing-title"></strong>',
            '<span class="arolana-publishing-stage"></span>',
            '<small class="arolana-publishing-warning">Please keep this page open while your video uploads.</small>',
            '</div>'
        ].join("");
        container.appendChild(panel);

        const title = panel.querySelector(".arolana-publishing-title");
        const stage = panel.querySelector(".arolana-publishing-stage");
        const warning = panel.querySelector(".arolana-publishing-warning");
        const controls = Array.from(container.querySelectorAll("button"));
        let busy = false;

        function lock(value) {
            busy = Boolean(value);
            container.classList.toggle("arolana-publishing-locked", busy);
            container.setAttribute("aria-busy", busy ? "true" : "false");
            controls.forEach(function (control) {
                if (control === panel) return;
                if (busy) {
                    control.dataset.arolanaWasDisabled = control.disabled ? "1" : "0";
                    control.disabled = true;
                } else if (control.dataset.arolanaWasDisabled !== "1") {
                    control.disabled = false;
                }
            });
        }

        return {
            get busy() { return busy; },
            start: function (message) {
                panel.hidden = false;
                panel.classList.remove("is-complete", "is-error");
                title.textContent = options.title || "Publishing your video";
                stage.textContent = message || "Preparing your upload…";
                warning.hidden = false;
                lock(true);
            },
            update: function (message) {
                panel.hidden = false;
                stage.textContent = message || "";
            },
            finish: function (message) {
                panel.hidden = false;
                panel.classList.add("is-complete");
                title.textContent = options.successTitle || "Upload complete";
                stage.textContent = message || "Saved successfully.";
                warning.hidden = true;
                lock(false);
            },
            fail: function (message) {
                panel.hidden = false;
                panel.classList.add("is-error");
                title.textContent = options.failureTitle || "Upload needs attention";
                stage.textContent = message || "Please try again.";
                warning.hidden = true;
                lock(false);
            },
            reset: function () {
                panel.hidden = true;
                panel.classList.remove("is-complete", "is-error");
                lock(false);
            }
        };
    }

    if (!document.getElementById("arolana-publishing-progress-styles")) {
        const style = document.createElement("style");
        style.id = "arolana-publishing-progress-styles";
        style.textContent = ".arolana-publishing-progress{display:flex;align-items:center;gap:14px;margin-top:16px;padding:16px;border:1px solid #bfdbfe;border-radius:16px;background:#eff6ff;color:#0f172a;box-shadow:0 12px 28px rgba(15,23,42,.08)}.arolana-publishing-progress[hidden]{display:none}.arolana-publishing-copy{display:grid;gap:3px}.arolana-publishing-title{font-size:1rem}.arolana-publishing-stage{font-size:.9rem;font-weight:700;color:#334155}.arolana-publishing-warning{color:#64748b}.arolana-publishing-spinner{width:28px;height:28px;flex:0 0 28px;border:3px solid #bfdbfe;border-top-color:#2563eb;border-radius:50%;animation:arolana-publishing-spin .8s linear infinite}.arolana-publishing-progress.is-complete{border-color:#bbf7d0;background:#f0fdf4}.arolana-publishing-progress.is-complete .arolana-publishing-spinner{animation:none;border-color:#22c55e;background:#22c55e;box-shadow:inset 0 0 0 7px #f0fdf4}.arolana-publishing-progress.is-error{border-color:#fecaca;background:#fef2f2}.arolana-publishing-progress.is-error .arolana-publishing-spinner{animation:none;border-color:#ef4444}.arolana-publishing-locked>*:not(.arolana-publishing-progress){opacity:.55;pointer-events:none}.arolana-publishing-progress{opacity:1!important;pointer-events:auto!important}@keyframes arolana-publishing-spin{to{transform:rotate(360deg)}}@media(prefers-reduced-motion:reduce){.arolana-publishing-spinner{animation-duration:1.8s}}";
        document.head.appendChild(style);
    }

    window.ArolanaPublishingProgress = { mount: mount };
})(window, document);
