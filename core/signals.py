import logging

from django.apps import apps
from django.db import models, transaction
from django.db.models.signals import post_save

from core.media_optimization import auto_optimize_instance_images

try:
    from core.background_tasks import submit_background
except Exception:
    submit_background = None

logger = logging.getLogger(__name__)


def _generate_model_media(model_label, object_id):
    model = apps.get_model(model_label)
    obj = model.objects.filter(pk=object_id).first()

    if not obj:
        return

    auto_optimize_instance_images(obj)


def optimize_instance_images_after_save(sender, instance, raw=False, **kwargs):
    if raw:
        return

    model_label = instance._meta.label
    object_id = instance.pk

    def run_after_commit():
        try:
            if submit_background:
                submit_background(_generate_model_media, model_label, object_id)
            else:
                _generate_model_media(model_label, object_id)
        except Exception:
            logger.exception(
                "Arolana auto image optimization failed for %s pk=%s",
                model_label,
                object_id,
            )

    transaction.on_commit(run_after_commit)


def connect_image_optimization_signals():
    for model in apps.get_models():
        image_fields = [
            field for field in model._meta.fields
            if isinstance(field, models.ImageField)
        ]

        if not image_fields:
            continue

        post_save.connect(
            optimize_instance_images_after_save,
            sender=model,
            weak=False,
            dispatch_uid=f"arolana_auto_optimize_images_{model._meta.label_lower}",
        )


connect_image_optimization_signals()