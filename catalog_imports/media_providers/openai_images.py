import base64
import io
import json
import os

from django.conf import settings

from catalog_imports.services.http_fetch import FetchBlocked, UnsafeURL, fetch_binary

from .base import GenerationResult, MediaProviderConfigurationError, MediaProviderError, MediaGenerationProvider


class OpenAIImageProvider(MediaGenerationProvider):
    key = "openai"

    def _config(self, name, default=""):
        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
        try:
            from decouple import config
            return config(name, default=default)
        except Exception:
            return default

    def _api_key(self):
        value = str(self._config("OPENAI_API_KEY", "") or "").strip()
        if not value:
            raise MediaProviderConfigurationError(
                "OPENAI_API_KEY is not configured. Add it to the local environment/.env and Railway variables before generating media."
            )
        return value

    def _model(self):
        return str(self._config("CATALOG_IMPORT_OPENAI_IMAGE_MODEL", "gpt-image-2") or "gpt-image-2").strip()

    def _convert_reference_to_png(self, url, index):
        try:
            result = fetch_binary(
                url,
                timeout=20,
                max_bytes=12 * 1024 * 1024,
                allowed_content_types={
                    "image/png", "image/x-png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "application/octet-stream",
                },
                user_agent="ArolanaProductImporter/5.0 (+https://arolana.com)",
                accept_header="image/png,image/jpeg,image/webp,image/gif;q=0.9,*/*;q=0.1",
            )
        except (FetchBlocked, UnsafeURL) as exc:
            raise MediaProviderError(f"Could not fetch official reference image: {exc}") from exc

        try:
            from PIL import Image, ImageOps
            image = Image.open(io.BytesIO(result.data))
            image = ImageOps.exif_transpose(image)
            if getattr(image, "is_animated", False):
                image.seek(0)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            buf = io.BytesIO()
            image.save(buf, format="PNG", optimize=True)
            return (f"reference-{index}.png", buf.getvalue(), "image/png")
        except Exception as exc:
            raise MediaProviderError("Official reference image could not be decoded as a supported image.") from exc

    def generate(self, *, prompt, reference_urls, size="1024x1024", quality="medium"):
        refs = [str(url).strip() for url in (reference_urls or []) if str(url).strip()]
        max_refs = int(self._config("CATALOG_IMPORT_MEDIA_MAX_REFERENCES", 3) or 3)
        refs = refs[: max(1, min(max_refs, 5))] if refs else []

        try:
            import requests
        except ImportError as exc:
            raise MediaProviderConfigurationError(
                "The requests package is required for the configured image provider."
            ) from exc

        model = self._model()
        output_format = str(
            self._config("CATALOG_IMPORT_MEDIA_OUTPUT_FORMAT", "webp") or "webp"
        ).strip().lower()
        if output_format not in {"png", "jpeg", "webp"}:
            output_format = "webp"

        compression = int(
            self._config("CATALOG_IMPORT_MEDIA_OUTPUT_COMPRESSION", 90) or 90
        )
        timeout = int(
            self._config("CATALOG_IMPORT_MEDIA_PROVIDER_TIMEOUT", 180) or 180
        )

        # Reference-grounded generation: preserve the existing Images Edits path.
        if refs:
            files = []
            for index, url in enumerate(refs, 1):
                filename, payload, mime = self._convert_reference_to_png(url, index)
                files.append(("image[]", (filename, payload, mime)))

            endpoint = str(
                self._config(
                    "CATALOG_IMPORT_OPENAI_IMAGE_ENDPOINT",
                    "https://api.openai.com/v1/images/edits",
                )
                or "https://api.openai.com/v1/images/edits"
            ).strip()

            data = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "output_format": output_format,
                "n": "1",
            }
            if output_format in {"jpeg", "webp"}:
                data["output_compression"] = str(max(0, min(compression, 100)))

            try:
                response = requests.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self._api_key()}"},
                    data=data,
                    files=files,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise MediaProviderError(f"Image provider request failed: {exc}") from exc

            request_mode = "edit_with_references"

        # Text-grounded creative generation:
        # This endpoint is used only when higher-level importer policy explicitly
        # permits an intentional creative slot with no pixel reference.
        else:
            endpoint = str(
                self._config(
                    "CATALOG_IMPORT_OPENAI_IMAGE_GENERATION_ENDPOINT",
                    "https://api.openai.com/v1/images/generations",
                )
                or "https://api.openai.com/v1/images/generations"
            ).strip()

            data = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "output_format": output_format,
                "n": 1,
            }
            if output_format in {"jpeg", "webp"}:
                data["output_compression"] = max(0, min(compression, 100))

            try:
                response = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "Content-Type": "application/json",
                    },
                    json=data,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                raise MediaProviderError(f"Image provider request failed: {exc}") from exc

            request_mode = "generation_text_only"

        request_id = str(response.headers.get("x-request-id") or "").strip()
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                code = str(error.get("code") or error.get("type") or "provider_error")
                message = str(error.get("message") or "Image provider rejected the request.")
            else:
                code = "provider_error"
                message = "Image provider rejected the request."
            raise MediaProviderError(
                f"Image provider returned HTTP {response.status_code} ({code}): {message}"
            )

        try:
            encoded = payload["data"][0]["b64_json"]
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise MediaProviderError(
                "Image provider returned no usable base64 image payload."
            ) from exc

        mime = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }[output_format]

        return GenerationResult(
            content=raw,
            mime_type=mime,
            provider_asset_id=request_id,
            metadata={
                "request_id": request_id,
                "model": model,
                "endpoint": endpoint,
                "request_mode": request_mode,
                "reference_count": len(refs),
                "size": size,
                "quality": quality,
                "output_format": output_format,
            },
        )
