from pathlib import PurePosixPath
from urllib.parse import urlparse

from django.db import migrations


SUPPORTED_VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "vimeo.com",
    "www.vimeo.com",
    "player.vimeo.com",
}


def repair_legacy_project_videos(apps, schema_editor):
    ServicePortfolio = apps.get_model("installers", "ServicePortfolio")
    ServiceProjectMedia = apps.get_model("installers", "ServiceProjectMedia")

    for project in ServicePortfolio.objects.all().iterator():
        approval_status = (
            "approved" if project.approval_status == "approved" else "pending"
        )
        local_video_name = str(getattr(project.local_video, "name", "") or "")
        if local_video_name and not ServiceProjectMedia.objects.filter(
            project_id=project.pk,
            media_type="video",
            video=local_video_name,
        ).exists():
            suffix = PurePosixPath(local_video_name).suffix.lower()
            ServiceProjectMedia.objects.create(
                project_id=project.pk,
                media_type="video",
                stage="walkthrough",
                video=local_video_name,
                thumbnail=str(getattr(project.video_thumbnail, "name", "") or ""),
                caption=project.title,
                alt_text=project.title,
                is_active=bool(project.is_active),
                approval_status=approval_status,
                uploaded_by_id=project.created_by_id,
                video_duration=project.video_duration or 0,
                original_filename=PurePosixPath(local_video_name).name,
                processing_status="none" if suffix in {".mp4", ".webm"} else "pending",
            )

        external_url = str(getattr(project, "video_url", "") or "").strip()
        external_host = urlparse(external_url).netloc.lower().split(":", 1)[0]
        if (
            external_url
            and external_host in SUPPORTED_VIDEO_HOSTS
            and not ServiceProjectMedia.objects.filter(
                project_id=project.pk,
                media_type="video",
                external_video_url=external_url,
            ).exists()
        ):
            ServiceProjectMedia.objects.create(
                project_id=project.pk,
                media_type="video",
                stage="walkthrough",
                external_video_url=external_url,
                thumbnail=str(getattr(project.video_thumbnail, "name", "") or ""),
                caption=project.title,
                alt_text=project.title,
                is_active=bool(project.is_active),
                approval_status=approval_status,
                uploaded_by_id=project.created_by_id,
                video_duration=project.video_duration or 0,
                processing_status="none",
            )


class Migration(migrations.Migration):
    dependencies = [
        ("installers", "0013_normalize_legacy_project_media"),
    ]

    operations = [
        migrations.RunPython(
            repair_legacy_project_videos,
            migrations.RunPython.noop,
        ),
    ]
