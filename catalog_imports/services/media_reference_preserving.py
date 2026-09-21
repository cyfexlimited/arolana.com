import hashlib
import io
from dataclasses import dataclass, field
from urllib.parse import urldefrag

from catalog_imports.models import ImportMediaCandidate

from .http_fetch import FetchBlocked, UnsafeURL, fetch_binary


class ReferencePreservingError(RuntimeError):
    pass


@dataclass
class ReferencePreservingResult:
    content: bytes
    mime_type: str = "image/png"
    provider_asset_id: str = ""
    metadata: dict = field(default_factory=dict)


_REFERENCE_PRESERVING_VIEWS = {
    ImportMediaCandidate.VIEW_LEFT,
    ImportMediaCandidate.VIEW_RIGHT,
    ImportMediaCandidate.VIEW_SIDE,
    ImportMediaCandidate.VIEW_BACK,
    ImportMediaCandidate.VIEW_TOP,
    ImportMediaCandidate.VIEW_PORTS,
    ImportMediaCandidate.VIEW_PACKAGE,
    ImportMediaCandidate.VIEW_CLOSEUP,
}


def is_reference_preserving_view(view_role):
    return view_role in _REFERENCE_PRESERVING_VIEWS


def _parse_square_size(size):
    value = str(size or "1024x1024").lower().strip()
    try:
        width, height = value.split("x", 1)
        width = int(width)
        height = int(height)
    except Exception:
        return 1024

    # Technical review assets are deliberately square and bounded.
    side = min(width, height)
    return max(512, min(side, 1536))


def _fetch_reference(url):
    # Arolana audit annotations live in URL fragments and are not HTTP request
    # data. Strip them explicitly to make provenance vs network URL clear.
    fetch_url, _fragment = urldefrag(str(url or "").strip())
    if not fetch_url:
        raise ReferencePreservingError("Verified technical reference URL is empty.")

    try:
        result = fetch_binary(
            fetch_url,
            timeout=20,
            max_bytes=15 * 1024 * 1024,
            allowed_content_types={
                "image/png",
                "image/x-png",
                "image/jpeg",
                "image/jpg",
                "image/webp",
                "image/gif",
                "image/avif",
                "application/octet-stream",
            },
            user_agent="ArolanaProductImporter/5.0.13 (+https://arolana.com)",
            accept_header=(
                "image/png,image/jpeg,image/webp,image/gif,image/avif;"
                "q=0.9,application/octet-stream;q=0.5,*/*;q=0.1"
            ),
        )
    except (FetchBlocked, UnsafeURL) as exc:
        raise ReferencePreservingError(
            f"Could not fetch verified technical reference: {exc}"
        ) from exc

    return result


def _decode_reference(raw):
    try:
        from PIL import Image, ImageOps

        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)

        if getattr(image, "is_animated", False):
            image.seek(0)

        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")

        # Preserve every visible source pixel. Transparency is composited on
        # white; no inpainting, masking, retouching, object removal, or redraw.
        if image.mode == "RGBA":
            white = Image.new("RGBA", image.size, "white")
            white.alpha_composite(image)
            image = white.convert("RGB")
        else:
            image = image.convert("RGB")

        return image
    except Exception as exc:
        raise ReferencePreservingError(
            "Verified technical reference could not be decoded as an image."
        ) from exc


def _fit_exact_pixels(image, box_width, box_height):
    """Scale proportionally only; never crop or warp the source."""
    from PIL import Image

    width, height = image.size
    if width <= 0 or height <= 0:
        raise ReferencePreservingError("Verified technical reference has invalid dimensions.")

    scale = min(box_width / width, box_height / height)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))

    if (target_width, target_height) == image.size:
        return image.copy()

    return image.resize(
        (target_width, target_height),
        resample=Image.Resampling.LANCZOS,
    )


def _layout_boxes(count, side, margin, gap):
    usable = side - (margin * 2)

    if count <= 1:
        return [(margin, margin, usable, usable)]

    if count == 2:
        box_width = (usable - gap) // 2
        return [
            (margin, margin, box_width, usable),
            (margin + box_width + gap, margin, box_width, usable),
        ]

    # Three references: two on top, one full-width below.
    top_height = (usable - gap) // 2
    top_width = (usable - gap) // 2
    return [
        (margin, margin, top_width, top_height),
        (margin + top_width + gap, margin, top_width, top_height),
        (margin, margin + top_height + gap, usable, top_height),
    ]


def render_reference_preserving_asset(*, reference_urls, view_role, size="1024x1024"):
    if not is_reference_preserving_view(view_role):
        raise ReferencePreservingError(
            "Reference-preserving renderer is limited to geometry-sensitive technical views."
        )

    refs = [
        str(value).strip()
        for value in (reference_urls or [])
        if str(value).strip()
    ]

    # A technical sheet should stay legible. The view gate/ranker has already
    # ordered the strongest references first.
    refs = refs[:3]
    if not refs:
        raise ReferencePreservingError(
            "Reference-preserving technical view requires at least one verified reference."
        )

    side = _parse_square_size(size)

    try:
        from PIL import Image
    except Exception as exc:
        raise ReferencePreservingError(
            "Pillow is required for reference-preserving technical media."
        ) from exc

    margin = max(24, side // 28)
    gap = max(18, side // 40)
    canvas = Image.new("RGB", (side, side), "white")
    boxes = _layout_boxes(len(refs), side, margin, gap)

    provenance = []

    for index, (url, box) in enumerate(zip(refs, boxes), 1):
        fetched = _fetch_reference(url)
        raw = bytes(fetched.data or b"")
        if not raw:
            raise ReferencePreservingError(
                "Verified technical reference returned an empty image."
            )

        image = _decode_reference(raw)
        original_width, original_height = image.size

        x, y, box_width, box_height = box
        fitted = _fit_exact_pixels(image, box_width, box_height)
        paste_x = x + (box_width - fitted.width) // 2
        paste_y = y + (box_height - fitted.height) // 2

        # This is a literal pixel-preserving placement. No mask or generative
        # model touches the product, labels, ports, buttons or accessories.
        canvas.paste(fitted, (paste_x, paste_y))

        provenance.append({
            "index": index,
            "audit_url": url,
            "network_url": str(getattr(fetched, "url", "") or urldefrag(url)[0]),
            "content_type": str(getattr(fetched, "content_type", "") or ""),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "source_bytes": len(raw),
            "source_width": original_width,
            "source_height": original_height,
            "placed_width": fitted.width,
            "placed_height": fitted.height,
            "cropped": False,
            "warped": False,
            "inpainted": False,
            "ai_redraw": False,
        })

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    payload = out.getvalue()
    digest = hashlib.sha256(payload).hexdigest()

    return ReferencePreservingResult(
        content=payload,
        mime_type="image/png",
        provider_asset_id=f"local-{digest[:32]}",
        metadata={
            "render_mode": "reference_preserving",
            "renderer": "arolana-local-reference-layout-v1",
            "ai_redraw": False,
            "cropping": False,
            "warping": False,
            "background": "white",
            "reference_count": len(provenance),
            "references": provenance,
            "output_width": side,
            "output_height": side,
            "output_sha256": digest,
            "rights_inherited_from_reference": True,
            "rights_note": (
                "This technical review asset is a deterministic presentation of "
                "official reference pixels. Rights are not assumed; the existing "
                "human rights review remains mandatory before Product attachment."
            ),
        },
    )
