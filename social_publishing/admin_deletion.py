"""Django Admin deletion guard for non-terminal social publications."""

from django.core.exceptions import PermissionDenied
from django.db.models import Count

from .deletion import active_publications
from .models import SocialPublication


class SocialPublicationDeleteGuardMixin:
    def social_publications_for_delete(self, objs):
        return SocialPublication.objects.none()

    def _publication_delete_warning(self, objs):
        publications = active_publications(self.social_publications_for_delete(objs))
        if not publications.exists():
            return ""
        statuses = ", ".join(
            f"{status}: {count}"
            for status, count in publications.values_list("status")
            .annotate(count=Count("pk"))
            .order_by("status")
        )
        return (
            "Deletion is blocked while related social publications are active "
            f"({statuses}). Complete or safely cancel them before deleting this content."
        )

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        warning = self._publication_delete_warning(objs)
        if warning:
            perms_needed.add(warning)
        return deleted_objects, model_count, perms_needed, protected

    def delete_model(self, request, obj):
        warning = self._publication_delete_warning([obj])
        if warning:
            raise PermissionDenied(warning)
        return super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        warning = self._publication_delete_warning(queryset)
        if warning:
            raise PermissionDenied(warning)
        return super().delete_queryset(request, queryset)
