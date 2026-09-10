from django.urls import path

from . import api_views

app_name = "ads_api"

urlpatterns = [
    path("recommendations/", api_views.recommendations_v2, name="recommendations_v2"),
    path("events/", api_views.events_v2, name="events_v2"),
    path("internal-test/", api_views.internal_test_session, name="internal_test_session"),
    path("management/bootstrap/", api_views.management_bootstrap, name="management_bootstrap"),
    path("management/current-advertiser/", api_views.management_current_advertiser, name="management_current_advertiser"),
    path("management/overview/", api_views.management_overview, name="management_overview"),
    path("management/campaigns/", api_views.management_campaigns, name="management_campaigns"),
    path("management/campaigns/<int:campaign_id>/", api_views.management_campaign_detail, name="management_campaign_detail"),
    path("management/campaigns/<int:campaign_id>/external-preview/", api_views.management_campaign_external_preview, name="management_campaign_external_preview"),
    path("management/campaigns/<int:campaign_id>/external-action/", api_views.management_campaign_external_action, name="management_campaign_external_action"),
    path("management/assets/", api_views.management_owned_assets, name="management_owned_assets"),
    path("management/creatives/", api_views.management_creatives, name="management_creatives"),
    path("management/creatives/<int:creative_id>/", api_views.management_creative_detail, name="management_creative_detail"),
    path("management/creatives/<int:creative_id>/preparation/", api_views.management_creative_preparation, name="management_creative_preparation"),
    path("management/creatives/<int:creative_id>/preparation/prepare/", api_views.management_creative_preparation_prepare, name="management_creative_preparation_prepare"),
    path("management/creatives/<int:creative_id>/preparation/retry/", api_views.management_creative_preparation_retry, name="management_creative_preparation_retry"),
    path("management/creatives/<int:creative_id>/media/", api_views.management_creative_media, name="management_creative_media"),
    path("management/creatives/<int:creative_id>/media/<int:media_id>/prepare/", api_views.management_creative_media_prepare, name="management_creative_media_prepare"),
    path("management/creatives/<int:creative_id>/media/<int:media_id>/retry/", api_views.management_creative_media_retry, name="management_creative_media_retry"),
    path("management/analytics/", api_views.management_analytics, name="management_analytics"),
    path("management/connected-accounts/", api_views.management_connected_accounts, name="management_connected_accounts"),
    path("management/connected-accounts/<str:provider>/connect/", api_views.management_connected_account_connect, name="management_connected_account_connect"),
    path("management/connected-accounts/<str:provider>/callback/", api_views.management_connected_account_callback, name="management_connected_account_callback"),
    path("management/connected-accounts/<str:provider>/accounts/", api_views.management_connected_account_accounts, name="management_connected_account_accounts"),
    path("management/connected-accounts/<str:provider>/<int:account_id>/pages/", api_views.management_connected_account_pages, name="management_connected_account_pages"),
    path("management/connected-accounts/<str:provider>/<int:account_id>/page-selection/", api_views.management_connected_account_page_select, name="management_connected_account_page_select"),
    path("management/connected-accounts/<str:provider>/select/", api_views.management_connected_account_select, name="management_connected_account_select"),
    path("management/connected-accounts/<str:provider>/disconnect/", api_views.management_connected_account_disconnect, name="management_connected_account_disconnect"),
]
