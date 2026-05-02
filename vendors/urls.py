from django.urls import path
from . import views

app_name = 'vendors'

urlpatterns = [
    path('', views.vendor_list, name='list'),
    path('become-vendor/', views.become_vendor, name='become'),  # This MUST come before the slug pattern
    path('<slug:slug>/', views.vendor_detail, name='detail'),
    path('follow/<int:vendor_id>/', views.follow_vendor, name='follow_vendor'),
]
