import logging
import mimetypes
import posixpath
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives, mail_admins
from django.db.models import F, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_safe
from types import SimpleNamespace
from accounts.models import User
from orders.models import Order
from products.models import Product
from vendors.models import VendorProfile
from notifications.models import Notification

from .models import VendorQuoteRequest

logger = logging.getLogger(__name__)


@require_safe
def proxy_media(request, path):
    """Serve public media from private storage without exposing the bucket."""
    normalized_path = posixpath.normpath(path).lstrip("/")

    if (
        not normalized_path
        or normalized_path == "."
        or normalized_path.startswith("../")
        or "/.." in normalized_path
    ):
        raise Http404("Media not found")

    allowed_prefixes = tuple(getattr(settings, "MEDIA_PROXY_PUBLIC_PREFIXES", ()))

    if allowed_prefixes:
        allowed = any(
            normalized_path == prefix.strip("/").strip()
            or normalized_path.startswith(f"{prefix.strip('/').strip()}/")
            for prefix in allowed_prefixes
            if prefix.strip("/").strip()
        )

        if not allowed:
            raise Http404("Media not found")

    try:
        media_file = default_storage.open(normalized_path, "rb")
    except Exception as exc:
        raise Http404("Media not found") from exc

    content_type = mimetypes.guess_type(normalized_path)[0] or "application/octet-stream"
    response = FileResponse(media_file, content_type=content_type)
    response["Cache-Control"] = "public, max-age=31536000, immutable"

    return response


def time_since(dt):
    """Return a human-readable time since string."""
    if not dt:
        return "Just now"

    now = timezone.now()
    diff = now - dt

    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"

    if diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"

    if diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"

    return "Just now"


@staff_member_required
def live_stats(request):
    """API endpoint for live admin statistics."""
    now_dt = timezone.now()
    today = now_dt.date()
    month_ago = now_dt - timedelta(days=30)

    total_users = User.objects.count()
    total_products = Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).count()
    total_orders = Order.objects.count()
    pending_orders = Order.objects.filter(status="pending").count()
    pending_products = Product.objects.filter(approval_status="pending").count()

    low_stock_products = Product.objects.filter(
        is_active=True,
        stock_quantity__gt=0,
        stock_quantity__lte=F("low_stock_threshold"),
    ).count()

    out_of_stock_products = Product.objects.filter(
        is_active=True,
        stock_quantity__lte=0,
    ).count()

    total_vendors = VendorProfile.objects.filter(is_verified=True).count()
    pending_vendors = VendorProfile.objects.filter(is_verified=False).count()

    delivered_revenue = (
        Order.objects.filter(status="delivered").aggregate(total=Sum("total"))["total"]
        or 0
    )

    unread_notifications = 0

    if request.user.is_authenticated:
        try:
            unread_notifications = request.user.notifications.filter(
                is_read=False,
                is_archived=False,
            ).count()
        except Exception:
            unread_notifications = 0

    prev_total_users = User.objects.filter(date_joined__lt=month_ago).count()

    prev_total_products = Product.objects.filter(
        created_at__lt=month_ago,
        is_active=True,
    ).count()

    prev_total_orders = Order.objects.filter(created_at__lt=month_ago).count()

    prev_pending_orders = Order.objects.filter(
        status="pending",
        created_at__lt=month_ago,
    ).count()

    chart_labels = []
    chart_data = []

    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime("%b %d"))

        revenue = (
            Order.objects.filter(
                created_at__date=day,
                status="delivered",
            ).aggregate(total=Sum("total"))["total"]
            or 0
        )

        chart_data.append(float(revenue))

    recent_orders = []

    for order in Order.objects.select_related("user").order_by("-created_at")[:5]:
        recent_orders.append({
            "title": f"Order #{order.id}",
            "time_ago": time_since(order.created_at),
            "amount": float(order.total),
        })

    recent_users = []

    for user in User.objects.order_by("-date_joined")[:5]:
        recent_users.append({
            "title": user.username,
            "time_ago": time_since(user.date_joined),
        })

    recent_products = []

    for product in Product.objects.filter(
        is_active=True,
        approval_status="approved",
    ).order_by("-created_at")[:5]:
        recent_products.append({
            "title": product.name[:30],
            "time_ago": time_since(product.created_at),
            "amount": float(product.price),
        })

    return JsonResponse({
        "total_users": total_users,
        "total_products": total_products,
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "pending_products": pending_products,
        "low_stock_products": low_stock_products,
        "out_of_stock_products": out_of_stock_products,
        "total_vendors": total_vendors,
        "pending_vendors": pending_vendors,
        "total_revenue": float(delivered_revenue),
        "unread_notifications": unread_notifications,
        "prev_total_users": prev_total_users,
        "prev_total_products": prev_total_products,
        "prev_total_orders": prev_total_orders,
        "prev_pending_orders": prev_pending_orders,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "recent_orders": recent_orders,
        "recent_users": recent_users,
        "recent_products": recent_products,
    })


def request_vendor_quote(request):
    """
    Customer quote request flow.

    Customer -> Arolana Quote Request -> Admin + Assigned Vendor notification.
    """
    vendor_id = request.GET.get("vendor") or request.POST.get("vendor")
    product_name = request.GET.get("product_name") or request.POST.get("product_name") or ""
    product_url = request.GET.get("product_url") or request.POST.get("product_url") or ""

    if not vendor_id:
        messages.error(request, "Vendor was not selected for this quote request.")
        return redirect("vendors:list")

    vendor = get_object_or_404(
        VendorProfile,
        id=vendor_id,
        is_active=True,
    )

    initial_name = ""
    initial_email = ""

    if request.user.is_authenticated:
        initial_name = request.user.get_full_name() or request.user.get_username()
        initial_email = request.user.email or ""

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        subject = (request.POST.get("subject") or "").strip()
        message = (request.POST.get("message") or "").strip()

        errors = []

        if not name:
            errors.append("Please enter your full name.")

        if not email and not phone:
            errors.append("Please enter either your email address or phone/WhatsApp number.")

        if not message:
            errors.append("Please describe what you need a quote for.")

        if errors:
            for error in errors:
                messages.error(request, error)

            return render(
                request,
                "core/request_vendor_quote.html",
                {
                    "vendor": vendor,
                    "product_name": product_name,
                    "product_url": product_url,
                    "form_data": request.POST,
                },
            )

        quote = VendorQuoteRequest.objects.create(
            customer=request.user if request.user.is_authenticated else None,
            vendor=vendor,
            name=name,
            email=email,
            phone=phone,
            subject=subject or f"Quote request for {vendor.store_name}",
            message=message,
            product_name=product_name[:255],
            product_url=product_url,
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            status="new",
        )

        email_result = send_vendor_quote_notifications(quote)

        if email_result.get("vendor_email_sent"):
            quote.status = "sent_to_vendor"
            quote.sent_to_vendor_at = timezone.now()
        quote.email_notification_status = email_result
        quote.save(update_fields=["status", "sent_to_vendor_at", "email_notification_status", "updated_at"])

        Notification.send(
            user=vendor.user,
            notification_type="vendor",
            title="New quote request from your Arolana store",
            message=f"{name} requested a quote for {product_name or vendor.store_name}.",
            link="/dashboard/vendor/quote-requests/",
            metadata={"quote_request_id": quote.id},
            priority=3,
        )
        for admin_user in User.objects.filter(is_active=True).filter(
            Q(is_staff=True) | Q(is_superuser=True)
        ).distinct()[:20]:
            Notification.send(
                user=admin_user,
                notification_type="vendor",
                title="New Arolana quote request",
                message=f"{name} requested a quote from {vendor.store_name}.",
                link=f"/admin/core/vendorquoterequest/{quote.id}/change/",
                metadata={"quote_request_id": quote.id},
                priority=3,
            )
        if quote.customer_id:
            Notification.send(
                user=quote.customer,
                notification_type="success",
                title="We received your quote request",
                message=f"Arolana and {vendor.store_name} have received your request.",
                link="/account/",
                metadata={"quote_request_id": quote.id},
            )

        messages.success(
            request,
            "Your quote request has been sent to Arolana and the vendor. You will be contacted shortly.",
        )

        return redirect("vendors:detail", slug=vendor.store_slug)

    return render(
        request,
        "core/request_vendor_quote.html",
        {
            "vendor": vendor,
            "product_name": product_name,
            "product_url": product_url,
            "form_data": {
                "name": initial_name,
                "email": initial_email,
                "subject": f"Quote request for {product_name or vendor.store_name}",
            },
        },
    )


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def get_vendor_quote_email(vendor):
    """
    Get best vendor email for quote notification.

    Priority:
    1. support_email
    2. business_email
    3. user.email
    """
    return (
        getattr(vendor, "support_email", "")
        or getattr(vendor, "business_email", "")
        or getattr(getattr(vendor, "user", None), "email", "")
    )


def send_vendor_quote_notifications(quote):
    """
    Notify Arolana admin and assigned vendor.

    Admin receives control/tracking email.
    Vendor receives customer quote enquiry.
    Quote is still saved even if email fails.
    """
    from_email = getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "Arolana <admin@arolana.com>",
    )

    admin_email = (
        getattr(settings, "CONTACT_EMAIL", None)
        or getattr(settings, "ADMIN_EMAIL", None)
        or getattr(settings, "DEFAULT_FROM_EMAIL", "admin@arolana.com")
    )

    vendor_email = get_vendor_quote_email(quote.vendor)

    subject = f"New quote request for {quote.vendor.store_name}"

    product_label = quote.product_name or "General vendor enquiry"
    product_url = quote.product_url or "Not provided"

    admin_message = f"""
New quote request received on Arolana.

Quote ID: {quote.id}
Vendor: {quote.vendor.store_name}

Customer Name: {quote.name}
Customer Email: {quote.email or "Not provided"}
Customer Phone: {quote.phone or "Not provided"}

Subject:
{quote.subject}

Message:
{quote.message}

Product:
{product_label}

Product URL:
{product_url}

Status:
{quote.get_status_display()}

This request is saved in Django Admin > Core > Vendor Quote Requests.
"""

    vendor_message = f"""
Hello {quote.vendor.store_name},

You have received a new quote request from Arolana.

Customer Name: {quote.name}
Customer Email: {quote.email or "Not provided"}
Customer Phone: {quote.phone or "Not provided"}

Subject:
{quote.subject}

Message:
{quote.message}

Product:
{product_label}

Product URL:
{product_url}

Please respond quickly from your Arolana vendor dashboard or contact Arolana support.

Arolana Marketplace
"""

    admin_html = f"""
<h2>New quote request received on Arolana</h2>
<p><strong>Quote ID:</strong> {quote.id}</p>
<p><strong>Vendor:</strong> {quote.vendor.store_name}</p>
<hr>
<p><strong>Customer:</strong> {quote.name}</p>
<p><strong>Email:</strong> {quote.email or "Not provided"}</p>
<p><strong>Phone:</strong> {quote.phone or "Not provided"}</p>
<p><strong>Subject:</strong> {quote.subject}</p>
<p><strong>Product:</strong> {product_label}</p>
<p><strong>Product URL:</strong> {product_url}</p>
<h3>Message</h3>
<p>{quote.message}</p>
<p>This request is saved in <strong>Django Admin &gt; Core &gt; Vendor Quote Requests</strong>.</p>
"""

    vendor_html = f"""
<h2>New quote request from Arolana</h2>
<p>Hello <strong>{quote.vendor.store_name}</strong>,</p>
<p>You have received a new customer quote request.</p>
<hr>
<p><strong>Customer:</strong> {quote.name}</p>
<p><strong>Email:</strong> {quote.email or "Not provided"}</p>
<p><strong>Phone:</strong> {quote.phone or "Not provided"}</p>
<p><strong>Subject:</strong> {quote.subject}</p>
<p><strong>Product:</strong> {product_label}</p>
<p><strong>Product URL:</strong> {product_url}</p>
<h3>Message</h3>
<p>{quote.message}</p>
<p>Please respond quickly from your Arolana vendor dashboard or contact Arolana support.</p>
"""

    result = {
        "admin_email_sent": False,
        "vendor_email_sent": False,
        "vendor_email": vendor_email,
        "admin_email": admin_email,
    }

    try:
        admin_email_message = EmailMultiAlternatives(
            subject=subject,
            body=admin_message,
            from_email=from_email,
            to=[admin_email],
            reply_to=[quote.email] if quote.email else None,
        )
        admin_email_message.attach_alternative(admin_html, "text/html")
        admin_email_message.send(fail_silently=False)
        result["admin_email_sent"] = True

    except Exception as error:
        logger.exception("Failed to send quote request email to admin for quote %s", quote.id)

        try:
            mail_admins(
                subject=f"Quote email failure for quote #{quote.id}",
                message=f"Admin quote email failed.\n\nError: {error}\n\nQuote ID: {quote.id}",
                fail_silently=True,
            )
        except Exception:
            pass

    if vendor_email:
        try:
            vendor_email_message = EmailMultiAlternatives(
                subject=subject,
                body=vendor_message,
                from_email=from_email,
                to=[vendor_email],
                reply_to=[quote.email] if quote.email else None,
            )
            vendor_email_message.attach_alternative(vendor_html, "text/html")
            vendor_email_message.send(fail_silently=False)
            result["vendor_email_sent"] = True

        except Exception:
            logger.exception("Failed to send quote request email to vendor for quote %s", quote.id)

    else:
        logger.warning(
            "Vendor quote request %s has no vendor email. Vendor: %s",
            quote.id,
            quote.vendor_id,
        )

    return result


def debug_home(request):
    """Debug view to test currency on homepage."""
    products = Product.objects.filter(is_active=True, approval_status="approved")[:5]

    html = "<html><body><h1>Currency Debug</h1>"
    html += f"<p>Session Currency: {request.session.get('user_currency', 'NOT SET')}</p>"
    html += "<h2>Products:</h2><ul>"

    from currency.templatetags.currency_filters import currency

    for product in products:
        price_usd = product.price
        price_converted = currency(price_usd, request)
        html += f"<li>{product.name}: ${price_usd} USD = {price_converted}</li>"

    html += "</ul>"
    html += "<p><a href='/currency/switch/?code=USD&next=/debug/'>Set USD</a> | "
    html += "<a href='/currency/switch/?code=NGN&next=/debug/'>Set NGN</a></p>"
    html += "<p><a href='/'>Back to Home</a></p>"
    html += "</body></html>"

    return HttpResponse(html)


def home(request):
    """Main homepage view with all sections including video."""
    from homepage.models import HomepageBanner, HomepageCategory, HomepageVideoSection

    video_section = (
        HomepageVideoSection.objects
        .filter(is_active=True)
        .order_by("display_order")
        .first()
    )

    banners = HomepageBanner.objects.filter(is_active=True).order_by("display_order")
    categories = HomepageCategory.objects.filter(is_active=True).order_by("display_order")
    featured_products = Product.objects.filter(is_featured=True, is_active=True)[:8]
    vendors = VendorProfile.objects.filter(is_verified=True, is_active=True)[:12]

    context = {
        "video_section": video_section,
        "banners": banners,
        "categories": categories,
        "featured_products": featured_products,
        "vendors": vendors,
    }

    return render(request, "base/home.html", context)

def build_static_page_context(title, subtitle, slug, meta_description=""):
    page = SimpleNamespace(
        title=title,
        subtitle=subtitle,
        slug=slug,
        content="",
        meta_title=f"{title} | Arolana",
        meta_description=meta_description or subtitle,
    )

    return {
        "page": page,
        "page_title": title,
        "page_subtitle": subtitle,
        "meta_title": f"{title} | Arolana",
        "meta_description": meta_description or subtitle,
        "show_side_ads": False,
    }


def terms_and_conditions(request):
    return render(
        request,
        "pages/terms.html",
        build_static_page_context(
            title="Terms and Conditions",
            subtitle="Rules for using Arolana marketplace, vendor services, orders, payments, delivery, quote requests, subscriptions, and support.",
            slug="terms-and-conditions",
            meta_description="Arolana marketplace terms covering customers, vendors, service providers, orders, payments, delivery, quote requests, subscriptions, and support.",
        ),
    )


def privacy_policy(request):
    return render(
        request,
        "pages/privacy.html",
        build_static_page_context(
            title="Privacy Policy",
            subtitle="How Arolana collects, uses, protects, and manages customer, vendor, and service provider information.",
            slug="privacy-policy",
        ),
    )


def return_policy(request):
    return render(
        request,
        "pages/returns.html",
        build_static_page_context(
            title="Return Policy",
            subtitle="Arolana return, refund, exchange, inspection, and warranty guidance for marketplace orders.",
            slug="return-policy",
        ),
    )


def shipping_policy(request):
    return render(
        request,
        "support/shipping.html",
        build_static_page_context(
            title="Shipping and Delivery",
            subtitle="Delivery timelines, pickup, logistics, shipping fees, and fulfillment guidance for Arolana orders.",
            slug="shipping",
        ),
    )


def help_center(request):
    return render(
        request,
        "pages/help_center.html",
        build_static_page_context(
            title="Help Center",
            subtitle="Get help with orders, vendors, delivery, payments, quotes, returns, and Arolana support.",
            slug="help",
        ),
    )


def contact_page(request):
    return render(
        request,
        "pages/contact.html",
        build_static_page_context(
            title="Contact Arolana",
            subtitle="Contact Arolana support for customer, vendor, service provider, quote, order, or marketplace assistance.",
            slug="contact",
        ),
    )
    
