from django.shortcuts import render
from django.http import HttpResponse, JsonResponse
from products.models import Product
from currency.models import Currency
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from orders.models import Order
from accounts.models import User
from vendors.models import VendorProfile

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
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)
    
    # Current month stats
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True).count()
    total_orders = Order.objects.count()
    pending_orders = Order.objects.filter(status='pending').count()
    
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
    for product in Product.objects.filter(is_active=True).order_by('-created_at')[:5]:
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

def debug_home(request):
    """Debug view to test currency on homepage"""
    products = Product.objects.filter(is_active=True)[:5]
    
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