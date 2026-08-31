import json
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from core.youtube_service import (
    SCOPE,
    YouTubeUploadError,
    get_video_embeddability,
    refresh_access_token,
    safe_upload_error_details,
    upload_video,
)


def response(*, status_code=200, payload=None, headers=None):
    item = Mock()
    item.status_code = status_code
    item.ok = 200 <= status_code < 300
    item.headers = headers or {}
    item.json.return_value = payload or {}
    item.text = json.dumps(payload or {})
    return item


@override_settings(
    YOUTUBE_CLIENT_ID="client",
    YOUTUBE_CLIENT_SECRET="secret",
    YOUTUBE_REFRESH_TOKEN="refresh",
    YOUTUBE_DEFAULT_PRIVACY="unlisted",
)
class YouTubeEmbeddabilityTests(SimpleTestCase):
    def test_oauth_scope_supports_upload_and_read_only_status_checks(self):
        self.assertIn("youtube.upload", SCOPE)
        self.assertIn("youtube.readonly", SCOPE)

    @patch("core.youtube_service.requests.put")
    @patch("core.youtube_service.requests.post")
    @patch("core.youtube_service.refresh_access_token", return_value="access")
    def test_arolana_upload_explicitly_enables_embedding(
        self, _refresh, mock_post, mock_put
    ):
        mock_post.return_value = response(
            headers={"Location": "https://upload.example/session"}
        )
        mock_put.return_value = response(
            payload={
                "id": "abc123xyz90",
                "status": {"privacyStatus": "unlisted", "embeddable": True},
            }
        )

        result = upload_video(
            SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4"),
            title="Arolana test",
        )

        metadata = json.loads(mock_post.call_args.kwargs["data"])
        self.assertIs(metadata["status"]["embeddable"], True)
        self.assertEqual(metadata["status"]["privacyStatus"], "unlisted")
        self.assertIs(result["embeddable"], True)
        self.assertEqual(result["ownership"], "arolana")

    @patch("core.youtube_service.requests.get")
    def test_read_only_status_check_classifies_embeddable_video(self, mock_get):
        mock_get.return_value = response(
            payload={
                "items": [
                    {
                        "id": "abc123xyz90",
                        "status": {
                            "embeddable": True,
                            "privacyStatus": "unlisted",
                            "uploadStatus": "processed",
                        },
                        "snippet": {"channelId": "channel", "channelTitle": "Arolana"},
                        "processingDetails": {"processingStatus": "succeeded"},
                    }
                ]
            }
        )

        result = get_video_embeddability("abc123xyz90", access_token="access")

        self.assertEqual(result["state"], "embeddable")
        self.assertIs(result["embeddable"], True)
        self.assertNotIn("access", str(result))

    @patch("core.youtube_service.requests.get")
    def test_insufficient_scope_is_safe_and_distinguishable(self, mock_get):
        mock_get.return_value = response(
            status_code=403,
            payload={"error": {"errors": [{"reason": "insufficientPermissions"}]}},
        )

        result = get_video_embeddability("abc123xyz90", access_token="access")

        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["http_status"], 403)
        self.assertEqual(result["reason"], "insufficientPermissions")
        self.assertNotIn("access", str(result))

    @patch("core.youtube_service.requests.put")
    @patch("core.youtube_service.requests.post")
    @patch("core.youtube_service.refresh_access_token", return_value="access")
    def test_arolana_owned_non_embeddable_upload_is_problem_state(
        self, _refresh, mock_post, mock_put
    ):
        mock_post.return_value = response(
            headers={"Location": "https://upload.example/session"}
        )
        mock_put.return_value = response(
            payload={"id": "abc123xyz90", "status": {"embeddable": False}}
        )

        with self.assertRaises(YouTubeUploadError) as raised:
            upload_video(
                SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4"),
                title="Arolana test",
            )
        self.assertEqual(raised.exception.stage, "video_upload")
        self.assertEqual(raised.exception.code, "youtube_upload_failed")

    @patch("core.youtube_service.requests.post")
    def test_token_refresh_failure_is_structured_and_hides_provider_body(self, mock_post):
        mock_post.return_value = response(
            status_code=400,
            payload={"error": "access_token=provider-secret"},
        )

        with self.assertRaises(YouTubeUploadError) as raised:
            refresh_access_token("refresh-token")

        self.assertEqual(raised.exception.stage, "token_refresh")
        self.assertEqual(raised.exception.code, "youtube_token_refresh_failed")
        self.assertEqual(str(raised.exception), "Could not refresh the Arolana YouTube connection.")
        self.assertNotIn("provider-secret", str(raised.exception))

    @patch("core.youtube_service.requests.post")
    @patch("core.youtube_service.refresh_access_token", return_value="access")
    def test_upload_initialization_failure_is_structured_and_hides_provider_body(
        self, _refresh, mock_post
    ):
        mock_post.return_value = response(
            status_code=500,
            payload={"error": "Authorization: Bearer provider-secret"},
        )

        with self.assertRaises(YouTubeUploadError) as raised:
            upload_video(SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4"), title="Test")

        self.assertEqual(safe_upload_error_details(raised.exception), {
            "stage": "upload_initialization",
            "code": "youtube_upload_init_failed",
            "message": "Could not start the YouTube upload.",
        })
        self.assertNotIn("provider-secret", str(raised.exception))

    @patch("core.youtube_service.requests.put")
    @patch("core.youtube_service.requests.post")
    @patch("core.youtube_service.refresh_access_token", return_value="access")
    def test_video_upload_failure_is_structured_and_hides_provider_body(
        self, _refresh, mock_post, mock_put
    ):
        mock_post.return_value = response(headers={"Location": "https://upload.example/session"})
        mock_put.return_value = response(
            status_code=500,
            payload={"error": "access_token=provider-secret"},
        )

        with self.assertRaises(YouTubeUploadError) as raised:
            upload_video(SimpleUploadedFile("video.mp4", b"video", content_type="video/mp4"), title="Test")

        self.assertEqual(raised.exception.stage, "video_upload")
        self.assertEqual(raised.exception.code, "youtube_upload_failed")
        self.assertNotIn("provider-secret", str(raised.exception))

    @patch("core.youtube_service.refresh_access_token", return_value="access")
    def test_empty_video_is_a_safe_validation_failure(self, _refresh):
        with self.assertRaises(YouTubeUploadError) as raised:
            upload_video(SimpleUploadedFile("video.mp4", b"", content_type="video/mp4"), title="Test")

        self.assertEqual(raised.exception.stage, "validation")
        self.assertEqual(raised.exception.code, "youtube_validation_failed")
