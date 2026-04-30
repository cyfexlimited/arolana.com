from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.db import models
from django.db.models import Sum, Count, Q, Avg
from django.utils import timezone
from datetime import timedelta
from django.core.paginator import Paginator
from django.template.loader import render_to_string
import json

from products.models import Product, ProductReview, Category
from vendors.models import VendorProfile
from accounts.models import User
from orders.models import Order, OrderItem
from .models import AdminActivityLog, SystemAlert

# ==================== PROFESSIONAL ADMIN DASHBOARD ====================

@staff_member_required
def admin_dashboard_index(request):
    """Professional admin dashboard with modern UI"""
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    # Stats
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True).count()
    vendors_count = VendorProfile.objects.filter(is_verified=True).count()
    low_stock_count = Product.objects.filter(stock_quantity__lte=5, is_active=True).count()
    
    # Growth
    revenue_growth = Order.objects.filter(
        created_at__date__gte=week_ago, 
        status='delivered'
    ).aggregate(total=Sum('total'))['total'] or 0
    order_growth = Order.objects.filter(created_at__date__gte=week_ago).count()
    
    # Recent orders
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    
    # Recent activity
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

@staff_member_required
def admin_dashboard_stats(request):
    """Dashboard statistics page"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    # Stats
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True).count()
    vendors_count = VendorProfile.objects.filter(is_verified=True).count()
    low_stock_count = Product.objects.filter(stock_quantity__lte=5, is_active=True).count()
    
    # Recent orders
    recent_orders = Order.objects.select_related('user').order_by('-created_at')[:10]
    
    # Recent activity
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

# ==================== API ENDPOINTS ====================

@staff_member_required
def api_dashboard(request):
    """API endpoint for dashboard data"""
    today = timezone.now().date()
    
    total_revenue = Order.objects.filter(status='delivered').aggregate(total=Sum('total'))['total'] or 0
    total_orders = Order.objects.count()
    total_users = User.objects.count()
    total_products = Product.objects.filter(is_active=True).count()
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
    """API endpoint for products list"""
    products = Product.objects.filter(is_active=True)[:20]
    html = render_to_string('admin_dashboard/partials/products.html', {'products': products})
    return JsonResponse({'html': html})

@staff_member_required
def api_add_product(request):
    """API endpoint for add product form"""
    from products.models import Category, Brand
    categories = Category.objects.filter(is_active=True)
    brands = Brand.objects.filter(is_active=True)
    html = render_to_string('admin_dashboard/partials/add_product.html', {
        'categories': categories,
        'brands': brands,
    })
    return JsonResponse({'html': html})

@staff_member_required
def api_orders(request):
    """API endpoint for orders list"""
    orders = Order.objects.all().order_by('-created_at')[:20]
    html = render_to_string('admin_dashboard/partials/orders.html', {'orders': orders})
    return JsonResponse({'html': html})

@staff_member_required
def api_users(request):
    """API endpoint for users list"""
    users = User.objects.all().order_by('-date_joined')[:20]
    html = render_to_string('admin_dashboard/partials/users.html', {'users': users})
    return JsonResponse({'html': html})

@staff_member_required
def api_vendors(request):
    """API endpoint for vendors list"""
    vendors = VendorProfile.objects.filter(is_active=True)[:20]
    html = render_to_string('admin_dashboard/partials/vendors.html', {'vendors': vendors})
    return JsonResponse({'html': html})

# ==================== VENDOR DASHBOARD ====================

@login_required
def vendor_dashboard(request):
    """Advanced vendor dashboard with notifications and analytics"""
    
    # Check if user is a vendor
    if not hasattr(request.user, 'vendor_profile') and request.user.user_type != 'vendor':
        return render(request, 'dashboard/access_denied.html', {
            'message': 'You are not registered as a vendor. Please become a vendor first.'
        })
    
    # Get vendor profile
    try:
        vendor_profile = request.user.vendor_profile
    except VendorProfile.DoesNotExist:
        return render(request, 'dashboard/access_denied.html', {
            'message': 'Your vendor profile is not set up. Please contact support.'
        })
    
    # Get products
    products = Product.objects.filter(vendor=request.user, is_active=True)
    
    # Get orders for vendor's products
    try:
        order_items = OrderItem.objects.filter(product__vendor=request.user)
        orders = Order.objects.filter(items__in=order_items).distinct()
    except:
        orders = []
        order_items = []
    
    # Calculate stats
    total_orders = len(orders) if orders else 0
    total_sales = sum(order.total for order in orders if hasattr(order, 'status') and order.status == 'delivered') if orders else 0
    
    # Get product reviews
    reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True)
    avg_rating = reviews.aggregate(avg=models.Avg('rating'))['avg'] or 0
    
    # Get low stock products
    low_stock = products.filter(stock_quantity__lte=5)
    
    # Get top selling products
    top_products = products[:5]
    
    # Recent orders for table
    recent_orders = orders[:10] if orders else []
    
    # Recent reviews
    recent_reviews = reviews.order_by('-created_at')[:5]
    
    # Create notifications
    notifications = []
    
    # Low stock notification
    if low_stock.exists():
        notifications.append({
            'type': 'warning',
            'title': 'Low Stock Alert',
            'message': f'You have {low_stock.count()} products with low stock (≤5 units)',
            'action_url': '/dashboard/vendor/#products',
            'icon': 'fa-exclamation-triangle'
        })
    
    # New review notification
    if recent_reviews.exists():
        notifications.append({
            'type': 'info',
            'title': 'New Reviews',
            'message': f'You have {recent_reviews.count()} new product reviews',
            'action_url': '/dashboard/vendor/#reviews',
            'icon': 'fa-star'
        })
    
    context = {
        'vendor_profile': vendor_profile,
        'total_products': products.count(),
        'total_orders': total_orders,
        'total_sales': total_sales,
        'low_stock': low_stock,
        'low_stock_count': low_stock.count(),
        'top_products': top_products,
        'avg_rating': round(avg_rating, 1),
        'total_reviews': reviews.count(),
        'recent_orders': recent_orders,
        'recent_reviews': recent_reviews,
        'notifications': notifications,
    }
    return render(request, 'dashboard/vendor_dashboard.html', context)

def dashboard_home(request):
    """Dashboard home redirect"""
    if request.user.is_authenticated:
        if request.user.user_type == 'vendor' or hasattr(request.user, 'vendor_profile'):
            return vendor_dashboard(request)
        elif request.user.is_staff or request.user.user_type == 'super_admin':
            return admin_dashboard_index(request)
    return render(request, 'dashboard/home.html')

@login_required
def vendor_orders(request):
    """Vendor order management"""
    try:
        order_items = OrderItem.objects.filter(product__vendor=request.user)
        orders = Order.objects.filter(items__in=order_items).distinct().order_by('-created_at')
        paginator = Paginator(orders, 20)
        page = request.GET.get('page', 1)
        orders_page = paginator.get_page(page)
    except:
        orders_page = []
    
    return render(request, 'dashboard/vendor_orders.html', {'orders': orders_page})

@login_required
def vendor_order_detail(request, order_id):
    """Vendor order detail view"""
    try:
        order = get_object_or_404(Order, id=order_id)
        vendor_items = order.items.filter(product__vendor=request.user)
    except:
        order = None
        vendor_items = []
    
    return render(request, 'dashboard/vendor_order_detail.html', {
        'order': order,
        'vendor_items': vendor_items
    })

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

@login_required
def vendor_products(request):
    """Vendor product management"""
    products = Product.objects.filter(vendor=request.user, is_active=True).order_by('-created_at')
    
    paginator = Paginator(products, 20)
    page = request.GET.get('page', 1)
    products_page = paginator.get_page(page)
    
    return render(request, 'dashboard/vendor_products.html', {'products': products_page})

@login_required
def vendor_product_detail(request, product_id):
    """Vendor product detail view"""
    product = get_object_or_404(Product, id=product_id, vendor=request.user)
    
    if request.method == 'POST':
        new_stock = request.POST.get('stock_quantity')
        if new_stock:
            product.stock_quantity = int(new_stock)
            product.save()
            messages.success(request, 'Product stock updated successfully')
    
    return render(request, 'dashboard/vendor_product_detail.html', {'product': product})

@login_required
def vendor_notifications_api(request):
    """API endpoint for notifications"""
    try:
        order_items = OrderItem.objects.filter(product__vendor=request.user)
        new_orders = Order.objects.filter(items__in=order_items, status='pending').count()
        new_reviews = ProductReview.objects.filter(product__vendor=request.user, is_active=True).count()
        low_stock = Product.objects.filter(vendor=request.user, stock_quantity__lte=5, is_active=True).count()
        
        notifications = []
        if new_orders > 0:
            notifications.append({'type': 'order', 'count': new_orders, 'message': f'{new_orders} new orders'})
        if new_reviews > 0:
            notifications.append({'type': 'review', 'count': new_reviews, 'message': f'{new_reviews} new reviews'})
        if low_stock > 0:
            notifications.append({'type': 'stock', 'count': low_stock, 'message': f'{low_stock} low stock items'})
        
        return JsonResponse({'notifications': notifications, 'total': len(notifications)})
    except:
        return JsonResponse({'notifications': [], 'total': 0})

@staff_member_required
def dismiss_alert(request, alert_id):
    """Dismiss a system alert"""
    alert = get_object_or_404(SystemAlert, id=alert_id)
    alert.is_dismissed = True
    alert.save()
    return JsonResponse({'success': True})

@staff_member_required
def get_chart_data(request):
    """AJAX endpoint for real-time chart updates"""
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

@login_required
def vendor_analytics_api(request):
    """API endpoint for vendor analytics data"""
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

@staff_member_required
def api_products_list(request):
    products = Product.objects.filter(is_active=True).order_by('-created_at')
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
                vendor=User.objects.filter(is_staff=True).first(),
                category=Category.objects.first(),
                is_active=True
            )
            return JsonResponse({'success': True, 'id': product.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False})

# ==================== USERS CRUD ====================

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

# ==================== ORDERS CRUD ====================

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