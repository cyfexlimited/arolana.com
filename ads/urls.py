from django.urls import path
from . import views

app_name = 'ads'

urlpatterns = [
    path('', views.test_page, name='test_page'),
    path('click/<int:banner_id>/', views.ad_click, name='ad_click'),
    path('track-click/<int:banner_id>/', views.track_click_api, name='track_click'),
    path('track-view/', views.track_view, name='track_view'),
]
