from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from products.models import ProductReview


logger = logging.getLogger(
    "arolana.review_video_conversion"
)


class ReviewVideoConversionError(Exception):
    """Raised when a review video cannot be converted."""


def _find_ffmpeg() -> str:
    ffmpeg_path = shutil.which("ffmpeg")

    if not ffmpeg_path:
        raise ReviewVideoConversionError(
            "FFmpeg is not installed or is not available on PATH."
        )

    return ffmpeg_path


def _copy_storage_file_to_local(
    storage_name: str,
    local_path: Path,
) -> None:
    with default_storage.open(
        storage_name,
        "rb",
    ) as source:
        with local_path.open("wb") as destination:
            shutil.copyfileobj(
                source,
                destination,
                length=1024 * 1024,
            )


def _converted_storage_name(
    review: ProductReview,
) -> str:
    return (
        "reviews/videos/converted/"
        f"{timezone.now():%Y/%m}/"
        f"review-{review.pk}.mp4"
    )


def convert_review_video(
    review_id: int,
) -> bool:
    """
    Convert one ProductReview video into browser-compatible MP4.

    Output:
    - MP4 container
    - H.264 video
    - AAC audio
    - yuv420p pixel format
    - fast-start metadata
    """
    review = (
        ProductReview.objects
        .filter(pk=review_id)
        .first()
    )

    if not review:
        logger.warning(
            "Review video conversion skipped: review %s does not exist.",
            review_id,
        )
        return False

    source_name = str(
        getattr(
            review.video_review,
            "name",
            "",
        )
        or ""
    ).strip()

    if not source_name:
        ProductReview.objects.filter(
            pk=review_id
        ).update(
            review_video_conversion_status="none",
            review_video_conversion_error="",
            review_video_converted_at=None,
        )
        return False

    ProductReview.objects.filter(
        pk=review_id
    ).update(
        review_video_conversion_status="processing",
        review_video_conversion_error="",
    )

    ffmpeg_path = _find_ffmpeg()

    try:
        with tempfile.TemporaryDirectory(
            prefix=f"arolana-review-{review_id}-"
        ) as temporary_directory:
            temp_root = Path(
                temporary_directory
            )

            source_extension = (
                Path(source_name).suffix.lower()
                or ".video"
            )

            input_path = temp_root / (
                f"input{source_extension}"
            )

            output_path = temp_root / "output.mp4"

            _copy_storage_file_to_local(
                source_name,
                input_path,
            )

            command = [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),

                # Remove metadata that may contain device/location details.
                "-map_metadata",
                "-1",

                # Use the first video stream and optional first audio stream.
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",

                # Browser-compatible video.
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-profile:v",
                "high",
                "-level",
                "4.1",
                "-pix_fmt",
                "yuv420p",

                # Avoid oversized 4K review videos.
                "-vf",
                (
                    "scale="
                    "'min(1920,iw)':"
                    "'min(1080,ih)':"
                    "force_original_aspect_ratio=decrease"
                ),

                # Browser-compatible audio.
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ac",
                "2",

                # Place MP4 metadata at the beginning for streaming.
                "-movflags",
                "+faststart",

                str(output_path),
            ]

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20 * 60,
                check=False,
            )

            if completed.returncode != 0:
                error_text = (
                    completed.stderr
                    or completed.stdout
                    or "FFmpeg conversion failed."
                ).strip()

                raise ReviewVideoConversionError(
                    error_text[-4000:]
                )

            if (
                not output_path.exists()
                or output_path.stat().st_size <= 0
            ):
                raise ReviewVideoConversionError(
                    "FFmpeg did not produce a valid output file."
                )

            storage_name = _converted_storage_name(
                review
            )

            old_converted_name = str(
                getattr(
                    review.review_video_converted,
                    "name",
                    "",
                )
                or ""
            ).strip()

            if default_storage.exists(
                storage_name
            ):
                default_storage.delete(
                    storage_name
                )

            with output_path.open("rb") as converted_file:
                saved_name = default_storage.save(
                    storage_name,
                    File(
                        converted_file,
                        name=Path(storage_name).name,
                    ),
                )

            with transaction.atomic():
                locked_review = (
                    ProductReview.objects
                    .select_for_update()
                    .get(pk=review_id)
                )

                locked_review.review_video_converted.name = (
                    saved_name
                )
                locked_review.review_video_conversion_status = (
                    "completed"
                )
                locked_review.review_video_conversion_error = ""
                locked_review.review_video_converted_at = (
                    timezone.now()
                )

                locked_review.save(
                    update_fields=[
                        "review_video_converted",
                        "review_video_conversion_status",
                        "review_video_conversion_error",
                        "review_video_converted_at",
                        "updated_at",
                    ]
                )

            if (
                old_converted_name
                and old_converted_name != saved_name
                and default_storage.exists(
                    old_converted_name
                )
            ):
                default_storage.delete(
                    old_converted_name
                )

            logger.info(
                "Converted review video review_id=%s source=%s output=%s",
                review_id,
                source_name,
                saved_name,
            )

            return True

    except Exception as exc:
        error_text = str(
            exc
        )[-4000:]

        ProductReview.objects.filter(
            pk=review_id
        ).update(
            review_video_conversion_status="failed",
            review_video_conversion_error=error_text,
            review_video_converted_at=None,
        )

        logger.exception(
            "Review video conversion failed review_id=%s",
            review_id,
        )

        return False