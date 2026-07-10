from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_slug
from django.db import IntegrityError, transaction
from django.db.models import Avg
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.template.loader import render_to_string

from orders.models import OrderItem
from products.models import Product
from subscriptions.models import (
    user_has_paid_subscription,
    user_subscription_limits,
    user_subscription_tier,
)

from .models import (
    VendorFollow,
    VendorProfile,
    VendorReview,
)


logger = logging.getLogger(__name__)


# ============================================================================
# HELPERS
# ============================================================================


def _decimal_or_none(value):
    try:
        if value in (
            None,
            "",
        ):
            return None

        return Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None


def _coordinate_is_valid(
    latitude,
    longitude,
):
    if latitude is None or longitude is None:
        return False

    return (
        Decimal("-90")
        <= latitude
        <= Decimal("90")
        and Decimal("-180")
        <= longitude
        <= Decimal("180")
    )


def _validation_messages(
    exc: ValidationError,
):
    if hasattr(
        exc,
        "message_dict",
    ):
        output = []

        for field_name, field_errors in (
            exc.message_dict.items()
        ):
            for error in field_errors:
                output.append(
                    f"{field_name}: {error}"
                )

        return output

    return list(
        exc.messages
    )


# ============================================================================
# VENDOR LIST
# ============================================================================


def vendor_list(request):
    """
    List approved, verified, and active vendors.
    """

    all_vendors = VendorProfile.objects.filter(
        is_verified=True,
        is_active=True,
        approval_status="approved",
    )

    vendors_ranked = all_vendors.order_by(
        "-is_top_rated",
        "-rating_avg",
        "-total_sales",
        "store_name",
    )

    top_rated_vendors = list(
        all_vendors.order_by(
            "-rating_avg",
            "store_name",
        )[:4]
    )

    trending_vendors = list(
        all_vendors.order_by(
            "-total_sales",
            "store_name",
        )[:4]
    )

    paginator = Paginator(
        vendors_ranked,
        12,
    )

    page = request.GET.get(
        "page",
        1,
    )

    vendors_page = paginator.get_page(
        page
    )

    context = {
        "vendors_shuffled": vendors_page,
        "top_rated_vendors": top_rated_vendors,
        "trending_vendors": trending_vendors,
        "total_vendors": all_vendors.count(),
    }

    if (
        request.headers.get(
            "X-Requested-With"
        )
        == "XMLHttpRequest"
    ):
        return JsonResponse(
            {
                "html": render_to_string(
                    "vendors/partials/vendor_grid.html",
                    context,
                    request=request,
                ),
                "pagination_html": render_to_string(
                    "products/partials/ajax_pagination.html",
                    {
                        "page_obj": vendors_page,
                        "pagination_id": (
                            "vendors-pagination"
                        ),
                        "wrapper_class": (
                            "mt-8 flex justify-center"
                        ),
                    },
                    request=request,
                ),
            }
        )

    return render(
        request,
        "vendors/list.html",
        context,
    )


# ============================================================================
# VENDOR DETAIL
# ============================================================================


def vendor_detail(
    request,
    slug,
):
    """
    Display an approved vendor storefront.

    The owner and staff may still view a pending vendor storefront.
    """

    base_queryset = (
        VendorProfile.objects
        .select_related(
            "user"
        )
        .filter(
            store_slug=slug,
        )
    )

    if (
        request.user.is_authenticated
        and request.user.is_staff
    ):
        vendor = get_object_or_404(
            base_queryset
        )

    else:
        vendor = get_object_or_404(
            base_queryset,
            is_active=True,
            approval_status="approved",
        )

    products = (
        Product.objects
        .filter(
            vendor=vendor.user,
            is_active=True,
            approval_status="approved",
        )
        .select_related(
            "category",
            "brand",
        )
        .order_by(
            "-created_at"
        )
    )

    product_categories = (
        products
        .values_list(
            "category_id",
            flat=True,
        )
        .distinct()
    )

    similar_vendors = (
        VendorProfile.objects
        .filter(
            is_verified=True,
            is_active=True,
            approval_status="approved",
            user__products__category_id__in=(
                product_categories
            ),
        )
        .exclude(
            id=vendor.id
        )
        .distinct()
        .order_by(
            "-rating_avg",
            "-total_sales",
        )[:4]
    )

    is_following = False

    if request.user.is_authenticated:
        is_following = (
            VendorFollow.objects
            .filter(
                user=request.user,
                vendor=vendor,
            )
            .exists()
        )

    followers_count = (
        VendorFollow.objects
        .filter(
            vendor=vendor
        )
        .count()
    )

    subscription_limits = (
        user_subscription_limits(
            vendor.user
        )
    )

    chat_enabled = (
        user_has_paid_subscription(
            vendor.user
        )
    )

    store_reviews_enabled = bool(
        subscription_limits.get(
            "store_reviews_enabled"
        )
    )

    vendor_reviews = (
        vendor.store_reviews
        .filter(
            is_active=True
        )
        .select_related(
            "user"
        )[:8]
    )

    customer_has_order = False

    if request.user.is_authenticated:
        customer_has_order = (
            OrderItem.objects
            .filter(
                product__vendor=vendor.user,
                order__user=request.user,
                order__status="delivered",
            )
            .exists()
        )

    if (
        vendor.followers_count
        != followers_count
    ):
        VendorProfile.objects.filter(
            pk=vendor.pk
        ).update(
            followers_count=followers_count
        )

        vendor.followers_count = (
            followers_count
        )

    try:
        rating_score = (
            float(
                vendor.rating_avg
                or 0
            )
            / 5
            * 40
        )

        sales_score = min(
            float(
                vendor.total_sales
                or 0
            )
            / 1000,
            30,
        )

        verified_score = (
            10
            if vendor.has_verified_kyc()
            else 0
        )

        response_score = 10

        fulfillment_score = min(
            (
                float(
                    vendor.fulfillment_rate
                    or 0
                )
                / 100
                * 10
            ),
            10,
        )

        follower_bonus = min(
            followers_count / 100,
            5,
        )

        vendor_score = round(
            rating_score
            + sales_score
            + verified_score
            + response_score
            + fulfillment_score
            + follower_bonus,
            2,
        )

    except (
        TypeError,
        ValueError,
        ArithmeticError,
    ):
        vendor_score = 0

    active_store_reviews = (
        vendor.store_reviews
        .filter(
            is_active=True
        )
    )

    context = {
        "vendor": vendor,
        "products": products,
        "product_count": products.count(),
        "similar_vendors": similar_vendors,
        "is_following": is_following,
        "followers_count": followers_count,
        "vendor_score": vendor_score,
        "chat_enabled": chat_enabled,
        "subscription_tier": (
            user_subscription_tier(
                vendor.user
            )
        ),
        "subscription_limits": (
            subscription_limits
        ),
        "store_reviews_enabled": (
            store_reviews_enabled
        ),
        "vendor_reviews": vendor_reviews,
        "customer_has_order": (
            customer_has_order
        ),
        "store_review_count": (
            active_store_reviews.count()
        ),
        "store_review_avg": (
            active_store_reviews.aggregate(
                avg=Avg(
                    "rating"
                )
            )["avg"]
            or 0
        ),
    }

    return render(
        request,
        "vendors/detail.html",
        context,
    )


# ============================================================================
# VENDOR REVIEWS
# ============================================================================


@login_required
def add_vendor_review(
    request,
    vendor_id,
):
    """
    Create a customer vendor-store review.
    """

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Invalid request method."
                ),
            },
            status=405,
        )

    vendor = get_object_or_404(
        VendorProfile,
        id=vendor_id,
        is_active=True,
        approval_status="approved",
    )

    limits = user_subscription_limits(
        vendor.user
    )

    if not limits.get(
        "store_reviews_enabled"
    ):
        messages.info(
            request,
            (
                "Store reviews are available only "
                "for vendors with an active paid "
                "subscription."
            ),
        )

        return redirect(
            "vendors:detail",
            slug=vendor.store_slug,
        )

    if request.user == vendor.user:
        messages.error(
            request,
            "You cannot review your own store.",
        )

        return redirect(
            "vendors:detail",
            slug=vendor.store_slug,
        )

    rating_raw = request.POST.get(
        "rating",
        "5",
    )

    try:
        rating = int(
            rating_raw
        )

    except (
        TypeError,
        ValueError,
    ):
        rating = 5

    rating = max(
        1,
        min(
            5,
            rating,
        ),
    )

    title = request.POST.get(
        "title",
        "",
    ).strip()

    comment = request.POST.get(
        "comment",
        "",
    ).strip()

    if not comment:
        messages.error(
            request,
            (
                "Please write a comment before "
                "submitting your review."
            ),
        )

        return redirect(
            "vendors:detail",
            slug=vendor.store_slug,
        )

    customer_has_order = (
        OrderItem.objects
        .filter(
            product__vendor=vendor.user,
            order__user=request.user,
            order__status="delivered",
        )
        .exists()
    )

    VendorReview.objects.create(
        vendor=vendor,
        user=request.user,
        rating=rating,
        title=title[:160],
        comment=comment,
        is_active=True,
        is_verified_customer=(
            customer_has_order
        ),
    )

    messages.success(
        request,
        (
            "Your vendor review was submitted. "
            "You can write another one anytime."
        ),
    )

    return redirect(
        "vendors:detail",
        slug=vendor.store_slug,
    )


# ============================================================================
# BECOME A VENDOR
# ============================================================================


@login_required
def become_vendor(request):
    """
    Create a pending vendor profile.

    This view does not accept private verification documents.
    KYC uploads must continue through the dedicated protected KYC flow.
    """

    if hasattr(
        request.user,
        "vendor_profile",
    ):
        messages.info(
            request,
            "You are already a vendor.",
        )

        return redirect(
            "vendors:detail",
            slug=(
                request.user
                .vendor_profile
                .store_slug
            ),
        )

    if request.method == "POST":
        store_name = request.POST.get(
            "store_name",
            "",
        ).strip()

        store_slug = request.POST.get(
            "store_slug",
            "",
        ).strip().lower()

        description = request.POST.get(
            "description",
            "",
        ).strip()

        address_line_1 = request.POST.get(
            "address_line_1",
            "",
        ).strip()

        city = request.POST.get(
            "city",
            "",
        ).strip()

        state = request.POST.get(
            "state",
            "",
        ).strip()

        country = (
            request.POST.get(
                "country",
                "Nigeria",
            ).strip()
            or "Nigeria"
        )

        pickup_contact_name = (
            request.POST.get(
                "pickup_contact_name",
                "",
            ).strip()
        )

        pickup_phone = request.POST.get(
            "pickup_phone",
            "",
        ).strip()

        pickup_address = request.POST.get(
            "pickup_address",
            "",
        ).strip()

        pickup_latitude = _decimal_or_none(
            request.POST.get(
                "pickup_latitude"
            )
        )

        pickup_longitude = _decimal_or_none(
            request.POST.get(
                "pickup_longitude"
            )
        )

        required_values = (
            store_name,
            store_slug,
            description,
            address_line_1,
            city,
            state,
            country,
            pickup_address,
        )

        if not all(
            required_values
        ):
            messages.error(
                request,
                (
                    "Please fill in all required fields, "
                    "including vendor address, city, state, "
                    "country, and pickup address."
                ),
            )

            return render(
                request,
                "vendors/become.html",
            )

        try:
            validate_slug(
                store_slug
            )

        except ValidationError:
            messages.error(
                request,
                (
                    "Store URL may contain only letters, "
                    "numbers, hyphens, and underscores."
                ),
            )

            return render(
                request,
                "vendors/become.html",
            )

        if not _coordinate_is_valid(
            pickup_latitude,
            pickup_longitude,
        ):
            messages.error(
                request,
                (
                    "Please provide a valid pickup map pin. "
                    "Latitude must be between -90 and 90, "
                    "and longitude between -180 and 180."
                ),
            )

            return render(
                request,
                "vendors/become.html",
            )

        if (
            VendorProfile.objects
            .filter(
                store_slug=store_slug
            )
            .exists()
        ):
            messages.error(
                request,
                "This store URL is already taken.",
            )

            return render(
                request,
                "vendors/become.html",
            )

        vendor = VendorProfile(
            user=request.user,
            store_name=store_name,
            store_slug=store_slug,
            description=description,
            address_line_1=address_line_1,
            city=city,
            state=state,
            country=country,
            business_address=address_line_1,
            pickup_contact_name=(
                pickup_contact_name
            ),
            pickup_phone=pickup_phone,
            pickup_address=pickup_address,
            pickup_latitude=(
                pickup_latitude
            ),
            pickup_longitude=(
                pickup_longitude
            ),
            is_verified=False,
            is_active=True,
            approval_status="pending",
        )

        try:
            vendor.full_clean()

            with transaction.atomic():
                vendor.save()

                request.user.user_type = (
                    "vendor"
                )

                request.user.save(
                    update_fields=[
                        "user_type",
                    ]
                )

        except ValidationError as exc:
            for error in _validation_messages(
                exc
            ):
                messages.error(
                    request,
                    error,
                )

            return render(
                request,
                "vendors/become.html",
            )

        except IntegrityError:
            logger.warning(
                (
                    "Vendor creation integrity error. "
                    "user_id=%s store_slug=%s"
                ),
                request.user.pk,
                store_slug,
            )

            messages.error(
                request,
                (
                    "This store URL or vendor account "
                    "already exists."
                ),
            )

            return render(
                request,
                "vendors/become.html",
            )

        messages.success(
            request,
            (
                "Congratulations! Your vendor account "
                "has been created and is pending approval."
            ),
        )

        return redirect(
            "vendors:detail",
            slug=vendor.store_slug,
        )

    return render(
        request,
        "vendors/become.html",
    )


# ============================================================================
# FOLLOW / UNFOLLOW
# ============================================================================


@login_required
def follow_vendor(
    request,
    vendor_id,
):
    """
    Toggle follow/unfollow for an approved vendor.
    """

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "Invalid request method."
                ),
            },
            status=405,
        )

    vendor = get_object_or_404(
        VendorProfile,
        id=vendor_id,
        is_active=True,
        approval_status="approved",
    )

    follow, created = (
        VendorFollow.objects
        .get_or_create(
            user=request.user,
            vendor=vendor,
        )
    )

    if created:
        followed = True

        message = (
            f"You are now following "
            f"{vendor.store_name}."
        )

    else:
        follow.delete()

        followed = False

        message = (
            f"You unfollowed "
            f"{vendor.store_name}."
        )

    followers_count = (
        VendorFollow.objects
        .filter(
            vendor=vendor
        )
        .count()
    )

    VendorProfile.objects.filter(
        pk=vendor.pk
    ).update(
        followers_count=followers_count
    )

    if (
        request.headers.get(
            "X-Requested-With"
        )
        == "XMLHttpRequest"
    ):
        return JsonResponse(
            {
                "success": True,
                "followed": followed,
                "followers_count": (
                    followers_count
                ),
                "message": message,
            }
        )

    messages.success(
        request,
        message,
    )

    return redirect(
        "vendors:detail",
        slug=vendor.store_slug,
    )