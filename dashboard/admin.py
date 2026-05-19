from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from .models import AdminActivityLog, DashboardWidget, SystemAlert, VendorAdminMessage, VendorNotification


@admin.register(SystemAlert)
class SystemAlertAdmin(admin.ModelAdmin):
    list_display = ["title", "level", "is_read", "is_dismissed", "created_at"]
    list_filter = ["level", "is_read", "is_dismissed", "created_at"]
    search_fields = ["title", "message", "link"]
    readonly_fields = ["created_at", "updated_at"]
    actions = ["mark_read", "dismiss"]

    def mark_read(self, request, queryset):
        queryset.update(is_read=True)
    mark_read.short_description = "Mark selected alerts read"

    def dismiss(self, request, queryset):
        queryset.update(is_dismissed=True)
    dismiss.short_description = "Dismiss selected alerts"


@admin.register(VendorNotification)
class VendorNotificationAdmin(admin.ModelAdmin):
    list_display = ["vendor", "title", "notification_type", "is_read", "created_at"]
    list_filter = ["notification_type", "is_read", "created_at"]
    search_fields = ["vendor__email", "vendor__username", "title", "message"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(VendorAdminMessage)
class VendorAdminMessageAdmin(admin.ModelAdmin):
    list_display = ["sender", "recipient", "subject", "message_type", "status", "created_at"]
    list_filter = ["message_type", "status", "created_at"]
    search_fields = ["sender__email", "recipient__email", "subject", "message"]
    readonly_fields = ["created_at", "updated_at", "read_at"]


@admin.register(AdminActivityLog)
class AdminActivityLogAdmin(admin.ModelAdmin):
    list_display = ["admin", "action_type", "model_name", "object_repr", "created_at"]
    list_filter = ["action_type", "model_name", "created_at"]
    search_fields = ["admin__email", "admin__username", "model_name", "object_repr", "changes"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(DashboardWidget)
class DashboardWidgetAdmin(admin.ModelAdmin):
    list_display = ["title", "widget_type", "position", "width", "is_active"]
    list_filter = ["widget_type", "width", "is_active"]
    search_fields = ["title", "roles"]


def _safe_count(model, **filters):
    try:
        return model.objects.filter(**filters).count() if filters else model.objects.count()
    except Exception:
        return 0


def _safe_sum(queryset, field):
    try:
        return queryset.aggregate(total=Sum(field)).get("total") or 0
    except Exception:
        return 0


@staff_member_required
def admin_home(request):
    """
    Arolana admin dashboard page.

    URL target:
        /dashboard/admin/

    Template:
        templates/dashboard/admin_home.html
    """

    User = get_user_model()

    # Optional imports: dashboard should still load if one app/model is unavailable.
    try:
        from products.models import Product, Category
    except Exception:
        Product = None
        Category = None

    try:
        from vendors.models import VendorProfile
    except Exception:
        VendorProfile = None

    try:
        from orders.models import Order
    except Exception:
        Order = None

    try:
        from smartchat.models import SmartChatConversation
    except Exception:
        SmartChatConversation = None

    try:
        from notifications.models import Notification
    except Exception:
        Notification = None

    today = timezone.now().date()

    products_total = _safe_count(Product) if Product else 0
    products_active = _safe_count(Product, is_active=True) if Product else 0
    products_pending = _safe_count(Product, approval_status="pending") if Product else 0
    products_approved = _safe_count(Product, approval_status="approved") if Product else 0

    users_total = _safe_count(User)
    users_today = 0
    try:
        users_today = User.objects.filter(date_joined__date=today).count()
    except Exception:
        users_today = 0

    vendors_total = _safe_count(VendorProfile) if VendorProfile else 0
    vendors_verified = _safe_count(VendorProfile, is_verified=True) if VendorProfile else 0

    orders_total = _safe_count(Order) if Order else 0
    paid_orders = Order.objects.filter(status__in=["paid", "completed", "delivered"]) if Order else []
    total_revenue = _safe_sum(paid_orders, "total_amount") if Order else 0

    chat_open = 0
    chat_admin_requested = 0
    if SmartChatConversation:
        try:
            chat_open = SmartChatConversation.objects.exclude(status="closed").count()
            chat_admin_requested = SmartChatConversation.objects.filter(status="admin_requested").count()
        except Exception:
            chat_open = 0
            chat_admin_requested = 0

    unread_notifications = 0
    if Notification:
        try:
            unread_notifications = Notification.objects.filter(is_read=False).count()
        except Exception:
            unread_notifications = 0

    recent_products = []
    if Product:
        try:
            recent_products = (
                Product.objects.select_related("category", "brand", "vendor")
                .order_by("-created_at")[:8]
            )
        except Exception:
            recent_products = []

    recent_orders = []
    if Order:
        try:
            recent_orders = Order.objects.order_by("-created_at")[:8]
        except Exception:
            recent_orders = []

    context = {
        "metrics": {
            "users_total": users_total,
            "users_today": users_today,
            "products_total": products_total,
            "products_active": products_active,
            "products_pending": products_pending,
            "products_approved": products_approved,
            "vendors_total": vendors_total,
            "vendors_verified": vendors_verified,
            "orders_total": orders_total,
            "total_revenue": total_revenue,
            "chat_open": chat_open,
            "chat_admin_requested": chat_admin_requested,
            "unread_notifications": unread_notifications,
        },
        "recent_products": recent_products,
        "recent_orders": recent_orders,
        "page_title": "Arolana Admin Dashboard",
    }

    return render(request, "dashboard/admin_home.html", context)
