from dataclasses import dataclass


@dataclass(frozen=True)
class VendorEntitlements:
    max_products: int
    featured_products: int
    max_images_per_product: int
    max_variants_per_product: int
    can_upload_video: bool
    can_upload_pdf: bool
    can_upload_certificates: bool
    can_access_rfq: bool
    plan_label: str

    def unlimited(self, value):
        return value == -1


def get_vendor_entitlements(user):
    from subscriptions.models import subscription_label, user_subscription_limits

    limits = user_subscription_limits(user)
    return VendorEntitlements(
        max_products=limits.get("max_products", 1),
        featured_products=limits.get("featured_products", 0),
        max_images_per_product=limits.get("max_images_per_product", 3),
        max_variants_per_product=limits.get("max_variants_per_product", 0),
        can_upload_video=bool(limits.get("can_upload_video")),
        can_upload_pdf=bool(limits.get("can_upload_pdf")),
        can_upload_certificates=bool(limits.get("can_upload_certificates")),
        can_access_rfq=bool(limits.get("can_access_rfq")),
        plan_label=subscription_label(user),
    )


def vendor_offer_usage(user):
    try:
        vendor_profile = user.vendor_profile
    except Exception:
        return 0
    try:
        from products.models import VendorProductOffer

        return VendorProductOffer.objects.filter(
            vendor=vendor_profile,
            is_active=True,
        ).exclude(approval_status=VendorProductOffer.STATUS_REJECTED).count()
    except Exception:
        return 0


def legacy_product_usage(user):
    from products.models import Product

    return Product.objects.filter(vendor=user).exclude(
        approval_status__in=["rejected", "draft"]
    ).count()


def vendor_listing_usage(user):
    offer_count = vendor_offer_usage(user)
    if offer_count:
        return offer_count
    return legacy_product_usage(user)


def can_create_vendor_offer(user):
    entitlements = get_vendor_entitlements(user)
    used = vendor_listing_usage(user)
    max_products = entitlements.max_products
    allowed = max_products == -1 or used < max_products
    return {
        "allowed": allowed,
        "used": used,
        "limit": max_products,
        "plan_label": entitlements.plan_label,
        "message": "" if allowed else (
            f"Your {entitlements.plan_label} plan has reached its product listing limit "
            f"({used}/{max_products}). Upgrade to add more offers."
        ),
    }
