from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    # Regular chat URLs
    path('', views.chat_list, name='list'),
    path('room/<int:room_id>/', views.chat_room, name='room'),
    path('start/<int:user_id>/', views.start_chat, name='start_user'),
    path('start/product/<int:product_id>/', views.start_chat, name='start_product'),
    path('start/order/<int:order_id>/', views.start_chat, name='start_order'),
    path('send/<int:room_id>/', views.send_message, name='send'),
    path('mark-read/<int:room_id>/', views.mark_read, name='mark_read'),
    path('unread-count/', views.get_unread_count, name='unread_count'),
    
    # Vendor chat URLs
    path('vendor/', views.vendor_chat_list, name='vendor_list'),
    path('vendor/room/<int:room_id>/', views.vendor_chat_room, name='vendor_room'),
    path('vendor/send/<int:room_id>/', views.vendor_send_message, name='vendor_send'),
    path('vendor/unread-count/', views.get_vendor_unread_count, name='vendor_unread'),
    
    # Customer chat URLs
    path('customer/room/<int:room_id>/', views.customer_chat_room, name='customer_room'),
    path('customer/send/<int:room_id>/', views.customer_send_message, name='customer_send'),
    path('start/<int:vendor_id>/', views.start_vendor_chat, name='start_vendor'),
    path('start/<int:vendor_id>/<int:product_id>/', views.start_vendor_chat, name='start_vendor_product'),
]
