from pathlib import PurePosixPath

from django.db import migrations


LEGACY_STAGE_MAP = {
    'before_image': 'before',
    'during_image': 'progress',
    'progress_image': 'progress',
    'after_image': 'after',
}


def _approval_status(project):
    status = getattr(project, 'approval_status', '')
    if status == 'approved':
        return 'approved'
    if status == 'rejected':
        return 'rejected'
    return 'pending'


def normalize_and_import_legacy_media(apps, schema_editor):
    ServicePortfolio = apps.get_model('installers', 'ServicePortfolio')
    ServiceProjectMedia = apps.get_model('installers', 'ServiceProjectMedia')

    for legacy_type, stage in LEGACY_STAGE_MAP.items():
        ServiceProjectMedia.objects.filter(media_type=legacy_type).update(
            media_type='image',
            stage=stage,
        )

    ServiceProjectMedia.objects.filter(media_type='document', stage='general').update(
        stage='supporting_document'
    )

    for project in ServicePortfolio.objects.all().iterator():
        status = _approval_status(project)
        image_name = str(getattr(project.image, 'name', '') or '')
        if image_name and not ServiceProjectMedia.objects.filter(
            project_id=project.pk,
            image=image_name,
        ).exists():
            ServiceProjectMedia.objects.create(
                project_id=project.pk,
                media_type='image',
                stage='general',
                image=image_name,
                caption=project.title,
                alt_text=project.title,
                is_active=bool(project.is_active),
                is_featured=True,
                approval_status=status,
                uploaded_by_id=project.created_by_id,
                original_filename=PurePosixPath(image_name).name,
            )

        local_video_name = str(getattr(project.local_video, 'name', '') or '')
        if local_video_name and not ServiceProjectMedia.objects.filter(
            project_id=project.pk,
            video=local_video_name,
        ).exists():
            suffix = PurePosixPath(local_video_name).suffix.lower()
            ServiceProjectMedia.objects.create(
                project_id=project.pk,
                media_type='video',
                stage='walkthrough',
                video=local_video_name,
                thumbnail=str(getattr(project.video_thumbnail, 'name', '') or ''),
                caption=project.title,
                is_active=bool(project.is_active),
                approval_status=status,
                uploaded_by_id=project.created_by_id,
                video_duration=project.video_duration or 0,
                original_filename=PurePosixPath(local_video_name).name,
                processing_status='none' if suffix in {'.mp4', '.webm'} else 'pending',
            )

        external_video_url = str(getattr(project, 'video_url', '') or '').strip()
        if external_video_url and not ServiceProjectMedia.objects.filter(
            project_id=project.pk,
            external_video_url=external_video_url,
        ).exists():
            ServiceProjectMedia.objects.create(
                project_id=project.pk,
                media_type='video',
                stage='walkthrough',
                external_video_url=external_video_url,
                thumbnail=str(getattr(project.video_thumbnail, 'name', '') or ''),
                caption=project.title,
                is_active=bool(project.is_active),
                approval_status=status,
                uploaded_by_id=project.created_by_id,
                video_duration=project.video_duration or 0,
                processing_status='none',
            )

        if not ServiceProjectMedia.objects.filter(
            project_id=project.pk,
            is_cover=True,
        ).exists():
            cover = ServiceProjectMedia.objects.filter(
                project_id=project.pk,
                media_type='image',
                is_active=True,
                approval_status='approved',
            ).order_by('-is_featured', 'display_order', 'id').first()
            if cover is None:
                cover = ServiceProjectMedia.objects.filter(
                    project_id=project.pk,
                    media_type='image',
                    is_active=True,
                ).order_by('-is_featured', 'display_order', 'id').first()
            if cover is not None:
                ServiceProjectMedia.objects.filter(pk=cover.pk).update(
                    is_cover=True,
                    is_featured=True,
                )


def restore_legacy_media_types(apps, schema_editor):
    ServiceProjectMedia = apps.get_model('installers', 'ServiceProjectMedia')
    reverse_map = {
        'before': 'before_image',
        'progress': 'progress_image',
        'after': 'after_image',
    }
    for stage, legacy_type in reverse_map.items():
        ServiceProjectMedia.objects.filter(
            media_type='image',
            stage=stage,
        ).update(media_type=legacy_type)


class Migration(migrations.Migration):

    dependencies = [
        ('installers', '0012_remove_serviceprojectmedia_installers__media_t_b536fd_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(
            normalize_and_import_legacy_media,
            restore_legacy_media_types,
        ),
    ]
