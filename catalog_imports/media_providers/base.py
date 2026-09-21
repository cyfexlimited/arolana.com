from dataclasses import dataclass, field
from typing import Optional


class MediaProviderError(RuntimeError):
    pass


class MediaProviderConfigurationError(MediaProviderError):
    pass


@dataclass
class GenerationResult:
    content: bytes
    mime_type: str
    provider_asset_id: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    metadata: dict = field(default_factory=dict)


class MediaGenerationProvider:
    key = ""

    def generate(self, *, prompt, reference_urls, size="1024x1024", quality="medium"):
        raise NotImplementedError
