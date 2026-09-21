import base64
from unittest.mock import patch

from django.test import SimpleTestCase

from catalog_imports.media_providers.openai_images import OpenAIImageProvider


class _Response:
    status_code = 200
    headers = {"x-request-id": "req_text_only_1"}

    def json(self):
        return {
            "data": [
                {
                    "b64_json": base64.b64encode(b"fake-image-bytes").decode("ascii")
                }
            ]
        }


class Phase523OpenAITextOnlyImageProviderTests(SimpleTestCase):
    @patch("requests.post")
    def test_no_reference_uses_images_generations_endpoint(self, post):
        post.return_value = _Response()
        provider = OpenAIImageProvider()

        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "CATALOG_IMPORT_OPENAI_IMAGE_MODEL": "gpt-image-2",
            },
            clear=False,
        ):
            result = provider.generate(
                prompt="Creative support image",
                reference_urls=[],
                size="1024x1024",
                quality="medium",
            )

        self.assertEqual(result.content, b"fake-image-bytes")
        self.assertEqual(result.metadata["request_mode"], "generation_text_only")
        self.assertEqual(result.metadata["reference_count"], 0)
        self.assertIn("/v1/images/generations", post.call_args.args[0])
        self.assertIn("json", post.call_args.kwargs)

    @patch("requests.post")
    @patch.object(OpenAIImageProvider, "_convert_reference_to_png")
    def test_reference_input_still_uses_edit_endpoint(self, convert_ref, post):
        convert_ref.return_value = ("reference-1.png", b"png", "image/png")
        post.return_value = _Response()
        provider = OpenAIImageProvider()

        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "test-key",
                "CATALOG_IMPORT_OPENAI_IMAGE_MODEL": "gpt-image-2",
            },
            clear=False,
        ):
            result = provider.generate(
                prompt="Edit from reference",
                reference_urls=["https://manufacturer.example/exact.png"],
                size="1024x1024",
                quality="medium",
            )

        self.assertEqual(result.metadata["request_mode"], "edit_with_references")
        self.assertEqual(result.metadata["reference_count"], 1)
        self.assertIn("/v1/images/edits", post.call_args.args[0])
        self.assertIn("files", post.call_args.kwargs)
