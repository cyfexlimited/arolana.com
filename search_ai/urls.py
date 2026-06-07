from django.urls import path
from . import views

app_name = 'search_ai'

urlpatterns = [
    path('', views.advanced_search, name='search'),
    path('ai/', views.ai_search, name='ai_search'),
    path('advanced/', views.advanced_search, name='advanced_search'),
    path('image/', views.image_search, name='image_search'),
    path('voice/', views.voice_search, name='voice_search'),
    path('voice-page/', views.voice_search_page, name='voice_search_page'),
    path('track-click/', views.track_click, name='track_click'),
    path('upload-image/', views.upload_search_image, name='upload_image'),

    path('api/mobile/search/ai/', views.mobile_ai_search_api, name='mobile_ai_search_api'),
    path('api/mobile/search/voice/', views.mobile_voice_search_api, name='mobile_voice_search_api'),
]
