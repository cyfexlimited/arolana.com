from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import models
from django.db.models import Sum, Count, Q, Avg, F
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django.db import transaction
from decimal import Decimal, InvalidOperation
import json
import random
import string

from products.models import Product, Category, ProductReview, Wishlist, RecentlyViewed, ProductVariant, ProductVariantImage, ProductQuestion, Accessory, AccessoryProduct, ProductImage, ProductVideo, Brand
from vendors.models import VendorProfile
from accounts.models import User
from orders.models import Order, OrderItem
from deliveries.models import DeliveryRequest
from .models import AdminActivityLog, SystemAlert, VendorAdminMessage, VendorNotification
from subscriptions.models import SubscriptionPlan, VendorSubscription, subscription_label, user_has_paid_subscription, user_subscription_limits, user_subscription_tier
from arolana_payments.models import PaymentTransaction
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError
from core.image_protection import (
    duplicate_warning_payload,
    inspect_vendor_image_upload,
    set_protected_image_uploader,
)

from order_robot.models import OrderRobotVendorTask
from order_robot.services import vendor_mark_confirmed, vendor_mark_rejected
from vendors.security import send_vendor_password_changed_email
from notifications.models import Notification

try:
    from chat.models import VendorChatRoom
except Exception:
    VendorChatRoom = None

# ==================== HELPER FUNCTIONS ====================

def get_paginated_items(queryset, page_num, per_page=20):
    """Get paginated items with error handling"""
    paginator = Paginator(queryset, per_page)
    try:
        return paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)

def seller_has_verified_kyc(user):
    try:
        profile = user.vendor_profile
        return profile.has_verified_kyc()
    except ObjectDoesNotExist:
        return False

def require_verified_kyc(request):
    if seller_has_verified_kyc(request.user):
        return None
    messages.error(request, 'KYC verification must be approved before you can upload or manage products.')
    return redirect('kyc:dashboard')


def vendor_selectable_categories():
    """
    Vendors should choose a real selling category, not broad admin departments.
    Leaf categories are preferred; if a category has no configured children it remains selectable.
    """
    return (
        Category.objects
        .filter(is_active=True)
        .annotate(active_child_count=Count('children', filter=Q(children__is_active=True)))
        .filter(Q(parent__isnull=False) | Q(active_child_count=0))
        .order_by('parent__name', 'order', 'name')
    )


def _vendor_image_review_notice(request, instance, field_name, emit_message=True):
    if not getattr(instance, field_name, None):
        return None
    set_protected_image_uploader(instance, field_name, request.user)
    warning = duplicate_warning_payload(instance, field_name)
    if not warning:
        return None
    if emit_message and warning.get("needs_review"):
        messages.warning(
            request,
            warning.get("message")
            or "This image matches another vendor upload and has been sent for Arolana review.",
        )
    elif emit_message and warning.get("same_vendor_reuse"):
        messages.info(
            request,
            warning.get("message") or "Image reused from your existing Arolana catalogue.",
        )
    return warning


def _vendor_image_review_payload(user, instance, field_name):
    if not getattr(instance, field_name, None):
        return None
    set_protected_image_uploader(instance, field_name, user)
    return duplicate_warning_payload(instance, field_name)


def _inspect_vendor_product_uploads(request):
    results = []
    for field_name, files in request.FILES.lists():
        if field_name not in {"main_image", "additional_images"} and not field_name.startswith("variant_images_"):
            continue
        for image_file in files:
            result = inspect_vendor_image_upload(image_file, request.user)
            result["field_name"] = field_name
            results.append(result)
    blocked = [item for item in results if not item.get("allowed", True)]
    if blocked:
        first = blocked[0]
        raise ValidationError(first.get("message") or "This image cannot be used by this vendor.")
    return results


def _decimal_or_none(value):
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _percent(part, total, fallback=0):
    if not total:
        return round(float(fallback or 0), 1)
    return round((float(part or 0) / float(total)) * 100, 1)


def _vendor_unread_admin_count(user):
    return VendorAdminMessage.objects.filter(
        recipient=user,
        status='unread',
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    ).count()


def _vendor_customer_chat_stats(user):
    if VendorChatRoom is None:
        return {'customer_chat_unread': 0, 'customer_chat_count': 0}
    rooms = VendorChatRoom.objects.filter(vendor=user, is_active=True)
    return {
        'customer_chat_unread': rooms.aggregate(total=Sum('vendor_unread'))['total'] or 0,
        'customer_chat_count': rooms.count(),
    }


def _vendor_subscription_context(user):
    tier = user_subscription_tier(user)
    limits = user_subscription_limits(user)
    current_subscription = VendorSubscription.objects.filter(
        vendor=user,
        is_active=True,
        end_date__gt=timezone.now()
    ).select_related('plan').first()
    vendor_profile = getattr(user, 'vendor_profile', None)
    subscription_invoices = PaymentTransaction.objects.filter(
        user=user,
        checkout_data__purpose='vendor_subscription',
    ).order_by('-created_at')[:12]
    subscription_plans = SubscriptionPlan.objects.filter(is_active=True).order_by('order', 'price_monthly')
    expires_at = None
    if current_subscription:
        expires_at = current_subscription.end_date
    elif vendor_profile:
        expires_at = getattr(vendor_profile, 'subscription_expires_at', None) or vendor_profile.subscription_expiry
    return {
        'subscription_tier': tier,
        'subscription_label': subscription_label(tier),
        'subscription_limits': limits,
        'subscription_benefits_image_url': '/static/images/arolana-vendor-subscription-benefits.png',
        'current_subscription': current_subscription,
        'subscription_profile': vendor_profile,
        'subscription_active': bool(getattr(vendor_profile, 'subscription_active', False)) if vendor_profile else False,
        'subscription_started_at': getattr(vendor_profile, 'subscription_started_at', None) if vendor_profile else None,
        'subscription_expires_at': expires_at,
        'subscription_expiring_soon': bool(expires_at and expires_at <= timezone.now() + timedelta(days=3)),
        'subscription_plans': subscription_plans,
        'subscription_invoices': subscription_invoices,
        'chat_enabled': user_has_paid_subscription(user),
    }


def _vendor_performance_context(user, vendor_profile=None):
    all_products = Product.objects.filter(vendor=user)
    active_products = all_products.filter(is_active=True, approval_status='approved')
    order_items = OrderItem.objects.filter(product__vendor=user)
    orders = Order.objects.filter(items__product__vendor=user).distinct()
    reviews = ProductReview.objects.filter(product__vendor=user, is_active=True)

    delivered_count = orders.filter(status='delivered').count()
    shipped_count = orders.filter(status='shipped').count()
    cancelled_count = orders.filter(status='cancelled').count()
    refunded_count = orders.filter(status='refunded').count()
    completed_or_problem_count = delivered_count + shipped_count + cancelled_count + refunded_count
    fallback_fulfillment = getattr(vendor_profile, 'fulfillment_rate', 0) if vendor_profile else 0
    fallback_return = getattr(vendor_profile, 'return_rate', 0) if vendor_profile else 0
    fulfillment_rate = _percent(delivered_count + shipped_count, completed_or_problem_count, fallback_fulfillment)
    return_rate = _percent(refunded_count, completed_or_problem_count, fallback_return)

    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    rating_score = _percent(avg_rating, 5)
    in_stock_count = active_products.filter(Q(stock_quantity__gt=F('low_stock_threshold')) | Q(allow_backorder=True)).count()
    product_health = _percent(in_stock_count, active_products.count(), 100 if active_products.exists() else 0)
    approved_count = all_products.filter(approval_status='approved').count()
    approval_base = all_products.exclude(approval_status='rejected').count() or all_products.count()
    approval_rate = _percent(approved_count, approval_base, 0)
    kyc_score = 100 if vendor_profile and vendor_profile.has_verified_kyc() else 0
    subscription_priority = user_subscription_limits(user).get('priority_score', 0)

    vendor_score = round(
        (rating_score * 0.30) +
        (fulfillment_rate * 0.25) +
        (approval_rate * 0.15) +
        (product_health * 0.15) +
        (float(subscription_priority) * 0.10) +
        (kyc_score * 0.05),
        1
    )
    vendor_score = min(100, max(0, vendor_score))

    if vendor_score >= 85:
        vendor_score_label = 'Excellent'
    elif vendor_score >= 70:
        vendor_score_label = 'Strong'
    elif vendor_score >= 50:
        vendor_score_label = 'Building'
    else:
        vendor_score_label = 'Needs Attention'

    total_units_sold = order_items.filter(order__status='delivered').aggregate(total=Sum('quantity'))['total'] or 0
    total_views = all_products.aggregate(total=Sum('views_count'))['total'] or 0

    return {
        'vendor_score': vendor_score,
        'vendor_score_label': vendor_score_label,
        'fulfillment_rate': fulfillment_rate,
        'return_rate': return_rate,
        'delivered_count': delivered_count,
        'shipped_count': shipped_count,
        'cancelled_count': cancelled_count,
        'refunded_count': refunded_count,
        'product_health': product_health,
        'approval_rate': approval_rate,
        'total_units_sold': total_units_sold,
        'total_views': total_views,
        'score_breakdown': [
            {'label': 'Customer rating', 'value': round(rating_score, 1)},
            {'label': 'Fulfillment', 'value': fulfillment_rate},
            {'label': 'Approval quality', 'value': approval_rate},
            {'label': 'Inventory health', 'value': product_health},
            {'label': 'Subscription boost', 'value': subscription_priority},
            {'label': 'KYC trust', 'value': kyc_score},
        ],
    }

# ==================== PROFESSIONAL ADMIN DASHBOARD ====================

@staff_member_required
def admin_dashboard_index(request):
    """Professional admin dashboard with modern UI"""
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True, approval_status='approved').count()
    vendors_count = VendorProfile.objects.filter(is_verified=True).count()
    low_stock_count = Product.objects.filter(stock_quantity__lte=5, is_active=True, approval_status='approved').count()
    
    revenue_growth = Order.objects.filter(
        created_at__date__gte=week_ago, 
        status='delivered'
    ).aggregate(total=Sum('total'))['total'] or 0
    order_growth = Order.objects.filter(created_at__date__gte=week_ago).count()
    
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    recent_activity = AdminActivityLog.objects.select_related('admin').order_by('-created_at')[:20]
    
    context = {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'total_users': total_users,
        'total_products': total_products,
        'vendors_count': vendors_count,
        'low_stock_count': low_stock_count,
        'revenue_growth': revenue_growth,
        'order_growth': order_growth,
        'recent_orders': recent_orders,
        'recent_activity': recent_activity,
    }
    
    return render(request, 'admin_dashboard/index.html', context)

# ==================== VENDOR DASHBOARD ====================

@login_required
def vendor_dashboard(request):
    """Advanced vendor dashboard with product management"""
    
    if not hasattr(request.user, 'vendor_profile') and request.user.user_type != 'vendor':
        return render(request, 'dashboard/access_denied.html', {
            'message': 'You are not registered as a vendor. Please become a vendor first.'
        })
    
    try:
        vendor_profile = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return render(request, 'dashboard/access_denied.html', {
            'message': 'Your vendor profile is not set up. Please contact support.'
        })

    if request.method == 'POST':
        action = request.POST.get('dashboard_action')
        if action == 'profile_settings':
            editable = [
                'store_name', 'company_name', 'vendor_type', 'country', 'address_line_1', 'city', 'state', 'description',
                'business_address', 'manufacturer_address', 'warehouse_address',
                'pickup_address', 'pickup_phone', 'support_email', 'support_phone', 'website',
                'preferred_language', 'preferred_currency',
                'store_slogan', 'storefront_accent_color', 'store_video_url', 'store_gallery_notes',
                'featured_categories', 'featured_products_note', 'business_hours',
                'return_policy', 'warranty_note', 'delivery_note', 'business_phone', 'whatsapp_number',
            ]
            for field in editable:
                if field in request.POST:
                    value = request.POST.get(field, '').strip()
                    if field == 'vendor_type' and value not in dict(VendorProfile.VENDOR_TYPE_CHOICES):
                        continue
                    if field == 'preferred_language' and value not in ['english', 'french', 'arabic', 'chinese', 'spanish']:
                        continue
                    if field == 'preferred_currency':
                        value = value.upper()
                        if value not in ['NGN', 'USD', 'GBP', 'EUR', 'CNY', 'CAD']:
                            continue
                    if field == 'storefront_accent_color':
                        if not (value.startswith('#') and len(value) in (4, 7)):
                            value = vendor_profile.storefront_accent
                    setattr(vendor_profile, field, value)
            if request.FILES.get('store_logo'):
                vendor_profile.store_logo = request.FILES['store_logo']
            if request.FILES.get('store_banner'):
                vendor_profile.store_banner = request.FILES['store_banner']
            vendor_profile.save()
            messages.success(request, 'Vendor profile and preferences updated.')
            return redirect('dashboard:vendor_home')
        if action == 'change_password':
            current = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            if not request.user.check_password(current):
                messages.error(request, 'Current password is incorrect.')
            elif not new_password or new_password != confirm_password:
                messages.error(request, 'New password and confirmation do not match.')
            else:
                try:
                    validate_password(new_password, request.user)
                except ValidationError as error:
                    messages.error(request, ' '.join(error.messages))
                else:
                    request.user.set_password(new_password)
                    request.user.save(update_fields=['password'])
                    update_session_auth_hash(request, request.user)
                    email_sent = send_vendor_password_changed_email(request.user)
                    Notification.send(
                        user=request.user,
                        notification_type='security',
                        title='Vendor security updated',
                        message='Your Arolana vendor password/PIN was changed successfully. Contact support immediately if you did not make this change.',
                        link='/dashboard/vendor/',
                        metadata={'event': 'vendor_password_changed'},
                        priority=3,
                    )
                    if email_sent:
                        messages.success(
                            request,
                            f'Password/PIN changed successfully. A security confirmation email was sent to {request.user.email}.',
                        )
                    else:
                        messages.success(
                            request,
                            'Password/PIN changed successfully. Your security notification was saved, but the email provider could not confirm delivery.',
                        )
                    return redirect('dashboard:vendor_home')
    
    all_products = Product.objects.filter(vendor=request.user).select_related('category', 'brand').prefetch_related('variants', 'images')
    products = all_products.filter(is_active=True, approval_status='approved')
    vendor_order_filter = Q(items__product__vendor=request.user) | Q(items__variant__product__vendor=request.user)
    vendor_item_filter = Q(product__vendor=request.user) | Q(variant__product__vendor=request.user)
    order_items = OrderItem.objects.filter(vendor_item_filter)
    orders = Order.objects.filter(vendor_order_filter).distinct().order_by('-created_at')
    
    total_orders = orders.count()
    total_sales = order_items.filter(order__status='delivered').aggregate(total=Sum('subtotal'))['total'] or 0
    
    reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True)
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
    low_stock = products.filter(stock_quantity__lte=5)
    
    top_products = products.annotate(
        total_sold=Sum('orderitem__quantity')
    ).order_by('-total_sold')[:5]
    
    categories = vendor_selectable_categories()
    brands = Brand.objects.filter(is_active=True)
    recent_orders = orders[:10]
    recent_reviews = reviews.order_by('-created_at')[:5]
    
    # ========== APPROVAL COUNTS ==========
    pending_count = all_products.filter(approval_status='pending').count()
    approved_count = all_products.filter(approval_status='approved').count()
    rejected_count = all_products.filter(approval_status='rejected').count()
    changes_required_count = all_products.filter(approval_status='requires_changes').count()
    
    # Get notifications for this vendor
    vendor_notifications_qs = VendorNotification.objects.filter(vendor=request.user)
    notification_count = vendor_notifications_qs.count()
    unread_notification_count = vendor_notifications_qs.filter(is_read=False).count()
    notifications_list = vendor_notifications_qs.order_by('-created_at')[:10]
    
    # Convert notifications to the format expected by template
    notifications = []
    for notif in notifications_list:
        notifications.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'notification_type': notif.notification_type,
            'action_url': notif.action_url,
            'created_at': notif.created_at
        })
    
    # Get unread message count
    unread_messages_count = _vendor_unread_admin_count(request.user)
    pickup_report_count = (
        DeliveryRequest.objects
        .filter(
            Q(order__items__product__vendor=request.user) | Q(order__items__variant__product__vendor=request.user),
            status__in=[
                DeliveryRequest.STATUS_PICKED_UP,
                DeliveryRequest.STATUS_IN_TRANSIT,
                DeliveryRequest.STATUS_ARRIVED_CUSTOMER,
                DeliveryRequest.STATUS_DELIVERED,
            ],
        )
        .distinct()
        .count()
    )
    robot_tasks = (
        OrderRobotVendorTask.objects
        .filter(vendor=request.user)
        .select_related('process__order', 'process__live_delivery')
        .order_by('-created_at')[:5]
    )
    
    # Monthly sales data for chart
    monthly_sales = []
    today = timezone.now().date()
    for i in range(6):
        month_start = today.replace(day=1) - timedelta(days=30 * i)
        month_sales = order_items.filter(
            order__status='delivered',
            order__created_at__month=month_start.month
        ).aggregate(total=Sum('subtotal'))['total'] or 0
        monthly_sales.append({
            'month': month_start.strftime('%b'),
            'sales': float(month_sales)
        })
    monthly_sales.reverse()
    
    subscription_context = _vendor_subscription_context(request.user)
    performance_context = _vendor_performance_context(request.user, vendor_profile)
    chat_context = _vendor_customer_chat_stats(request.user)

    context = {
        'vendor_profile': vendor_profile,
        'total_products': products.count(),
        'current_product_count': all_products.exclude(approval_status='rejected').count(),
        'total_orders': total_orders,
        'total_sales': total_sales,
        'low_stock': low_stock,
        'low_stock_count': low_stock.count(),
        'top_products': top_products,
        'avg_rating': round(avg_rating, 1),
        'total_reviews': reviews.count(),
        'recent_orders': recent_orders,
        'recent_reviews': recent_reviews,
        'categories': categories,
        'brands': brands,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'changes_required_count': changes_required_count,
        'notifications': notifications,
        'notification_count': notification_count,
        'unread_notification_count': unread_notification_count,
        'unread_count': unread_messages_count,
        'pickup_report_count': pickup_report_count,
        'monthly_sales': monthly_sales,
        'robot_tasks': robot_tasks,
        'robot_pending_count': OrderRobotVendorTask.objects.filter(vendor=request.user, status=OrderRobotVendorTask.STATUS_PENDING).count(),
    }
    context.update(subscription_context)
    context.update(performance_context)
    context.update(chat_context)
    return render(request, 'dashboard/vendor_dashboard.html', context)


@login_required
def vendor_pickup_location(request):
    if not hasattr(request.user, 'vendor_profile') and request.user.user_type != 'vendor':
        return render(request, 'dashboard/access_denied.html', {
            'message': 'You are not registered as a vendor. Please become a vendor first.'
        })

    try:
        vendor_profile = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return render(request, 'dashboard/access_denied.html', {
            'message': 'Your vendor profile is not set up. Please contact support.'
        })

    if request.method == 'POST':
        pickup_address = request.POST.get('pickup_address', '').strip()
        pickup_latitude = _decimal_or_none(request.POST.get('pickup_latitude'))
        pickup_longitude = _decimal_or_none(request.POST.get('pickup_longitude'))
        if not pickup_address or pickup_latitude is None or pickup_longitude is None:
            messages.error(request, 'Add an exact pickup address and set the map pin so riders can locate you.')
        else:
            vendor_profile.pickup_contact_name = request.POST.get('pickup_contact_name', '').strip()
            vendor_profile.pickup_phone = request.POST.get('pickup_phone', '').strip()
            vendor_profile.pickup_address = pickup_address
            vendor_profile.pickup_latitude = pickup_latitude
            vendor_profile.pickup_longitude = pickup_longitude
            vendor_profile.save(update_fields=[
                'pickup_contact_name',
                'pickup_phone',
                'pickup_address',
                'pickup_latitude',
                'pickup_longitude',
                'updated_at',
            ])
            messages.success(request, 'Pickup location saved. Delivery fees and rider assignment will now use this map pin.')
            return redirect('dashboard:vendor_pickup_location')

    context = {
        'vendor_profile': vendor_profile,
        'unread_count': _vendor_unread_admin_count(request.user),
    }
    context.update(_vendor_subscription_context(request.user))
    context.update(_vendor_customer_chat_stats(request.user))
    return render(request, 'dashboard/vendor_pickup_location.html', context)


@login_required
def vendor_order_robot_tasks(request):
    if not hasattr(request.user, 'vendor_profile') and request.user.user_type != 'vendor':
        return render(request, 'dashboard/access_denied.html', {
            'message': 'You are not registered as a vendor. Please become a vendor first.'
        })

    status = request.GET.get('status', '')
    tasks = (
        OrderRobotVendorTask.objects
        .filter(vendor=request.user)
        .select_related('process__order', 'process__legacy_delivery', 'process__live_delivery')
        .prefetch_related('process__order__items__product')
        .order_by('-created_at')
    )
    if status in dict(OrderRobotVendorTask.STATUS_CHOICES):
        tasks = tasks.filter(status=status)

    page = request.GET.get('page', 1)
    tasks_page = get_paginated_items(tasks, page, 12)
    context = {
        'tasks': tasks_page,
        'current_status': status,
        'status_choices': OrderRobotVendorTask.STATUS_CHOICES,
        'pending_count': OrderRobotVendorTask.objects.filter(vendor=request.user, status=OrderRobotVendorTask.STATUS_PENDING).count(),
        'unread_count': _vendor_unread_admin_count(request.user),
    }
    context.update(_vendor_subscription_context(request.user))
    context.update(_vendor_customer_chat_stats(request.user))
    return render(request, 'dashboard/vendor_order_robot_tasks.html', context)


@login_required
def vendor_order_robot_task_action(request, task_id, action):
    task = get_object_or_404(
        OrderRobotVendorTask.objects.select_related('process__order'),
        id=task_id,
        vendor=request.user,
    )
    if request.method != 'POST':
        return redirect('dashboard:vendor_order_robot_tasks')

    note = request.POST.get('note', '').strip()
    if action == 'confirm':
        vendor_mark_confirmed(task, actor=request.user, note=note or 'Vendor confirmed stock and order availability.')
        messages.success(request, 'Order confirmed. Arolana Order Robot has been updated.')
    elif action == 'ready':
        vendor_mark_confirmed(task, ready=True, actor=request.user, note=note or 'Vendor marked order ready for pickup.')
        messages.success(request, 'Order marked ready for pickup. Rider/admin delivery flow can continue.')
    elif action == 'reject':
        vendor_mark_rejected(task, actor=request.user, note=note or 'Vendor cannot fulfill this order.')
        messages.warning(request, 'Order escalated to Arolana admin for help.')
    else:
        messages.error(request, 'Unknown robot action.')
    return redirect('dashboard:vendor_order_robot_tasks')

def dashboard_home(request):
    """Dashboard home redirect"""
    if request.user.is_authenticated:
        if request.user.user_type == 'vendor' or hasattr(request.user, 'vendor_profile'):
            return vendor_dashboard(request)
        elif request.user.is_staff or request.user.user_type == 'super_admin':
            return admin_dashboard_index(request)
    return render(request, 'dashboard/home.html')

# ==================== VENDOR PRODUCT MANAGEMENT ====================

@login_required
def vendor_products(request):
    """Vendor product management with filtering"""
    products = Product.objects.filter(vendor=request.user).select_related('category', 'brand').order_by('-created_at')
    
    category_slug = request.GET.get('category')
    if category_slug:
        products = products.filter(category__slug=category_slug)
    
    status = request.GET.get('status')
    if status in {'pending', 'approved', 'requires_changes', 'rejected'}:
        products = products.filter(approval_status=status)
    elif status == 'active':
        products = products.filter(is_active=True, approval_status='approved')
    elif status == 'inactive':
        products = products.filter(is_active=False)
    elif status == 'low_stock':
        products = products.filter(stock_quantity__lte=5, is_active=True, approval_status='approved')
    elif status == 'out_of_stock':
        products = products.filter(stock_quantity=0, is_active=True, approval_status='approved')
    
    search_query = request.GET.get('q')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query)
            | Q(sku__icontains=search_query)
            | Q(manufacturer_sku__icontains=search_query)
        )
    
    sort_by = request.GET.get('sort', '-created_at')
    sort_mapping = {
        'newest': '-created_at',
        'oldest': 'created_at',
        'price_high': '-price',
        'price_low': 'price',
        'name_asc': 'name',
        'name_desc': '-name',
        'stock_high': '-stock_quantity',
        'stock_low': 'stock_quantity',
    }
    products = products.order_by(sort_mapping.get(sort_by, '-created_at'))
    
    page = request.GET.get('page', 1)
    products_page = get_paginated_items(products, page, 20)
    
    categories = vendor_selectable_categories()
    
    # Get approval counts for sidebar
    pending_count = Product.objects.filter(vendor=request.user, approval_status='pending').count()
    approved_count = Product.objects.filter(vendor=request.user, approval_status='approved').count()
    rejected_count = Product.objects.filter(vendor=request.user, approval_status='rejected').count()
    changes_required_count = Product.objects.filter(vendor=request.user, approval_status='requires_changes').count()
    
    context = {
        'products': products_page,
        'categories': categories,
        'current_category': category_slug,
        'current_status': status,
        'search_query': search_query,
        'current_sort': sort_by,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'changes_required_count': changes_required_count,
        'unread_count': _vendor_unread_admin_count(request.user),
        **_vendor_subscription_context(request.user),
        **_vendor_customer_chat_stats(request.user),
    }
    return render(request, 'dashboard/vendor_products.html', context)

@login_required
def vendor_add_product(request):
    """Vendor add product with full features including variants, images, videos"""
    
    if not hasattr(request.user, 'vendor_profile') and request.user.user_type != 'vendor':
        messages.error(request, 'You are not authorized as a vendor.')
        return redirect('dashboard:vendor_home')

    kyc_redirect = require_verified_kyc(request)
    if kyc_redirect:
        return kyc_redirect

    subscription_limits = user_subscription_limits(request.user)
    current_product_count = Product.objects.filter(vendor=request.user).exclude(
        approval_status__in=['rejected', 'draft']
    ).count()
    current_featured_count = Product.objects.filter(vendor=request.user, is_featured=True).exclude(approval_status='rejected').count()
    
    if request.method == 'POST':
        try:
            max_products = subscription_limits['max_products']
            product_limit_reached = max_products != -1 and current_product_count >= max_products

            # Get form data
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '')
            specifications = request.POST.get('specifications', '')
            price = request.POST.get('price', '')
            compare_price = request.POST.get('compare_price')
            stock_quantity = request.POST.get('stock_quantity', 0)
            sku = request.POST.get('sku', '')
            manufacturer_sku = request.POST.get('manufacturer_sku', '').strip()
            condition = request.POST.get('condition') or Product.CONDITION_BRAND_NEW
            category_id = request.POST.get('category')
            brand_id = request.POST.get('brand')
            is_featured = request.POST.get('is_featured') == 'on'
            is_active = request.POST.get('is_active') == 'on'
            meta_title = request.POST.get('meta_title', '')
            meta_description = request.POST.get('meta_description', '')
            
            # Video
            video_type = request.POST.get('video_type')
            video_url = request.POST.get('youtube_url')
            
            # Validate
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('dashboard:vendor_add_product')
            
            price_amount = Decimal(str(price or '0'))
            compare_price_amount = Decimal(str(compare_price)) if compare_price else None
            if price_amount <= 0:
                messages.error(request, 'Valid price is required.')
                return redirect('dashboard:vendor_add_product')
            
            if not category_id:
                messages.error(request, 'Category is required.')
                return redirect('dashboard:vendor_add_product')

            if condition not in dict(Product.PRODUCT_CONDITION_CHOICES):
                condition = Product.CONDITION_BRAND_NEW

            upload_policy_results = _inspect_vendor_product_uploads(request)
            
            # Generate SKU if not provided
            if not sku:
                sku = f"VND-{request.user.id}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"

            max_featured = subscription_limits['featured_products']
            if is_featured and max_featured != -1 and current_featured_count >= max_featured:
                is_featured = False
                messages.warning(request, 'Featured product limit reached for your current plan. The product was saved without featured placement.')
            
            with transaction.atomic():
                product = Product.objects.create(
                    name=name,
                    description=description,
                    specifications=specifications,
                    price=price_amount,
                    compare_price=compare_price_amount,
                    stock_quantity=int(stock_quantity or 0),
                    sku=sku,
                    manufacturer_sku=manufacturer_sku,
                    condition=condition,
                    category_id=category_id,
                    brand_id=brand_id if brand_id else None,
                    vendor=request.user,
                    is_featured=is_featured,
                    is_active=False,
                    meta_title=meta_title,
                    meta_description=meta_description,
                    approval_status='draft' if product_limit_reached else 'pending',
                )

                if video_type and video_type != 'none' and not subscription_limits.get('can_upload_video'):
                    messages.warning(request, 'Your current subscription does not allow product video upload. Upgrade your plan to add videos.')
                elif video_type == 'youtube' and video_url:
                    product.video_type = 'youtube'
                    product.video_url = video_url
                    product.save(update_fields=['video_type', 'video_url'])
                elif video_type == 'local' and request.FILES.get('local_video'):
                    product.video_type = 'local'
                    product.local_video = request.FILES['local_video']
                    product.save(update_fields=['video_type', 'local_video'])

                main_image = request.FILES.get('main_image')
                if main_image:
                    product.main_image = main_image
                    product.save(update_fields=['main_image'])
                    _vendor_image_review_notice(request, product, 'main_image', emit_message=False)

                manual_pdf = request.FILES.get('manual_pdf')
                if manual_pdf:
                    if subscription_limits.get('can_upload_pdf'):
                        product.manual_pdf = manual_pdf
                        product.save(update_fields=['manual_pdf'])
                    else:
                        messages.warning(request, 'Your current subscription does not allow PDF brochure/manual upload. Upgrade your plan to add PDF files.')

                additional_images = request.FILES.getlist('additional_images')
                max_images = subscription_limits['max_images_per_product']
                image_limit = len(additional_images) if max_images == -1 else max_images
                for order, img in enumerate(additional_images[:image_limit]):
                    product_image = ProductImage.objects.create(product=product, image=img, order=order)
                    _vendor_image_review_notice(request, product_image, 'image', emit_message=False)

                max_variants = subscription_limits['max_variants_per_product']
                variant_indexes = request.POST.getlist('variant_index[]')
                if not variant_indexes:
                    variant_indexes = [str(i) for i in range(len(request.POST.getlist('variant_type[]')))]
                variant_limit = len(variant_indexes) if max_variants == -1 else max_variants

                for raw_index in variant_indexes[:variant_limit]:
                    variant_type = request.POST.get(f'variant_type_{raw_index}')
                    variant_value = request.POST.get(f'variant_value_{raw_index}', '').strip()
                    if not variant_type:
                        legacy_types = request.POST.getlist('variant_type[]')
                        try:
                            legacy_index = int(raw_index)
                            variant_type = legacy_types[legacy_index] if legacy_index < len(legacy_types) else ''
                            variant_value = request.POST.getlist('variant_value[]')[legacy_index]
                        except Exception:
                            variant_type = ''
                    if variant_type and variant_value:
                        variant_name = request.POST.get(f'variant_name_{raw_index}', '').strip() or f"{variant_type.title()}: {variant_value}"
                        variant_price = request.POST.get(f'variant_price_{raw_index}', '0') or '0'
                        variant_stock = request.POST.get(f'variant_stock_{raw_index}', '0') or '0'
                        variant_color = request.POST.get(f'variant_color_code_{raw_index}', '').strip()
                        variant_sku = request.POST.get(f'variant_sku_{raw_index}', '').strip()
                        variant = ProductVariant.objects.create(
                        product=product,
                        variant_type=variant_type,
                        name=variant_name,
                        value=variant_value,
                        sku=variant_sku,
                        price_adjustment=Decimal(str(variant_price)),
                        stock_quantity=int(variant_stock),
                        color_code=variant_color,
                        is_active=True
                    )
                        variant_images = request.FILES.getlist(f'variant_images_{raw_index}')
                        for image_order, image_file in enumerate(variant_images):
                            if image_order == 0:
                                variant.image = image_file
                                variant.save(update_fields=['image'])
                                _vendor_image_review_notice(request, variant, 'image', emit_message=False)
                            variant_image = ProductVariantImage.objects.create(
                                variant=variant,
                                image=image_file,
                                order=image_order,
                                is_main=image_order == 0,
                                alt_text=f"{product.name} {variant.value}",
                            )
                            _vendor_image_review_notice(request, variant_image, 'image', emit_message=False)

                if max_variants != -1 and len(variant_indexes) > max_variants:
                    messages.warning(request, f'Your plan allows {max_variants} variants per product. Extra variants were not saved.')
            
            same_vendor_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "same_vendor_reuse"
            )
            near_duplicate_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "near_duplicate_cross_vendor"
            )
            if same_vendor_count:
                noun = "image is" if same_vendor_count == 1 else "images are"
                messages.info(
                    request,
                    f"{same_vendor_count} {noun} already used by this same vendor. Reuse allowed.",
                )
            if near_duplicate_count:
                messages.warning(
                    request,
                    f"{near_duplicate_count} image(s) look similar to media used by another vendor. "
                    "The product is inactive and has been submitted for review.",
                )
            if product_limit_reached:
                messages.warning(
                    request,
                    f'Product "{product.name}" was saved as a draft. Your current plan allows '
                    f'{max_products} product(s), and you have used {current_product_count}/{max_products}. '
                    'Upgrade your plan before publishing this product.',
                )
                return redirect('dashboard:vendor_product_detail', product_id=product.id)
            messages.success(request, f'Product "{product.name}" was saved and submitted for approval.')
            return redirect('dashboard:vendor_products')
            
        except Exception as e:
            messages.error(request, f'Error adding product: {str(e)}')
            return redirect('dashboard:vendor_add_product')
    
    categories = vendor_selectable_categories()
    brands = Brand.objects.filter(is_active=True)
    
    context = {
        'categories': categories,
        'brands': brands,
        'condition_choices': Product.PRODUCT_CONDITION_CHOICES,
        'subscription_limits': subscription_limits,
        'current_product_count': current_product_count,
        'current_featured_count': current_featured_count,
        'product_limit_reached': (
            subscription_limits['max_products'] != -1
            and current_product_count >= subscription_limits['max_products']
        ),
        **_vendor_subscription_context(request.user),
        **_vendor_customer_chat_stats(request.user),
        'unread_count': _vendor_unread_admin_count(request.user),
    }
    return render(request, 'dashboard/vendor_add_product.html', context)

@login_required
def vendor_product_detail(request, product_id):
    """Vendor product detail with full editing capabilities"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    
    if request.method == 'POST':
        kyc_redirect = require_verified_kyc(request)
        if kyc_redirect:
            return kyc_redirect
        subscription_limits = user_subscription_limits(request.user)

        try:
            upload_policy_results = _inspect_vendor_product_uploads(request)
            product.name = request.POST.get('name', product.name)
            product.description = request.POST.get('description', product.description)
            product.specifications = request.POST.get('specifications', product.specifications)
            product.price = Decimal(str(request.POST.get('price', product.price)))
            product.compare_price = Decimal(str(request.POST.get('compare_price'))) if request.POST.get('compare_price') else None
            product.stock_quantity = int(request.POST.get('stock_quantity', product.stock_quantity))
            product.sku = request.POST.get('sku', product.sku)
            product.manufacturer_sku = request.POST.get('manufacturer_sku', '').strip()
            product.condition = request.POST.get('condition') or Product.CONDITION_BRAND_NEW
            if product.condition not in dict(Product.PRODUCT_CONDITION_CHOICES):
                product.condition = Product.CONDITION_BRAND_NEW
            product.category_id = request.POST.get('category', product.category_id)
            product.brand_id = request.POST.get('brand') if request.POST.get('brand') else None
            product.is_featured = request.POST.get('is_featured') == 'on'
            product.is_active = request.POST.get('is_active') == 'on'
            product.meta_title = request.POST.get('meta_title', '')
            product.meta_description = request.POST.get('meta_description', '')
            
            main_image = request.FILES.get('main_image')
            if main_image:
                product.main_image = main_image

            manual_pdf = request.FILES.get('manual_pdf')
            if manual_pdf:
                if subscription_limits.get('can_upload_pdf'):
                    product.manual_pdf = manual_pdf
                else:
                    messages.warning(request, 'Your current subscription does not allow PDF brochure/manual upload. Upgrade your plan to add PDF files.')

            video_type = request.POST.get('video_type')
            if video_type and video_type != 'none' and not subscription_limits.get('can_upload_video'):
                messages.warning(request, 'Your current subscription does not allow product video upload. Upgrade your plan to add videos.')
                product.video_type = ''
                product.video_url = ''
            else:
                product.video_type = video_type or ''
                product.video_url = request.POST.get('youtube_url', '') if video_type == 'youtube' else ''
                if video_type == 'local' and request.FILES.get('local_video'):
                    product.local_video = request.FILES['local_video']

            if any(item.get("pending_review") for item in upload_policy_results):
                product.approval_status = "pending"
                product.is_active = False
                product.resubmitted_at = timezone.now()
            
            product.save()
            if main_image:
                _vendor_image_review_notice(request, product, 'main_image')

            additional_images = request.FILES.getlist('additional_images')
            if additional_images:
                max_images = subscription_limits['max_images_per_product']
                existing_images = product.images.count()
                remaining = len(additional_images) if max_images == -1 else max(0, max_images - existing_images)
                for order, img in enumerate(additional_images[:remaining], start=existing_images):
                    product_image = ProductImage.objects.create(product=product, image=img, order=order)
                    _vendor_image_review_notice(request, product_image, 'image')
                if max_images != -1 and len(additional_images) > remaining:
                    messages.warning(request, f'Only {remaining} gallery image(s) were added because of your plan limit.')

            same_vendor_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "same_vendor_reuse"
            )
            near_duplicate_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "near_duplicate_cross_vendor"
            )
            if same_vendor_count:
                noun = "image is" if same_vendor_count == 1 else "images are"
                messages.info(
                    request,
                    f"{same_vendor_count} {noun} already used by this same vendor. Reuse allowed.",
                )
            if near_duplicate_count:
                messages.warning(
                    request,
                    f"{near_duplicate_count} image(s) were submitted for duplicate review. "
                    "The product is inactive until admin review is complete.",
                )

            messages.success(request, 'Product updated successfully!')
            return redirect('dashboard:vendor_products')
            
        except Exception as e:
            messages.error(request, f'Error updating product: {str(e)}')
    
    categories = vendor_selectable_categories()
    brands = Brand.objects.filter(is_active=True)
    product_images = product.images.all()
    variants = product.variants.filter(is_active=True)
    reviews = product.reviews.filter(is_active=True)
    
    context = {
        'product': product,
        'categories': categories,
        'brands': brands,
        'condition_choices': Product.PRODUCT_CONDITION_CHOICES,
        'product_images': product_images,
        'variants': variants,
        'reviews': reviews,
        'total_reviews': reviews.count(),
        'avg_rating': reviews.aggregate(avg=Avg('rating'))['avg'] or 0,
        'subscription_limits': user_subscription_limits(request.user),
        **_vendor_subscription_context(request.user),
        **_vendor_customer_chat_stats(request.user),
        'unread_count': _vendor_unread_admin_count(request.user),
    }
    return render(request, 'dashboard/vendor_product_detail.html', context)

@login_required
def vendor_product_variants(request, product_id):
    """Manage product variants via AJAX"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    
    if request.method == 'POST':
        if not seller_has_verified_kyc(request.user):
            return JsonResponse({'success': False, 'error': 'KYC verification is required before managing variants.'}, status=403)

        try:
            data = json.loads(request.body)
            action = data.get('action')
            
            if action == 'add':
                limits = user_subscription_limits(request.user)
                max_variants = limits['max_variants_per_product']
                if max_variants != -1 and product.variants.filter(is_active=True).count() >= max_variants:
                    return JsonResponse({'success': False, 'error': f'Your plan allows {max_variants} variants per product.'}, status=403)
                variant = ProductVariant.objects.create(
                    product=product,
                    variant_type=data.get('variant_type'),
                    name=data.get('name'),
                    value=data.get('value'),
                    sku=data.get('sku', ''),
                    price_adjustment=Decimal(str(data.get('price_adjustment', 0))),
                    stock_quantity=int(data.get('stock_quantity', 0)),
                    color_code=data.get('color_code', ''),
                    is_active=True
                )
                return JsonResponse({'success': True, 'variant_id': variant.id})
            
            elif action == 'update':
                variant = get_object_or_404(ProductVariant, id=data.get('variant_id'), product=product)
                variant.variant_type = data.get('variant_type', variant.variant_type)
                variant.name = data.get('name', variant.name)
                variant.value = data.get('value', variant.value)
                variant.price_adjustment = Decimal(str(data.get('price_adjustment', variant.price_adjustment)))
                variant.stock_quantity = int(data.get('stock_quantity', variant.stock_quantity))
                variant.sku = data.get('sku', variant.sku)
                variant.color_code = data.get('color_code', variant.color_code)
                variant.is_active = data.get('is_active', variant.is_active)
                variant.save()
                return JsonResponse({'success': True})
            
            elif action == 'delete':
                variant = get_object_or_404(ProductVariant, id=data.get('variant_id'), product=product)
                variant.delete()
                return JsonResponse({'success': True})
                
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    variants = product.variants.filter(is_active=True)
    return JsonResponse({
        'variants': [
            {
                'id': v.id,
                'variant_type': v.variant_type,
                'name': v.name,
                'value': v.value,
                'price_adjustment': float(v.price_adjustment),
                'stock_quantity': v.stock_quantity,
                'sku': v.sku,
                'color_code': v.color_code,
                'image': v.image.url if v.image else '',
            }
            for v in variants
        ]
    })

@login_required
def vendor_product_images(request, product_id):
    """Manage product images via AJAX"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    
    if request.method == 'POST':
        if not seller_has_verified_kyc(request.user):
            return JsonResponse({'success': False, 'error': 'KYC verification is required before uploading images.'}, status=403)

        try:
            images = request.FILES.getlist('images')
            upload_policy_results = [
                inspect_vendor_image_upload(image_file, request.user)
                for image_file in images
            ]
            blocked = next(
                (item for item in upload_policy_results if not item.get("allowed", True)),
                None,
            )
            if blocked:
                return JsonResponse({
                    "success": False,
                    "allowed": False,
                    "reason": blocked.get("status"),
                    "message": blocked.get("message"),
                    "duplicate_warning": blocked,
                }, status=409)
            duplicate_warnings = []
            for img in images:
                product_image = ProductImage.objects.create(product=product, image=img)
                warning = _vendor_image_review_payload(request.user, product_image, 'image')
                if warning:
                    duplicate_warnings.append(warning)
            if any(item.get("pending_review") for item in upload_policy_results):
                product.approval_status = "pending"
                product.is_active = False
                product.resubmitted_at = timezone.now()
                product.save(update_fields=[
                    "approval_status",
                    "is_active",
                    "resubmitted_at",
                    "updated_at",
                ])
            same_vendor_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "same_vendor_reuse"
            )
            near_duplicate_count = sum(
                1 for item in upload_policy_results
                if item.get("status") == "near_duplicate_cross_vendor"
            )
            return JsonResponse({
                'success': True,
                'count': len(images),
                'duplicate_warnings': duplicate_warnings,
                'same_vendor_reuse_count': same_vendor_count,
                'review_count': near_duplicate_count,
                'message': (
                    f'{near_duplicate_count} image(s) were submitted for Arolana duplicate review.'
                    if near_duplicate_count
                    else (
                        f'{same_vendor_count} image(s) are already used by this same vendor. Reuse allowed.'
                        if same_vendor_count
                        else 'Images uploaded successfully.'
                    )
                ),
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        try:
            data = json.loads(request.body)
            image_id = data.get('image_id')
            image = get_object_or_404(ProductImage, id=image_id, product=product)
            image.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    images = product.images.all()
    return JsonResponse({
        'images': [
            {
                'id': img.id,
                'url': img.image.url,
                'thumbnail': img.image.url,
            }
            for img in images
        ]
    })

@login_required
def vendor_product_reviews(request, product_id):
    """View product reviews"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    reviews = product.reviews.filter(is_active=True).order_by('-created_at')
    
    return render(request, 'dashboard/vendor_product_reviews.html', {
        'product': product,
        'reviews': reviews,
        'unread_count': _vendor_unread_admin_count(request.user),
        **_vendor_subscription_context(request.user),
        **_vendor_customer_chat_stats(request.user),
    })


@login_required
def vendor_reviews(request):
    """All reviews received by the vendor across products."""
    reviews = ProductReview.objects.filter(
        product__vendor=request.user,
        is_active=True
    ).select_related('product', 'user').order_by('-created_at')

    rating = request.GET.get('rating')
    if rating in {'1', '2', '3', '4', '5'}:
        reviews = reviews.filter(rating=int(rating))

    product_id = request.GET.get('product')
    if product_id:
        reviews = reviews.filter(product_id=product_id)

    all_reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True)
    rating_counts = {item['rating']: item['count'] for item in all_reviews.values('rating').annotate(count=Count('id'))}
    products = Product.objects.filter(vendor=request.user).only('id', 'name').order_by('name')
    reviews_page = get_paginated_items(reviews, request.GET.get('page', 1), 20)

    context = {
        'reviews': reviews_page,
        'products': products,
        'current_rating': rating,
        'current_product': product_id,
        'avg_rating': all_reviews.aggregate(avg=Avg('rating'))['avg'] or 0,
        'total_reviews': all_reviews.count(),
        'rating_counts': rating_counts,
        'unread_count': _vendor_unread_admin_count(request.user),
        **_vendor_subscription_context(request.user),
        **_vendor_customer_chat_stats(request.user),
    }
    return render(request, 'dashboard/vendor_reviews.html', context)

@login_required
def vendor_product_questions(request, product_id):
    """View and answer product questions"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    questions = product.questions.filter().order_by('-created_at')
    
    if request.method == 'POST':
        qna_id = request.POST.get('qna_id')
        answer = request.POST.get('answer', '').strip()
        
        if qna_id and answer:
            qna = get_object_or_404(ProductQuestion, id=qna_id, product=product)
            qna.answer = answer
            qna.answered_by = request.user
            qna.answered_at = timezone.now()
            qna.save()
            messages.success(request, 'Answer posted successfully!')
        
        return redirect('dashboard:vendor_product_questions', product_id=product_id)
    
    return render(request, 'dashboard/vendor_product_questions.html', {
        'product': product,
        'questions': questions,
    })

# ==================== VENDOR ORDER MANAGEMENT ====================

@login_required
def vendor_orders(request):
    """Vendor order management"""
    order_items = OrderItem.objects.filter(product__vendor=request.user)
    orders = Order.objects.filter(items__in=order_items).distinct().order_by('-created_at')
    
    status = request.GET.get('status')
    if status:
        orders = orders.filter(status=status)
    
    search = request.GET.get('search')
    if search:
        orders = orders.filter(id__icontains=search)
    
    paginator = Paginator(orders, 20)
    page = request.GET.get('page', 1)
    orders_page = get_paginated_items(orders, page, 20)
    
    # Get unread message count for sidebar
    unread_count = VendorAdminMessage.objects.filter(
        recipient=request.user,
        status='unread',
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    ).count()
    
    context = {
        'orders': orders_page,
        'current_status': status,
        'search_query': search,
        'unread_count': unread_count,
    }
    return render(request, 'dashboard/vendor_orders.html', context)

@login_required
def vendor_order_detail(request, order_id):
    """Vendor order detail view"""
    order = get_object_or_404(
        Order.objects.prefetch_related("items__product", "items__variant__product", "live_delivery_requests__rider__user"),
        id=order_id,
    )
    vendor_items = order.items.filter(
        Q(product__vendor=request.user) | Q(variant__product__vendor=request.user)
    ).select_related("product", "variant", "variant__product")
    if not vendor_items.exists():
        messages.error(request, "You do not have access to this order.")
        return redirect("dashboard:vendor_orders")
    delivery = order.live_delivery_requests.select_related("rider", "rider__user").order_by("-created_at").first()
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status and vendor_items.exists():
            order.status = new_status
            order.save()
            messages.success(request, f'Order status updated to {new_status}')
            return redirect('dashboard:vendor_order_detail', order_id=order_id)
    
    context = {
        'order': order,
        'vendor_items': vendor_items,
        'delivery': delivery,
    }
    return render(request, 'dashboard/vendor_order_detail.html', context)

@login_required
def vendor_update_order_status(request, order_id):
    """Update order status via AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_status = data.get('status')
            order = get_object_or_404(Order, id=order_id)
            
            if order.items.filter(product__vendor=request.user).exists():
                order.status = new_status
                order.save()
                return JsonResponse({'success': True, 'status': new_status})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False})

# ==================== VENDOR ANALYTICS ====================

@login_required
def vendor_analytics(request):
    """Vendor analytics dashboard"""
    products = Product.objects.filter(vendor=request.user, is_active=True, approval_status="approved")
    all_products = Product.objects.filter(vendor=request.user)
    order_items = OrderItem.objects.filter(product__vendor=request.user)
    orders = Order.objects.filter(items__in=order_items).distinct()
    
    delivered_items = order_items.filter(order__status='delivered')
    total_revenue = delivered_items.aggregate(total=Sum('subtotal'))['total'] or 0
    total_units_sold = delivered_items.aggregate(total=Sum('quantity'))['total'] or 0
    total_views = all_products.aggregate(total=Sum('views_count'))['total'] or 0
    average_order_value = (total_revenue / orders.filter(status='delivered').count()) if orders.filter(status='delivered').exists() else 0
    reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True)
    top_products = all_products.annotate(total_sold=Sum('orderitem__quantity')).order_by('-total_sold')[:10]
    order_status_counts = {
        status: orders.filter(status=status).count()
        for status, _label in Order.STATUS_CHOICES
    }
    
    today = timezone.now().date()
    sales_data = []
    for i in range(30):
        date = today - timedelta(days=i)
        daily_sales = order_items.filter(
            order__created_at__date=date,
            order__status='delivered'
        ).aggregate(total=Sum('subtotal'))['total'] or 0
        sales_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': float(daily_sales)
        })
    sales_data.reverse()
    
    context = {
        'total_products': products.count(),
        'total_orders': orders.count(),
        'total_revenue': total_revenue,
        'total_units_sold': total_units_sold,
        'total_views': total_views,
        'average_order_value': average_order_value,
        'total_reviews': reviews.count(),
        'avg_rating': reviews.aggregate(avg=Avg('rating'))['avg'] or 0,
        'top_products': top_products,
        'order_status_counts': order_status_counts,
        'sales_data': sales_data,
        'unread_count': _vendor_unread_admin_count(request.user),
        **_vendor_subscription_context(request.user),
        **_vendor_performance_context(request.user, getattr(request.user, 'vendor_profile', None)),
        **_vendor_customer_chat_stats(request.user),
    }
    return render(request, 'dashboard/vendor_analytics.html', context)

@login_required
def vendor_analytics_api(request):
    """API endpoint for vendor analytics data"""
    from django.db.models import Sum
    
    try:
        today = timezone.now().date()
        sales_data = []
        
        for i in range(30):
            date = today - timedelta(days=i)
            daily_sales = OrderItem.objects.filter(
                product__vendor=request.user,
                order__created_at__date=date,
                order__status='delivered'
            ).aggregate(total=Sum('subtotal'))['total'] or 0
            
            sales_data.append({
                'date': date.strftime('%Y-%m-%d'),
                'sales': float(daily_sales)
            })
        
        sales_data.reverse()
        
        return JsonResponse({
            'success': True,
            'sales_data': sales_data,
            'total_sales': sum(d['sales'] for d in sales_data)
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# ==================== VENDOR NOTIFICATIONS ====================

@login_required
def vendor_notifications_api(request):
    """API endpoint for vendor notifications"""
    
    try:
        order_items = OrderItem.objects.filter(product__vendor=request.user)
        new_orders = Order.objects.filter(items__in=order_items, status='pending').count()
        new_reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True).count()
        low_stock = Product.objects.filter(vendor=request.user, stock_quantity__lte=5, is_active=True, approval_status="approved").count()
        
        notifications = []
        if new_orders > 0:
            notifications.append({
                'type': 'order', 
                'count': new_orders, 
                'message': f'{new_orders} new order{"s" if new_orders != 1 else ""}',
                'icon': 'fa-shopping-cart'
            })
        if new_reviews > 0:
            notifications.append({
                'type': 'review', 
                'count': new_reviews, 
                'message': f'{new_reviews} new review{"s" if new_reviews != 1 else ""}',
                'icon': 'fa-star'
            })
        if low_stock > 0:
            notifications.append({
                'type': 'stock', 
                'count': low_stock, 
                'message': f'{low_stock} product{"s" if low_stock != 1 else ""} low on stock',
                'icon': 'fa-exclamation-triangle'
            })
        
        return JsonResponse({'notifications': notifications, 'total': len(notifications)})
    except Exception as e:
        return JsonResponse({'notifications': [], 'total': 0, 'error': str(e)})

# ==================== ADMIN API ENDPOINTS ====================

@staff_member_required
def admin_dashboard_stats(request):
    """Dashboard statistics page"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True, approval_status="approved").count()
    vendors_count = VendorProfile.objects.filter(is_verified=True).count()
    low_stock_count = Product.objects.filter(stock_quantity__lte=5, is_active=True, approval_status="approved").count()
    
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    recent_activity = AdminActivityLog.objects.select_related('admin').order_by('-created_at')[:20]
    
    context = {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'total_users': total_users,
        'total_products': total_products,
        'vendors_count': vendors_count,
        'low_stock_count': low_stock_count,
        'recent_orders': recent_orders,
        'recent_activity': recent_activity,
    }
    
    return render(request, 'admin_dashboard/stats.html', context)

@staff_member_required
def api_dashboard(request):
    """API endpoint for dashboard data"""
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True, approval_status="approved").count()
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    
    html = render_to_string('admin_dashboard/partials/dashboard.html', {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'total_users': total_users,
        'total_products': total_products,
        'recent_orders': recent_orders,
    })
    return JsonResponse({'html': html})

@staff_member_required
def api_products(request):
    products = Product.objects.filter(is_active=True, approval_status="approved")[:20]
    html = render_to_string('admin_dashboard/partials/products.html', {'products': products})
    return JsonResponse({'html': html})

@staff_member_required
def api_add_product(request):
    categories = Category.objects.filter(is_active=True)
    brands = Brand.objects.filter(is_active=True)
    html = render_to_string('admin_dashboard/partials/add_product.html', {
        'categories': categories,
        'brands': brands,
    })
    return JsonResponse({'html': html})

@staff_member_required
def api_orders(request):
    orders = Order.objects.all().order_by('-created_at')[:20]
    html = render_to_string('admin_dashboard/partials/orders.html', {'orders': orders})
    return JsonResponse({'html': html})

@staff_member_required
def api_users(request):
    users = User.objects.all().order_by('-date_joined')[:20]
    html = render_to_string('admin_dashboard/partials/users.html', {'users': users})
    return JsonResponse({'html': html})

@staff_member_required
def api_vendors(request):
    vendors = VendorProfile.objects.filter(is_active=True)[:20]
    html = render_to_string('admin_dashboard/partials/vendors.html', {'vendors': vendors})
    return JsonResponse({'html': html})

@staff_member_required
def dismiss_alert(request, alert_id):
    alert = get_object_or_404(SystemAlert, id=alert_id)
    alert.is_dismissed = True
    alert.save()
    return JsonResponse({'success': True})

@staff_member_required
def get_chart_data(request):
    days = int(request.GET.get('days', 30))
    today = timezone.now().date()
    
    sales_data = []
    for i in range(days):
        date = today - timedelta(days=i)
        daily_sales = Order.objects.filter(
            created_at__date=date,
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0
        sales_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': float(daily_sales)
        })
    
    return JsonResponse({'sales_data': sales_data})

@staff_member_required
def api_products_list(request):
    products = Product.objects.filter(is_active=True, approval_status="approved").order_by('-created_at')
    html = render_to_string('admin_dashboard/partials/products_list.html', {'products': products})
    return JsonResponse({'html': html})

@staff_member_required
def api_product_delete(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        product.is_active = False
        product.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def api_product_update(request, product_id):
    try:
        data = json.loads(request.body)
        product = get_object_or_404(Product, id=product_id)
        product.name = data.get('name', product.name)
        product.price = data.get('price', product.price)
        product.stock_quantity = data.get('stock_quantity', product.stock_quantity)
        if 'manufacturer_sku' in data:
            product.manufacturer_sku = data.get('manufacturer_sku', '').strip()
        product.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def api_product_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product = Product.objects.create(
                name=data.get('name'),
                price=data.get('price', 0),
                stock_quantity=data.get('stock_quantity', 0),
                sku=data.get('sku', f"SKU-{int(timezone.now().timestamp())}"),
                manufacturer_sku=data.get('manufacturer_sku', '').strip(),
                vendor=User.objects.filter(is_staff=True).first(),
                category=Category.objects.first(),
                is_active=True
            )
            return JsonResponse({'success': True, 'id': product.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False})

@staff_member_required
def api_users_list(request):
    users = User.objects.all().order_by('-date_joined')
    html = render_to_string('admin_dashboard/partials/users_list.html', {'users': users})
    return JsonResponse({'html': html})

@staff_member_required
def api_user_delete(request, user_id):
    try:
        user = get_object_or_404(User, id=user_id)
        user.is_active = False
        user.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def api_user_update(request, user_id):
    try:
        data = json.loads(request.body)
        user = get_object_or_404(User, id=user_id)
        user.username = data.get('username', user.username)
        user.email = data.get('email', user.email)
        user.user_type = data.get('user_type', user.user_type)
        user.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def api_orders_list(request):
    orders = Order.objects.all().order_by('-created_at')
    html = render_to_string('admin_dashboard/partials/orders_list.html', {'orders': orders})
    return JsonResponse({'html': html})

@staff_member_required
def api_order_update_status(request, order_id):
    try:
        data = json.loads(request.body)
        order = get_object_or_404(Order, id=order_id)
        order.status = data.get('status', order.status)
        order.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
def admin_product_approvals(request):
    """Admin view to approve/reject products"""
    from products.models import Product
    from django.core.mail import send_mail
    from django.conf import settings
    
    # Get all products pending approval
    pending_products = Product.objects.filter(approval_status='pending').order_by('-submitted_for_review_at')
    approved_products = Product.objects.filter(approval_status='approved').order_by('-approved_at')[:20]
    rejected_products = Product.objects.filter(approval_status='rejected').order_by('-updated_at')[:20]
    
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        try:
            product = Product.objects.get(id=product_id)
            
            if action == 'approve':
                product.approval_status = 'approved'
                product.approved_by = request.user
                product.approved_at = timezone.now()
                product.is_active = True
                product.save()
                
                # Send email notification to vendor
                if product.vendor and product.vendor.email:
                    send_mail(
                        subject=f'Product Approved: {product.name}',
                        message=f'''Dear Vendor,

Your product "{product.name}" has been approved and is now live on our marketplace!

{notes if notes else 'Thank you for your submission.'}

Best regards,
Arolana Team''',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[product.vendor.email],
                        fail_silently=True,
                    )
                
                messages.success(request, f'Product "{product.name}" has been approved.')
                
            elif action == 'reject':
                product.approval_status = 'rejected'
                product.approval_notes = notes
                product.is_active = False
                product.save()
                
                # Send rejection email with reason
                if product.vendor and product.vendor.email:
                    send_mail(
                        subject=f'Product Update Needed: {product.name}',
                        message=f'''Dear Vendor,

Your product "{product.name}" requires changes before it can be published.

Reason: {notes if notes else 'Please review the product details and resubmit.'}

Please make the necessary changes and resubmit for approval.

Best regards,
Arolana Team''',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[product.vendor.email],
                        fail_silently=True,
                    )
                
                messages.warning(request, f'Product "{product.name}" has been rejected.')
                
            elif action == 'requires_changes':
                product.approval_status = 'requires_changes'
                product.approval_notes = notes
                product.is_active = False
                product.save()
                
                # Send revision email
                if product.vendor and product.vendor.email:
                    send_mail(
                        subject=f'Product Changes Required: {product.name}',
                        message=f'''Dear Vendor,

Your product "{product.name}" requires some changes.

Required Changes:
{notes}

Please update your product and resubmit for approval.

Best regards,
Arolana Team''',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[product.vendor.email],
                        fail_silently=True,
                    )
                
                messages.info(request, f'Changes required for "{product.name}".')
                
            return redirect('dashboard:admin_product_approvals')
            
        except Product.DoesNotExist:
            messages.error(request, 'Product not found.')
            return redirect('dashboard:admin_product_approvals')
    
    # Get unread message count for sidebar
    unread_count = VendorAdminMessage.objects.filter(
        recipient=request.user,
        status='unread',
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    ).count()
    
    context = {
        'pending_products': pending_products,
        'approved_products': approved_products,
        'rejected_products': rejected_products,
        'pending_count': pending_products.count(),
        'approved_count': approved_products.count(),
        'rejected_count': rejected_products.count(),
        'unread_count': unread_count,
    }
    return render(request, 'dashboard/admin_product_approvals.html', context)


@staff_member_required
def admin_product_approval_detail(request, product_id):
    """View product details for approval"""
    from products.models import Product
    
    product = get_object_or_404(Product, id=product_id)
    
    context = {
        'product': product,
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/admin_product_approval_detail.html', context)


@login_required
def vendor_resubmit_product(request, product_id):
    """Vendor resubmit product for approval after changes"""
    from products.models import Product
    
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    
    if product.approval_status in ['rejected', 'requires_changes']:
        product.approval_status = 'pending'
        product.approval_notes = ''
        product.save()
        messages.success(request, f'Product "{product.name}" has been resubmitted for approval.')
    else:
        messages.error(request, 'This product cannot be resubmitted.')
    
    return redirect('dashboard:vendor_products')

# ==================== ADMIN-VENDOR MESSAGING SYSTEM ====================

@staff_member_required
def admin_messages(request):
    """Admin message dashboard - view all conversations with vendors"""
    search_query = request.GET.get('search', '')
    
    # Get all conversations with vendors
    conversations_raw = VendorAdminMessage.objects.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).exclude(
        Q(sender=request.user, is_deleted_by_sender=True) |
        Q(recipient=request.user, is_deleted_by_recipient=True)
    )
    
    # Build vendor list with latest message time
    vendors_data = {}
    
    for msg in conversations_raw:
        vendor = msg.sender if msg.sender != request.user else msg.recipient
        if vendor.user_type != 'vendor':
            continue
            
        if vendor.id not in vendors_data:
            vendors_data[vendor.id] = {
                'vendor': vendor,
                'last_message_time': msg.created_at,
                'last_message_preview': msg.message[:50] if msg.message else '',
                'unread_count': 0,
                'last_message_sender': msg.sender
            }
        else:
            if msg.created_at > vendors_data[vendor.id]['last_message_time']:
                vendors_data[vendor.id]['last_message_time'] = msg.created_at
                vendors_data[vendor.id]['last_message_preview'] = msg.message[:50] if msg.message else ''
                vendors_data[vendor.id]['last_message_sender'] = msg.sender
    
    # Get unread counts
    unread_messages = VendorAdminMessage.objects.filter(
        recipient=request.user,
        status='unread',
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    )
    
    for msg in unread_messages:
        vendor = msg.sender if msg.sender != request.user else msg.recipient
        if vendor.id in vendors_data:
            vendors_data[vendor.id]['unread_count'] += 1
    
    # Convert to list and sort
    vendors_list = list(vendors_data.values())
    vendors_list.sort(key=lambda x: x['last_message_time'], reverse=True)
    
    # Apply search filter
    if search_query:
        vendors_list = [
            v for v in vendors_list 
            if search_query.lower() in v['vendor'].email.lower() 
            or search_query.lower() in (v['vendor'].username or '').lower()
            or search_query.lower() in v.get('last_message_preview', '').lower()
        ]
    
    # Pagination
    paginator = Paginator(vendors_list, 20)
    page = request.GET.get('page', 1)
    vendors_page = paginator.get_page(page)
    
    total_unread = sum(v['unread_count'] for v in vendors_list)
    
    context = {
        'vendors': vendors_page,
        'total_unread': total_unread,
        'search_query': search_query,
        'active_tab': 'inbox',
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/admin_messages.html', context)


@staff_member_required
def admin_message_conversation(request, vendor_id):
    """View conversation with specific vendor"""
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    
    # Mark messages as read
    VendorAdminMessage.objects.filter(
        sender=vendor,
        recipient=request.user,
        status='unread'
    ).update(status='read', read_at=timezone.now())
    
    # Get conversation (excluding deleted messages)
    conversation = VendorAdminMessage.objects.filter(
        (Q(sender=request.user, recipient=vendor) | Q(sender=vendor, recipient=request.user)),
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    ).order_by('created_at')
    
    # Handle delete request
    if request.GET.get('delete'):
        message_id = request.GET.get('delete')
        try:
            msg = VendorAdminMessage.objects.get(id=message_id)
            if msg.delete_for_user(request.user):
                messages.success(request, 'Message deleted successfully')
            return redirect('dashboard:admin_message_conversation', vendor_id=vendor_id)
        except VendorAdminMessage.DoesNotExist:
            messages.error(request, 'Message not found')
    
    # Handle delete entire conversation
    if request.GET.get('delete_all'):
        for msg in conversation:
            msg.delete_for_user(request.user)
        messages.success(request, 'Conversation deleted successfully')
        return redirect('dashboard:admin_messages')
    
    if request.method == 'POST':
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')
        message_type = request.POST.get('message_type', 'general')
        product_id = request.POST.get('product_id')
        
        if subject and message_text:
            msg = VendorAdminMessage.objects.create(
                sender=request.user,
                recipient=vendor,
                subject=subject,
                message=message_text,
                message_type=message_type,
                product_id=product_id if product_id else None
            )
            
            # Create notification for vendor
            VendorNotification.objects.create(
                vendor=vendor,
                title=f'New message from Admin: {subject[:50]}',
                message=message_text[:200],
                notification_type='message',
                action_url=f'/dashboard/vendor/messages/'
            )
            
            messages.success(request, 'Message sent successfully!')
            return redirect('dashboard:admin_message_conversation', vendor_id=vendor_id)
    
    # Get products from this vendor for reference
    vendor_products = Product.objects.filter(vendor=vendor, is_active=True, approval_status="approved")
    
    context = {
        'vendor': vendor,
        'messages': conversation,
        'vendor_products': vendor_products,
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
        'active_tab': 'conversation'
    }
    return render(request, 'dashboard/admin_message_conversation.html', context)


@staff_member_required
def admin_send_broadcast(request):
    """Send broadcast message to all vendors"""
    
    if request.method == 'POST':
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')
        message_type = request.POST.get('message_type', 'announcement')
        
        if subject and message_text:
            vendors = User.objects.filter(user_type='vendor', is_active=True)
            sent_count = 0
            
            for vendor in vendors:
                # Create message
                VendorAdminMessage.objects.create(
                    sender=request.user,
                    recipient=vendor,
                    subject=f'[BROADCAST] {subject}',
                    message=message_text,
                    message_type=message_type
                )
                
                # Create notification
                VendorNotification.objects.create(
                    vendor=vendor,
                    title=f'Admin Announcement: {subject[:50]}',
                    message=message_text[:200],
                    notification_type='announcement',
                    action_url='/dashboard/vendor/messages/'
                )
                sent_count += 1
            
            messages.success(request, f'Broadcast sent to {sent_count} vendors!')
            return redirect('dashboard:admin_messages')
        else:
            messages.error(request, 'Please provide both subject and message.')
    
    context = {
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/admin_broadcast.html', context)


@staff_member_required
def admin_search_vendors(request):
    """API endpoint to search vendors for messaging"""
    from django.db.models import Q
    
    query = request.GET.get('q', '')
    vendors = User.objects.filter(
        user_type='vendor',
        is_active=True
    ).filter(
        Q(email__icontains=query) | 
        Q(username__icontains=query) |
        Q(vendor_profile__store_name__icontains=query)
    )[:20]
    
    results = []
    for vendor in vendors:
        results.append({
            'id': vendor.id,
            'email': vendor.email,
            'username': vendor.username,
            'store_name': getattr(vendor, 'vendor_profile', None).store_name if hasattr(vendor, 'vendor_profile') else None,
            'avatar': None
        })
    
    return JsonResponse({'vendors': results})


@login_required
def vendor_messages(request):
    """Vendor message inbox"""
    search_query = request.GET.get('search', '')
    
    # Get conversations with admins
    conversations_raw = VendorAdminMessage.objects.filter(
        Q(sender=request.user) | Q(recipient=request.user)
    ).exclude(
        Q(sender=request.user, is_deleted_by_sender=True) |
        Q(recipient=request.user, is_deleted_by_recipient=True)
    )
    
    # Build admin list with latest message time
    admins_data = {}
    
    for msg in conversations_raw:
        admin = msg.sender if msg.sender != request.user else msg.recipient
        if not admin.is_staff:
            continue
            
        if admin.id not in admins_data:
            admins_data[admin.id] = {
                'admin': admin,
                'last_message_time': msg.created_at,
                'last_message_preview': msg.message[:50] if msg.message else '',
                'unread_count': 0,
                'last_message_sender': msg.sender
            }
        else:
            if msg.created_at > admins_data[admin.id]['last_message_time']:
                admins_data[admin.id]['last_message_time'] = msg.created_at
                admins_data[admin.id]['last_message_preview'] = msg.message[:50] if msg.message else ''
                admins_data[admin.id]['last_message_sender'] = msg.sender
    
    # Get unread counts
    unread_messages = VendorAdminMessage.objects.filter(
        recipient=request.user,
        status='unread',
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    )
    
    for msg in unread_messages:
        admin = msg.sender if msg.sender != request.user else msg.recipient
        if admin.id in admins_data:
            admins_data[admin.id]['unread_count'] += 1
    
    # Convert to list and sort
    admins_list = list(admins_data.values())
    admins_list.sort(key=lambda x: x['last_message_time'], reverse=True)
    
    # Apply search filter
    if search_query:
        admins_list = [
            a for a in admins_list 
            if search_query.lower() in a['admin'].email.lower() 
            or search_query.lower() in (a['admin'].username or '').lower()
            or search_query.lower() in a.get('last_message_preview', '').lower()
        ]
    
    # Pagination
    paginator = Paginator(admins_list, 20)
    page = request.GET.get('page', 1)
    admins_page = paginator.get_page(page)
    
    total_unread = sum(a['unread_count'] for a in admins_list)
    
    # Mark notifications as read
    VendorNotification.objects.filter(vendor=request.user, is_read=False).update(is_read=True)
    
    # Get notifications
    notifications = VendorNotification.objects.filter(vendor=request.user)[:20]
    
    # Convert notifications to list of dicts
    notifications_list = []
    for notif in notifications:
        notifications_list.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'notification_type': notif.notification_type,
            'action_url': notif.action_url,
            'created_at': notif.created_at
        })
    
    context = {
        'admins': admins_page,
        'total_unread': total_unread,
        'search_query': search_query,
        'notifications': notifications_list,
        'active_tab': 'inbox',
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/vendor_messages.html', context)


@login_required
def vendor_start_conversation(request):
    """Start a new conversation with admin"""
    
    if request.method == 'POST':
        admin_id = request.POST.get('admin_id')
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')
        
        if admin_id and subject and message_text:
            admin = get_object_or_404(User, id=admin_id, is_staff=True)
            
            msg = VendorAdminMessage.objects.create(
                sender=request.user,
                recipient=admin,
                subject=subject,
                message=message_text,
                message_type='general'
            )
            
            messages.success(request, 'Message sent successfully!')
            return redirect('dashboard:vendor_message_conversation', admin_id=admin_id)
    
    # Get list of admins to message
    admins = User.objects.filter(is_staff=True, is_active=True)
    
    context = {
        'admins': admins,
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/vendor_start_conversation.html', context)


@login_required
def vendor_message_conversation(request, admin_id):
    """View conversation with admin"""
    admin = get_object_or_404(User, id=admin_id, is_staff=True)
    
    # Mark messages as read
    VendorAdminMessage.objects.filter(
        sender=admin,
        recipient=request.user,
        status='unread'
    ).update(status='read', read_at=timezone.now())
    
    # Get conversation (excluding deleted messages)
    conversation = VendorAdminMessage.objects.filter(
        (Q(sender=request.user, recipient=admin) | Q(sender=admin, recipient=request.user)),
        is_deleted_by_sender=False,
        is_deleted_by_recipient=False
    ).order_by('created_at')
    
    # Handle delete request
    if request.GET.get('delete'):
        message_id = request.GET.get('delete')
        try:
            msg = VendorAdminMessage.objects.get(id=message_id)
            if msg.delete_for_user(request.user):
                messages.success(request, 'Message deleted successfully')
            return redirect('dashboard:vendor_message_conversation', admin_id=admin_id)
        except VendorAdminMessage.DoesNotExist:
            messages.error(request, 'Message not found')
    
    # Handle delete entire conversation
    if request.GET.get('delete_all'):
        for msg in conversation:
            msg.delete_for_user(request.user)
        messages.success(request, 'Conversation deleted successfully')
        return redirect('dashboard:vendor_messages')
    
    if request.method == 'POST':
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')
        
        if subject and message_text:
            msg = VendorAdminMessage.objects.create(
                sender=request.user,
                recipient=admin,
                subject=subject if subject.startswith('Re:') else f'Re: {subject}',
                message=message_text,
                message_type='general'
            )
            
            messages.success(request, 'Message sent successfully!')
            return redirect('dashboard:vendor_message_conversation', admin_id=admin_id)
    
    context = {
        'admin': admin,
        'messages': conversation,
        'unread_count': VendorAdminMessage.objects.filter(recipient=request.user, status='unread').count(),
    }
    return render(request, 'dashboard/vendor_message_conversation.html', context)


@login_required
def delete_notification(request, notification_id):
    """Delete a notification"""
    
    if request.method == 'POST':
        try:
            notification = VendorNotification.objects.get(id=notification_id, vendor=request.user)
            notification.delete()
            return JsonResponse({'success': True})
        except VendorNotification.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)


@login_required
def delete_all_notifications(request):
    """Delete all notifications for vendor"""
    
    if request.method == 'POST':
        count = VendorNotification.objects.filter(vendor=request.user).delete()[0]
        return JsonResponse({'success': True, 'deleted': count})
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
