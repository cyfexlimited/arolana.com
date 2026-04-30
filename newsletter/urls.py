from django.urls import path
from . import views

app_name = 'newsletter'

urlpatterns = [
    path('subscribe/', views.subscribe, name='subscribe'),
    path('api/subscribe/', views.api_subscribe, name='api_subscribe'),
    path('unsubscribe/<str:email>/', views.unsubscribe, name='unsubscribe'),
    path('unsubscribe/<str:token>/', views.unsubscribe_token, name='unsubscribe_token'),
    path('track/open/<int:tracking_id>/', views.track_open, name='track_open'),
    path('track/click/<int:tracking_id>/', views.track_click, name='track_click'),
    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/create/', views.campaign_create, name='campaign_create'),
    path('campaigns/<int:campaign_id>/', views.campaign_detail, name='campaign_detail'),
    path('campaigns/<int:campaign_id>/send/', views.campaign_send, name='campaign_send'),
    path('subscribers/', views.subscriber_list, name='subscriber_list'),
    path('subscribers/<int:subscriber_id>/', views.subscriber_detail, name='subscriber_detail'),
    path('subscribers/export/', views.subscriber_export, name='subscriber_export'),
]
