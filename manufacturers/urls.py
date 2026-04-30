from django.urls import path
from . import views

app_name = 'manufacturers'

urlpatterns = [
    path('', views.manufacturer_list, name='list'),
    path('<slug:slug>/', views.manufacturer_detail, name='detail'),
    path('api/home/', views.manufacturer_home, name='home_api'),
]
