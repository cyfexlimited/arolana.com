import mimetypes
import posixpath

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe
from products.models import Product
from currency.models import Currency
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Sum, Count
from django.utils import timezone
from datetime import timedelta
from orders.models import Order
from accounts.models import User
from vendors.models import VendorProfile
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .models import VendorQuoteRequest

@require_safe
def proxy_media(request, path):
    """Serve public media from private storage without exposing the bucket."""
    normalized_path = posixpath.normpath(path).lstrip('/')
    if (
        not normalized_path
        or normalized_path == '.'
        or normalized_path.startswith('../')
        or '/..' in normalized_path
    ):
        raise Http404('Media not found')

    allowed_prefixes = tuple(getattr(settings, 'MEDIA_PROXY_PUBLIC_PREFIXES', ()))
    if allowed_prefixes:
        allowed = any(
            normalized_path == prefix.strip('/').strip()
            or normalized_path.startswith(f"{prefix.strip('/').strip()}/")
            for prefix in allowed_prefixes
            if prefix.strip('/').strip()
        )
        if not allowed:
            raise Http404('Media not found')

    try:
        media_file = default_storage.open(normalized_path, 'rb')
    except Exception as exc:
        raise Http404('Media not found') from exc

    content_type = mimetypes.guess_type(normalized_path)[0] or 'application/octet-stream'
    response = FileResponse(media_file, content_type=content_type)
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

def time_since(dt):
    """Returns a human-readable time since string"""
    if not dt:
        return "Just now"
    now = timezone.now()
    diff = now - dt
    
    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"

@staff_member_required
def live_stats(request):
    """API endpoint for live statistics"""
    now_dt = timezone.now()
    today = now_dt.date()
    month_ago = now_dt - timedelta(days=30)
    
    # Current month stats
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True, approval_status="approved").count()
    total_orders = Order.objects.count()
    pending_orders = Order.objects.filter(status='pending').count()
    pending_products = Product.objects.filter(approval_status='pending').count()
    low_stock_products = Product.objects.filter(
        is_active=True,
        stock_quantity__gt=0,
        stock_quantity__lte=F('low_stock_threshold'),
    ).count()
    out_of_stock_products = Product.objects.filter(is_active=True, stock_quantity__lte=0).count()
    total_vendors = VendorProfile.objects.filter(is_verified=True).count()
    pending_vendors = VendorProfile.objects.filter(is_verified=False).count()
    delivered_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0

    unread_notifications = 0
    if request.user.is_authenticated:
        try:
            unread_notifications = request.user.notifications.filter(is_read=False, is_archived=False).count()
        except Exception:
            unread_notifications = 0
    
    # Previous month stats (for trend calculation)
    prev_total_users = User.objects.filter(date_joined__lt=month_ago).count()
    prev_total_products = Product.objects.filter(created_at__lt=month_ago, is_active=True).count()
    prev_total_orders = Order.objects.filter(created_at__lt=month_ago).count()
    prev_pending_orders = Order.objects.filter(
        status='pending',
        created_at__lt=month_ago
    ).count()
    
    # Chart data for last 30 days
    chart_labels = []
    chart_data = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime('%b %d'))
        revenue = Order.objects.filter(
            created_at__date=day,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0
        chart_data.append(float(revenue))
    
    # Recent orders
    recent_orders = []
    for order in Order.objects.select_related('user').order_by('-created_at')[:5]:
        recent_orders.append({
            'title': f'Order #{order.id}',
            'time_ago': time_since(order.created_at),
            'amount': float(order.total)
        })
    
    # Recent users
    recent_users = []
    for user in User.objects.order_by('-date_joined')[:5]:
        recent_users.append({
            'title': user.username,
            'time_ago': time_since(user.date_joined)
        })
    
    # Recent products
    recent_products = []
    for product in Product.objects.filter(is_active=True, approval_status="approved").order_by('-created_at')[:5]:
        recent_products.append({
            'title': product.name[:30],
            'time_ago': time_since(product.created_at),
            'amount': float(product.price)
        })
    
    return JsonResponse({
        'total_users': total_users,
        'total_products': total_products,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'pending_products': pending_products,
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'total_vendors': total_vendors,
        'pending_vendors': pending_vendors,
        'total_revenue': float(delivered_revenue),
        'unread_notifications': unread_notifications,
        'prev_total_users': prev_total_users,
        'prev_total_products': prev_total_products,
        'prev_total_orders': prev_total_orders,
        'prev_pending_orders': prev_pending_orders,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'recent_orders': recent_orders,
        'recent_users': recent_users,
        'recent_products': recent_products,
    })

def request_vendor_quote(request):
    """
    Customer quote request flow.

    Flow:
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

        send_vendor_quote_notifications(quote)

        messages.success(
            request,
            "Your quote request has been sent to Arolana and the vendor. You will be contacted shortly.",
        )

        return redirect("vendors:detail", vendor.store_slug)

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


def send_vendor_quote_notifications(quote):
    """
    Notify Arolana admin and assigned vendor.
    This keeps Arolana in control while still alerting the vendor.
    """
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "admin@arolana.com")
    admin_email = getattr(settings, "CONTACT_EMAIL", None) or getattr(settings, "DEFAULT_FROM_EMAIL", "admin@arolana.com")

    vendor_email = (
        getattr(quote.vendor, "support_email", "")
        or getattr(quote.vendor, "business_email", "")
        or getattr(getattr(quote.vendor, "user", None), "email", "")
    )

    subject = f"New Arolana quote request: {quote.vendor.store_name}"

    admin_message = f"""
New quote request received on Arolana.

Vendor: {quote.vendor.store_name}
Customer: {quote.name}
Email: {quote.email}
Phone: {quote.phone}
Subject: {quote.subject}

Message:
{quote.message}

Product: {quote.product_name}
Product URL: {quote.product_url}

Quote ID: {quote.id}
"""

    vendor_message = f"""
You have a new quote request from Arolana.

Customer: {quote.name}
Email: {quote.email}
Phone: {quote.phone}
Subject: {quote.subject}

Message:
{quote.message}

Product: {quote.product_name}
Product URL: {quote.product_url}

Please respond quickly from your vendor dashboard or contact Arolana support.
"""

    try:
        send_mail(
            subject,
            admin_message,
            from_email,
            [admin_email],
            fail_silently=True,
        )

        if vendor_email:
            send_mail(
                subject,
                vendor_message,
                from_email,
                [vendor_email],
                fail_silently=True,
            )

    except Exception:
        pass

def debug_home(request):
    """Debug view to test currency on homepage"""
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
    """Main homepage view with all sections including video"""
    from homepage.models import HomepageVideoSection, HomepageBanner, HomepageCategory
    from vendors.models import VendorProfile
    
    # Get video section
    video_section = HomepageVideoSection.objects.filter(is_active=True).order_by('display_order').first()
    
    # Get banners for carousel
    banners = HomepageBanner.objects.filter(is_active=True).order_by('display_order')
    
    # Get categories
    categories = HomepageCategory.objects.filter(is_active=True).order_by('display_order')
    
    # Get featured products
    featured_products = Product.objects.filter(is_featured=True, is_active=True)[:8]
    
    # Get vendors
    vendors = VendorProfile.objects.filter(is_verified=True, is_active=True)[:12]
    
    context = {
        'video_section': video_section,
        'banners': banners,
        'categories': categories,
        'featured_products': featured_products,
        'vendors': vendors,
    }
    return render(request, 'base/home.html', context)
