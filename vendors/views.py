from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Avg
from .models import VendorProfile, VendorFollow, VendorReview
from products.models import Product
from orders.models import OrderItem
from subscriptions.models import user_has_paid_subscription, user_subscription_limits, user_subscription_tier
import random

def vendor_list(request):
    """List all vendors with sorting options"""
    # Get all verified and active vendors
    all_vendors = list(VendorProfile.objects.filter(is_verified=True, is_active=True))
    
    # Shuffle for all vendors
    vendors_shuffled = all_vendors.copy()
    random.shuffle(vendors_shuffled)
    
    # Top rated vendors (sorted by rating)
    top_rated_vendors = sorted(all_vendors, key=lambda x: x.rating_avg, reverse=True)[:4]
    
    # Trending vendors (sorted by sales)
    trending_vendors = sorted(all_vendors, key=lambda x: x.total_sales, reverse=True)[:4]
    
    # Pagination
    paginator = Paginator(vendors_shuffled, 12)
    page = request.GET.get('page', 1)
    vendors_page = paginator.get_page(page)
    
    context = {
        'vendors_shuffled': vendors_page,
        'top_rated_vendors': top_rated_vendors,
        'trending_vendors': trending_vendors,
        'total_vendors': len(all_vendors),
    }
    return render(request, 'vendors/list.html', context)

def vendor_detail(request, slug):
    """Display individual vendor shop page with follow status and similar vendors."""
    vendor = get_object_or_404(VendorProfile, store_slug=slug, is_active=True)

    products = Product.objects.filter(
        vendor=vendor.user,
        is_active=True,
        approval_status="approved"
    ).select_related("category", "brand").order_by("-created_at")

    # Similar vendors from same product categories
    product_categories = products.values_list("category_id", flat=True).distinct()

    similar_vendors = (
        VendorProfile.objects
        .filter(
            is_verified=True,
            is_active=True,
            user__products__category_id__in=product_categories
        )
        .exclude(id=vendor.id)
        .distinct()
        .order_by("-rating_avg", "-total_sales")[:4]
    )

    # Follow state
    is_following = False
    if request.user.is_authenticated:
        is_following = VendorFollow.objects.filter(
            user=request.user,
            vendor=vendor
        ).exists()

    followers_count = VendorFollow.objects.filter(vendor=vendor).count()
    subscription_limits = user_subscription_limits(vendor.user)
    chat_enabled = user_has_paid_subscription(vendor.user)
    store_reviews_enabled = bool(subscription_limits.get('store_reviews_enabled'))
    vendor_reviews = vendor.store_reviews.filter(is_active=True).select_related('user')[:8]
    customer_has_order = False
    if request.user.is_authenticated:
        customer_has_order = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__user=request.user,
            order__status='delivered'
        ).exists()

    # Keep stored followers_count synced
    if vendor.followers_count != followers_count:
        vendor.followers_count = followers_count
        vendor.save(update_fields=["followers_count"])

    # Vendor score calculation
    try:
        rating_score = float(vendor.rating_avg or 0) / 5 * 40
        sales_score = min(float(vendor.total_sales or 0) / 1000, 30)
        verified_score = 10 if vendor.is_verified else 0
        response_score = 10
        fulfillment_score = min(float(vendor.fulfillment_rate or 0) / 100 * 10, 10)
        follower_bonus = min(followers_count / 100, 5)

        vendor_score = round(
            rating_score
            + sales_score
            + verified_score
            + response_score
            + fulfillment_score
            + follower_bonus,
            2
        )
    except Exception:
        vendor_score = 0

    context = {
        "vendor": vendor,
        "products": products,
        "product_count": products.count(),
        "similar_vendors": similar_vendors,
        "is_following": is_following,
        "followers_count": followers_count,
        "vendor_score": vendor_score,
        "chat_enabled": chat_enabled,
        "subscription_tier": user_subscription_tier(vendor.user),
        "subscription_limits": subscription_limits,
        "store_reviews_enabled": store_reviews_enabled,
        "vendor_reviews": vendor_reviews,
        "customer_has_order": customer_has_order,
        "store_review_count": vendor.store_reviews.filter(is_active=True).count(),
        "store_review_avg": vendor.store_reviews.filter(is_active=True).aggregate(avg=Avg('rating'))['avg'] or 0,
    }

    return render(request, "vendors/detail.html", context)


@login_required
def add_vendor_review(request, vendor_id):
    """Create or update a customer review for a vendor storefront."""
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request method."}, status=405)

    vendor = get_object_or_404(VendorProfile, id=vendor_id, is_active=True)
    limits = user_subscription_limits(vendor.user)
    if not limits.get('store_reviews_enabled'):
        messages.info(request, "Store reviews are available only for vendors with an active paid subscription.")
        return redirect("vendors:detail", slug=vendor.store_slug)

    if request.user == vendor.user:
        messages.error(request, "You cannot review your own store.")
        return redirect("vendors:detail", slug=vendor.store_slug)

    rating = request.POST.get("rating", "5")
    title = request.POST.get("title", "").strip()
    comment = request.POST.get("comment", "").strip()

    if not comment:
        messages.error(request, "Please write a comment before submitting your review.")
        return redirect("vendors:detail", slug=vendor.store_slug)

    customer_has_order = OrderItem.objects.filter(
        product__vendor=vendor.user,
        order__user=request.user,
        order__status='delivered'
    ).exists()

    VendorReview.objects.create(
        vendor=vendor,
        user=request.user,
        rating=rating,
        title=title,
        comment=comment,
        is_active=True,
        is_verified_customer=customer_has_order,
    )

    messages.success(request, "Your vendor review was submitted. You can write another one anytime.")
    return redirect("vendors:detail", slug=vendor.store_slug)

@login_required
def become_vendor(request):
    """Allow user to become a vendor."""
    if hasattr(request.user, "vendor_profile"):
        messages.info(request, "You are already a vendor.")
        return redirect("vendors:detail", slug=request.user.vendor_profile.store_slug)

    if request.method == "POST":
        store_name = request.POST.get("store_name", "").strip()
        store_slug = request.POST.get("store_slug", "").strip()
        description = request.POST.get("description", "").strip()

        if not store_name or not store_slug or not description:
            messages.error(request, "Please fill in all fields.")
            return render(request, "vendors/become.html")

        if VendorProfile.objects.filter(store_slug=store_slug).exists():
            messages.error(request, "This store URL is already taken.")
            return render(request, "vendors/become.html")

        vendor = VendorProfile.objects.create(
            user=request.user,
            store_name=store_name,
            store_slug=store_slug,
            description=description,
            is_verified=True,
            is_active=True,
        )

        request.user.user_type = "vendor"
        request.user.save(update_fields=["user_type"])

        messages.success(request, "Congratulations! Your vendor account has been created.")
        return redirect("vendors:detail", slug=vendor.store_slug)

    return render(request, "vendors/become.html")
    
@login_required
def follow_vendor(request, vendor_id):
    """Toggle follow/unfollow for a vendor."""
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method."
        }, status=405)

    vendor = get_object_or_404(VendorProfile, id=vendor_id, is_active=True)

    follow, created = VendorFollow.objects.get_or_create(
        user=request.user,
        vendor=vendor
    )

    if created:
        followed = True
        message = f"You are now following {vendor.store_name}."
    else:
        follow.delete()
        followed = False
        message = f"You unfollowed {vendor.store_name}."

    followers_count = VendorFollow.objects.filter(vendor=vendor).count()

    vendor.followers_count = followers_count
    vendor.save(update_fields=["followers_count"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "success": True,
            "followed": followed,
            "followers_count": followers_count,
            "message": message,
        })

    messages.success(request, message)
    return redirect("vendors:detail", slug=vendor.store_slug)
