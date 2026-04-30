from django.urls import path
from . import views

app_name = 'hero_banners'

urlpatterns = [
    path('track-view/', views.track_banner_view, name='track_view'),
    path('track-click/', views.track_banner_click, name='track_click'),
]