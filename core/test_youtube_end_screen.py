from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ArolanaYouTubeEndScreenTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = (
            Path(settings.BASE_DIR) / "core/static/js/arolana-youtube-player.js"
        ).read_text(encoding="utf-8")
        cls.base_template = (
            Path(settings.BASE_DIR) / "templates/base/base.html"
        ).read_text(encoding="utf-8")
        cls.landing_template = (
            Path(settings.BASE_DIR) / "templates/landing_pages/landing_page_detail.html"
        ).read_text(encoding="utf-8")
        cls.landing_script = (
            Path(settings.BASE_DIR)
            / "landing_pages/static/landing_pages/js/landing_pages.js"
        ).read_text(encoding="utf-8")
        cls.root_urls = (
            Path(settings.BASE_DIR) / "arolana_config/urls.py"
        ).read_text(encoding="utf-8")
        cls.video_watch_template = (
            Path(settings.BASE_DIR) / "templates/videos/watch.html"
        ).read_text(encoding="utf-8")
        cls.video_gallery_template = (
            Path(settings.BASE_DIR) / "templates/videos/gallery_page.html"
        ).read_text(encoding="utf-8")

    def test_base_loads_shared_player_once(self):
        self.assertEqual(
            self.base_template.count("js/arolana-youtube-player.js"), 1
        )

    def test_player_standardizes_iframe_api_parameters(self):
        self.assertIn('searchParams.set("rel", "0")', self.script)
        self.assertIn('searchParams.set("playsinline", "1")', self.script)
        self.assertIn('searchParams.set("enablejsapi", "1")', self.script)

    def test_ended_replay_and_independent_players_are_supported(self):
        self.assertIn("YT.PlayerState.ENDED", self.script)
        self.assertIn("player.seekTo(0, true)", self.script)
        self.assertIn("player.playVideo()", self.script)
        self.assertIn("const players = new Map()", self.script)
        self.assertIn("players.set(iframe.id, state)", self.script)
        self.assertIn("players.delete(iframe.id)", self.script)
        self.assertIn("state.player.destroy()", self.script)

    def test_overlay_uses_only_internal_context_links(self):
        self.assertIn("url.origin === window.location.origin", self.script)
        self.assertIn('label: "View Product"', self.script)
        self.assertIn('label: "View Service"', self.script)

    def test_missing_recommendations_and_embed_errors_fail_safely(self):
        self.assertIn(".slice(0, 3)", self.script)
        self.assertIn("onError: function (event)", self.script)
        self.assertIn("overlay.hidden = true", self.script)
        self.assertIn('link.textContent = "Watch on YouTube"', self.script)
        self.assertIn('state.fallback.hidden = false', self.script)
        self.assertIn('category: classifyPlayerError(errorCode)', self.script)
        self.assertIn('youtube_video_error', self.script)
        self.assertIn("if (normalizedSrc !== iframe.src) iframe.src = normalizedSrc", self.script)
        self.assertIn('"Arolana YouTube playback failed " +', self.script)
        self.assertIn("JSON.stringify(details)", self.script)

    def test_dynamically_assigned_landing_page_iframe_is_detected(self):
        self.assertIn('attributeFilter: ["src"]', self.script)
        self.assertIn('scan(mutation.target)', self.script)
        self.assertNotIn("arolana-landing-inline-video-player", self.landing_template)
        self.assertIn("cloneNode(false)", self.landing_script)
        self.assertIn("ArolanaYouTubePlayer.destroy(videoFrame)", self.landing_script)

    def test_api_loading_and_analytics_are_guarded(self):
        self.assertIn("if (apiPromise) return apiPromise", self.script)
        self.assertIn("window.setInterval(finish, 25)", self.script)
        self.assertIn("if (state.completed) return", self.script)
        self.assertIn("if (!state.started)", self.script)
        self.assertIn("if (state.replayPending", self.script)

    def test_diagnostic_embed_page_is_not_publicly_routed(self):
        self.assertNotIn('"youtube-embed-test/"', self.root_urls)

    def test_dedicated_video_pages_inherit_shared_base(self):
        self.assertIn('extends "base/base.html"', self.video_watch_template)
        self.assertIn('extends "base/base.html"', self.video_gallery_template)
