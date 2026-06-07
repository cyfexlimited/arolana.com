from django.urls import path

from . import views

app_name = "arolana_ops"

urlpatterns = [
    path("api/mobile/recommendations/", views.mobile_recommendations_api, name="mobile_recommendations_api"),
    path("api/mobile/product-history/", views.mobile_product_history_api, name="mobile_product_history_api"),
    path("api/mobile/product-view/", views.mobile_product_view_api, name="mobile_product_view_api"),
    path("api/mobile/price-alerts/", views.mobile_price_alerts_api, name="mobile_price_alerts_api"),
    path("api/mobile/price-alerts/create/", views.mobile_price_alert_create_api, name="mobile_price_alert_create_api"),
    path("api/mobile/price-alerts/delete/", views.mobile_price_alert_delete_api, name="mobile_price_alert_delete_api"),
]
