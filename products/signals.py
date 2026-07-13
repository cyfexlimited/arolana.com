"""Signals that keep Product rating cache fields synchronized."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import ProductReview
from .review_stats import refresh_product_review_stats


def _schedule_refresh(*product_ids):
    ids = tuple(
        sorted(
            {
                int(product_id)
                for product_id in product_ids
                if product_id
            }
        )
    )

    if not ids:
        return

    def refresh_after_commit():
        for product_id in ids:
            refresh_product_review_stats(product_id)

    transaction.on_commit(refresh_after_commit)


@receiver(
    pre_save,
    sender=ProductReview,
    dispatch_uid="products.product_review.remember_previous_product",
)
def remember_previous_product(sender, instance, **kwargs):
    """Remember the old product when admin moves a review to another product."""

    instance._previous_product_id = None

    if not instance.pk:
        return

    instance._previous_product_id = (
        sender.objects
        .filter(pk=instance.pk)
        .values_list("product_id", flat=True)
        .first()
    )


@receiver(
    post_save,
    sender=ProductReview,
    dispatch_uid="products.product_review.refresh_after_save",
)
def refresh_after_review_save(sender, instance, **kwargs):
    _schedule_refresh(
        getattr(instance, "_previous_product_id", None),
        instance.product_id,
    )


@receiver(
    post_delete,
    sender=ProductReview,
    dispatch_uid="products.product_review.refresh_after_delete",
)
def refresh_after_review_delete(sender, instance, **kwargs):
    _schedule_refresh(instance.product_id)
