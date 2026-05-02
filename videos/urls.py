from django.urls import path
from . import views

app_name = 'videos'

urlpatterns = [
    path('watch/<int:video_id>/', views.video_watch, name='watch'),
    path('track/', views.track_video_event, name='track'),
    path('gallery/<slug:slug>/', views.video_gallery, name='gallery'),
    path('embed/<int:video_id>/', views.video_embed, name='video_embed'),
    path('api/product/<int:product_id>/', views.product_videos, name='product_videos'),
]
