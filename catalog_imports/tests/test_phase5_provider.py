import base64
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from catalog_imports.media_providers.openai_images import OpenAIImageProvider


class Phase5OpenAIProviderTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    @patch("catalog_imports.media_providers.openai_images.fetch_binary")
    @patch("requests.post")
    def test_provider_uses_reference_edit_endpoint_and_returns_image(self, post, fetch_binary):
        from PIL import Image
        import io
        ref = io.BytesIO()
        Image.new("RGB", (200, 200), "white").save(ref, format="PNG")
        fetch_binary.return_value = Mock(data=ref.getvalue())

        generated = io.BytesIO()
        Image.new("RGB", (256, 256), "white").save(generated, format="WEBP")
        response = Mock(status_code=200, headers={"x-request-id": "req_123"})
        response.json.return_value = {"data": [{"b64_json": base64.b64encode(generated.getvalue()).decode()}]}
        post.return_value = response

        result = OpenAIImageProvider().generate(
            prompt="exact product",
            reference_urls=["https://example.com/ref.png"],
        )
        self.assertEqual(result.provider_asset_id, "req_123")
        self.assertEqual(result.mime_type, "image/webp")
        self.assertGreater(len(result.content), 10)
        kwargs = post.call_args.kwargs
        self.assertIn("files", kwargs)
        self.assertEqual(kwargs["data"]["model"], "gpt-image-2")
