from django.urls import path
from . import views

app_name = 'ads'

urlpatterns = [
    path('marketing/', views.marketing_overview, name='marketing_overview'),
    path('marketing/campaigns/', views.marketing_campaigns, name='marketing_campaigns'),
    path('marketing/campaigns/<int:campaign_id>/', views.marketing_campaign_detail, name='marketing_campaign_detail'),
    path('marketing/create/', views.marketing_create_campaign, name='marketing_create_campaign'),
    path('marketing/assets/', views.marketing_assets, name='marketing_assets'),
    path('marketing/creatives/', views.marketing_creatives, name='marketing_creatives'),
    path('marketing/placements/', views.marketing_placements, name='marketing_placements'),
    path('marketing/connected-accounts/', views.marketing_connected_accounts, name='marketing_connected_accounts'),
    path('marketing/connected-accounts/<str:provider>/select/', views.marketing_connected_account_select, name='marketing_connected_account_select'),
    path('marketing/analytics/', views.marketing_analytics, name='marketing_analytics'),
    path('marketing/billing/', views.marketing_billing, name='marketing_billing'),
    path('marketing/settings/', views.marketing_settings, name='marketing_settings'),
    path('test/', views.test_ads, name='test'),
    path('track-click/', views.track_click, name='track_click'),
    path('track-view/', views.track_view, name='track_view'),
    path('force-images/', views.force_create_images, name='force_images'),
    path('force-images-view/', views.force_create_images_view, name='force_images_view'),
    path('ajax-get/', views.ajax_get_ad, name='ajax_get'),
]
