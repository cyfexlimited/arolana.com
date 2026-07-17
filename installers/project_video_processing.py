from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    ServicePortfolio,
    ServiceProjectMedia,
    project_external_video_embed_url,
)


logger = logging.getLogger("arolana.project_video_processing")


class ProjectVideoProcessingError(Exception):
    """Raised when a project video cannot be prepared for web/mobile playback."""


def ensure_legacy_project_video_media() -> int:
    """Import legacy portfolio videos that were added after the data migration."""
    project_ids = list(
        ServicePortfolio.objects.filter(
            Q(local_video__isnull=False) & ~Q(local_video="")
            | Q(video_url__isnull=False) & ~Q(video_url="")
        ).values_list("id", flat=True)
    )
    created_count = 0
    for project_id in project_ids:
        with transaction.atomic():
            project = ServicePortfolio.objects.select_for_update().get(pk=project_id)
            approval_status = (
                ServiceProjectMedia.STATUS_APPROVED
                if project.approval_status == ServicePortfolio.STATUS_APPROVED
                else ServiceProjectMedia.STATUS_PENDING
            )
            local_name = str(getattr(project.local_video, "name", "") or "")
            if local_name and not ServiceProjectMedia.objects.filter(
                project_id=project.pk,
                media_type=ServiceProjectMedia.TYPE_VIDEO,
                video=local_name,
            ).exists():
                ServiceProjectMedia.objects.create(
                    project=project,
                    media_type=ServiceProjectMedia.TYPE_VIDEO,
                    stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
                    video=local_name,
                    thumbnail=str(getattr(project.video_thumbnail, "name", "") or ""),
                    caption=project.title,
                    alt_text=project.title,
                    is_active=project.is_active,
                    approval_status=approval_status,
                    uploaded_by_id=project.created_by_id,
                    video_duration=project.video_duration or 0,
                    original_filename=Path(local_name).name,
                )
                created_count += 1

            external_url = str(project.video_url or "").strip()
            if (
                external_url
                and project_external_video_embed_url(external_url)
                and not ServiceProjectMedia.objects.filter(
                    project_id=project.pk,
                    media_type=ServiceProjectMedia.TYPE_VIDEO,
                    external_video_url=external_url,
                ).exists()
            ):
                ServiceProjectMedia.objects.create(
                    project=project,
                    media_type=ServiceProjectMedia.TYPE_VIDEO,
                    stage=ServiceProjectMedia.STAGE_WALKTHROUGH,
                    external_video_url=external_url,
                    thumbnail=str(getattr(project.video_thumbnail, "name", "") or ""),
                    caption=project.title,
                    alt_text=project.title,
                    is_active=project.is_active,
                    approval_status=approval_status,
                    uploaded_by_id=project.created_by_id,
                    video_duration=project.video_duration or 0,
                )
                created_count += 1
    return created_count


def _binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ProjectVideoProcessingError(
            f"{name} is not installed or is not available on PATH."
        )
    return path


def _copy_from_storage(storage_name: str, destination: Path) -> None:
    with default_storage.open(storage_name, "rb") as source:
        with destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)


def _duration_seconds(ffprobe: str, source: Path) -> int:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(source),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    try:
        seconds = float(json.loads(completed.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return 0
    return max(int(round(seconds)), 0)


def _run(command: list[str], timeout: int) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        error = (
            completed.stderr
            or completed.stdout
            or "FFmpeg processing failed."
        ).strip()
        raise ProjectVideoProcessingError(error[-4000:])


def process_project_video(
    media_id: int,
    *,
    force: bool = False,
    retry_failed: bool = False,
) -> bool:
    """Create a streaming MP4 and poster while retaining the protected original."""
    media = ServiceProjectMedia.objects.filter(
        pk=media_id,
        media_type=ServiceProjectMedia.TYPE_VIDEO,
    ).first()
    if not media:
        logger.warning("Project video media %s does not exist.", media_id)
        return False

    source_name = str(getattr(media.video, "name", "") or "").strip()
    if not source_name or media.external_video_url:
        ServiceProjectMedia.objects.filter(pk=media_id).update(
            processing_status=ServiceProjectMedia.PROCESSING_NONE,
            processing_error="",
        )
        return False

    source_suffix = Path(source_name).suffix.lower()
    if source_suffix in {".mp4", ".webm"} and not force:
        ServiceProjectMedia.objects.filter(pk=media_id).update(
            processing_status=ServiceProjectMedia.PROCESSING_NONE,
            processing_error="",
        )
        return True

    claimable_statuses = [ServiceProjectMedia.PROCESSING_PENDING]
    if retry_failed:
        claimable_statuses.append(ServiceProjectMedia.PROCESSING_FAILED)
    if force:
        claimable_statuses.extend(
            [
                ServiceProjectMedia.PROCESSING_NONE,
                ServiceProjectMedia.PROCESSING_COMPLETED,
            ]
        )
    claimed = ServiceProjectMedia.objects.filter(
        pk=media_id,
        processing_status__in=set(claimable_statuses),
    ).update(
        processing_status=ServiceProjectMedia.PROCESSING_ACTIVE,
        processing_error="",
        updated_at=timezone.now(),
    )
    if not claimed:
        logger.info(
            "Project video media_id=%s was already claimed or is not eligible.",
            media_id,
        )
        return False
    media.refresh_from_db()

    old_processed = str(
        getattr(media.processed_video, "name", "") or ""
    ).strip()
    old_thumbnail = str(getattr(media.thumbnail, "name", "") or "").strip()

    try:
        ffmpeg = _binary("ffmpeg")
        ffprobe = _binary("ffprobe")
        with tempfile.TemporaryDirectory(
            prefix=f"arolana-project-video-{media_id}-"
        ) as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / f"input{source_suffix or '.video'}"
            output_path = root / "project-video.mp4"
            poster_path = root / "project-video-poster.jpg"
            _copy_from_storage(source_name, input_path)

            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(input_path),
                    "-map_metadata",
                    "-1",
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "22",
                    "-profile:v",
                    "high",
                    "-level",
                    "4.1",
                    "-pix_fmt",
                    "yuv420p",
                    "-vf",
                    (
                        "scale=w='min(1920,iw)':h='min(1080,ih)':"
                        "force_original_aspect_ratio=decrease:force_divisible_by=2"
                    ),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-ac",
                    "2",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                timeout=30 * 60,
            )
            if not output_path.exists() or output_path.stat().st_size <= 0:
                raise ProjectVideoProcessingError(
                    "FFmpeg did not produce a valid project video."
                )

            try:
                _run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(output_path),
                        "-map_metadata",
                        "-1",
                        "-vf",
                        "thumbnail,scale='min(1280,iw)':-2",
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        str(poster_path),
                    ],
                    timeout=5 * 60,
                )
            except ProjectVideoProcessingError:
                # A poster is useful, but a poster failure must not discard a
                # valid streaming MP4. The UI has a branded video fallback.
                logger.warning(
                    "Project video poster generation failed media_id=%s",
                    media_id,
                    exc_info=True,
                )

            duration = _duration_seconds(ffprobe, output_path)
            with transaction.atomic():
                locked = ServiceProjectMedia.objects.select_for_update().get(
                    pk=media_id
                )
                with output_path.open("rb") as converted:
                    locked.processed_video.save(
                        f"project-{media_id}.mp4",
                        File(converted),
                        save=False,
                    )
                if poster_path.exists() and poster_path.stat().st_size > 0:
                    with poster_path.open("rb") as poster:
                        locked.thumbnail.save(
                            f"project-{media_id}-poster.jpg",
                            File(poster),
                            save=False,
                        )
                locked.video_duration = duration
                locked.processing_status = ServiceProjectMedia.PROCESSING_COMPLETED
                locked.processing_error = ""
                locked.save(
                    update_fields=[
                        "processed_video",
                        "thumbnail",
                        "video_duration",
                        "processing_status",
                        "processing_error",
                        "updated_at",
                    ]
                )
                new_processed = str(locked.processed_video.name or "")
                new_thumbnail = str(locked.thumbnail.name or "")

            for previous, current in (
                (old_processed, new_processed),
                (old_thumbnail, new_thumbnail),
            ):
                if previous and previous != current and default_storage.exists(previous):
                    default_storage.delete(previous)

        logger.info("Processed project video media_id=%s", media_id)
        return True
    except Exception as exc:
        ServiceProjectMedia.objects.filter(pk=media_id).update(
            processing_status=ServiceProjectMedia.PROCESSING_FAILED,
            processing_error=str(exc)[-4000:],
            updated_at=timezone.now(),
        )
        logger.exception("Project video processing failed media_id=%s", media_id)
        return False
