from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import VendorSubscription
from .services import sync_vendor_subscription_profile


@receiver(post_save, sender=VendorSubscription)
def sync_vendor_profile_after_subscription_save(sender, instance, **kwargs):
    sync_vendor_subscription_profile(instance.vendor)


@receiver(post_delete, sender=VendorSubscription)
def sync_vendor_profile_after_subscription_delete(sender, instance, **kwargs):
    sync_vendor_subscription_profile(instance.vendor)
