from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # Dashboard home
    path('', views.dashboard_home, name='home'),
    
    # Professional admin dashboard
    path('admin-dashboard/', views.admin_dashboard_index, name='admin_index'),
    path('admin-dashboard/stats/', views.admin_dashboard_stats, name='admin_stats'),
    
    # API endpoints for admin panel
    path('api/dashboard/', views.api_dashboard, name='api_dashboard'),
    path('api/products/', views.api_products, name='api_products'),
    path('api/add_product/', views.api_add_product, name='api_add_product'),
    path('api/orders/', views.api_orders, name='api_orders'),
    path('api/users/', views.api_users, name='api_users'),
    path('api/vendors/', views.api_vendors, name='api_vendors'),
    
    # Products CRUD
    path('api/products/list/', views.api_products_list, name='api_products_list'),
    path('api/product/delete/<int:product_id>/', views.api_product_delete, name='api_product_delete'),
    path('api/product/update/<int:product_id>/', views.api_product_update, name='api_product_update'),
    path('api/product/create/', views.api_product_create, name='api_product_create'),
    
    # Users CRUD
    path('api/users/list/', views.api_users_list, name='api_users_list'),
    path('api/user/delete/<int:user_id>/', views.api_user_delete, name='api_user_delete'),
    path('api/user/update/<int:user_id>/', views.api_user_update, name='api_user_update'),
    
    # Orders
    path('api/orders/list/', views.api_orders_list, name='api_orders_list'),
    path('api/order/update-status/<int:order_id>/', views.api_order_update_status, name='api_order_update_status'),
    
    # Admin dashboard (legacy)
    path('admin/', views.admin_dashboard_index, name='admin_home'),
    path('admin/dismiss-alert/<int:alert_id>/', views.dismiss_alert, name='dismiss_alert'),
    path('admin/chart-data/', views.get_chart_data, name='chart_data'),
    path('admin/product-approvals/', views.admin_product_approvals, name='admin_product_approvals'),
    path('admin/product-approval/<int:product_id>/', views.admin_product_approval_detail, name='admin_product_approval_detail'),
    path('admin/search-vendors/', views.admin_search_vendors, name='admin_search_vendors'),
    path('admin/messages/', views.admin_messages, name='admin_messages'),
    path('admin/messages/<int:vendor_id>/', views.admin_message_conversation, name='admin_message_conversation'),
    path('admin/broadcast/', views.admin_send_broadcast, name='admin_broadcast'),

        # Vendor dashboard
    path('vendor/', views.vendor_dashboard, name='vendor_home'),
    path('vendor/orders/', views.vendor_orders, name='vendor_orders'),
    path('vendor/order/<int:order_id>/', views.vendor_order_detail, name='vendor_order_detail'),
    path('vendor/order/<int:order_id>/update-status/', views.vendor_update_order_status, name='update_order_status'),
    path('vendor/products/', views.vendor_products, name='vendor_products'),
    path('vendor/product/<int:product_id>/', views.vendor_product_detail, name='vendor_product_detail'),
    path('vendor/product/add/', views.vendor_add_product, name='vendor_add_product'),
    path('vendor/notifications/api/', views.vendor_notifications_api, name='notifications_api'),
    path('vendor/analytics/', views.vendor_analytics, name='vendor_analytics'),  # ADD THIS
    path('vendor/analytics/api/', views.vendor_analytics_api, name='analytics_api'),
    path('vendor/product/resubmit/<int:product_id>/', views.vendor_resubmit_product, name='vendor_resubmit_product'),
    path('vendor/messages/', views.vendor_messages, name='vendor_messages'),
    path('vendor/messages/<int:admin_id>/', views.vendor_message_conversation, name='vendor_message_conversation'),
    path('vendor/messages/', views.vendor_messages, name='vendor_messages'),
    path('vendor/messages/start/', views.vendor_start_conversation, name='vendor_start_conversation'),
    path('vendor/messages/<int:admin_id>/', views.vendor_message_conversation, name='vendor_message_conversation'),
    path('vendor/messages/notifications/api/', views.vendor_notifications_api, name='vendor_notifications_api'),
    path('vendor/notifications/delete/<int:notification_id>/', views.delete_notification, name='delete_notification'),
    path('vendor/notifications/delete-all/', views.delete_all_notifications, name='delete_all_notifications'),
]
