from django.urls import path
from . import views

app_name = 'ads'

urlpatterns = [
    path('test/', views.test_ads, name='test'),
    path('track-click/', views.track_click, name='track_click'),
    path('track-view/', views.track_view, name='track_view'),
    path('force-images/', views.force_create_images, name='force_images'),
    path('force-images-view/', views.force_create_images_view, name='force_images_view'),
    path('ajax-get/', views.ajax_get_ad, name='ajax_get'),
]