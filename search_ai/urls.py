from django.urls import path
from . import views

app_name = 'search_ai'

urlpatterns = [
    path('', views.advanced_search, name='search'),
    path('ai/', views.ai_search, name='ai_search'),
    path('advanced/', views.advanced_search, name='advanced_search'),
    path('image/', views.image_search, name='image_search'),
    path('track-click/', views.track_click, name='track_click'),
    path('upload-image/', views.upload_search_image, name='upload_image'),
]
