"""Deletion hooks for publication-bearing Vendor and Provider content."""

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from installers.models import ServicePortfolio, ServiceProjectMedia
from products.models import Product, ProductVideo

from .deletion import prepare_publications_for_source_deletion


@receiver(pre_delete, sender=ProductVideo)
def archive_product_video_publications(sender, instance, **kwargs):
    prepare_publications_for_source_deletion(ProductVideo, [instance.pk])


@receiver(pre_delete, sender=Product)
def archive_product_and_child_video_publications(sender, instance, **kwargs):
    prepare_publications_for_source_deletion(Product, [instance.pk])
    video_ids = instance.additional_videos.values_list("pk", flat=True)
    prepare_publications_for_source_deletion(ProductVideo, video_ids)


@receiver(pre_delete, sender=ServiceProjectMedia)
def archive_service_project_media_publications(sender, instance, **kwargs):
    prepare_publications_for_source_deletion(ServiceProjectMedia, [instance.pk])


@receiver(pre_delete, sender=ServicePortfolio)
def archive_service_project_and_media_publications(sender, instance, **kwargs):
    prepare_publications_for_source_deletion(ServicePortfolio, [instance.pk])
    media_ids = instance.media_items.values_list("pk", flat=True)
    prepare_publications_for_source_deletion(ServiceProjectMedia, media_ids)
