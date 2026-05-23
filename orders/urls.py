from django.urls import path

from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.orders_home, name='list'),
    path('track/', views.track_order, name='track'),
    path('delivery-quote/', views.delivery_quote, name='delivery_quote'),
    path('<str:order_number>/', views.order_detail, name='detail'),
]
