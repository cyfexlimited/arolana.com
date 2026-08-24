"""Arolana-only source deletion while preserving external publication audits."""

from django.contrib.contenttypes.models import ContentType
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from .models import PublicationStatus, SocialPublication


TERMINAL_PUBLICATION_STATUSES = frozenset(
    {
        PublicationStatus.PUBLISHED,
        PublicationStatus.FAILED,
        PublicationStatus.CANCELLED,
    }
)

ACTIVE_PUBLICATION_STATUSES = frozenset(
    {
        PublicationStatus.PENDING,
        PublicationStatus.QUEUED,
        PublicationStatus.UPLOADING,
        PublicationStatus.PROCESSING,
        PublicationStatus.RETRYING,
    }
)


class ActiveSocialPublicationError(ProtectedError):
    """Deletion was refused because external publication is not terminal."""


def publications_for_objects(model, object_ids):
    ids = tuple({int(value) for value in object_ids if value})
    if not ids:
        return SocialPublication.objects.none()
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    return SocialPublication.objects.filter(content_type=content_type, object_id__in=ids)


def active_publications(publications):
    # Unknown future states fail closed until explicitly classified terminal.
    return publications.exclude(status__in=TERMINAL_PUBLICATION_STATUSES)


def archive_terminal_publications(publications):
    now = timezone.now()
    archived = []
    for publication in publications.filter(status__in=TERMINAL_PUBLICATION_STATUSES):
        model_class = publication.content_type.model_class()
        model_name = model_class.__name__ if model_class else publication.content_type.model
        publication.archived_at = publication.archived_at or now
        publication.original_content_type_label = (
            publication.original_content_type_label
            or f"{publication.content_type.app_label}.{model_name}"
        )
        publication.original_object_id = publication.original_object_id or publication.object_id
        publication.archive_metadata = {
            **(publication.archive_metadata or {}),
            "reason": "source_deleted_from_arolana",
        }
        publication.save(
            update_fields=[
                "archived_at",
                "original_content_type_label",
                "original_object_id",
                "archive_metadata",
                "updated_at",
            ]
        )
        archived.append(publication)
    return archived


def prepare_publications_for_source_deletion(model, object_ids):
    publications = publications_for_objects(model, object_ids)
    blocking = active_publications(publications)
    if blocking.exists():
        statuses = sorted(set(blocking.values_list("status", flat=True)))
        message = (
            "Deletion is blocked while social publication is active "
            f"({', '.join(statuses)}). Complete or cancel it safely first."
        )
        raise ActiveSocialPublicationError(message, set(blocking))
    return archive_terminal_publications(publications)
