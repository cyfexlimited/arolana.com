from django.urls import path

from . import views

app_name = "deliveries"

urlpatterns = [
    path("rider/", views.rider_dashboard, name="rider_dashboard"),
    path("rider/register/", views.rider_register, name="rider_register"),
    path("rider/online/", views.rider_go_online, name="rider_go_online"),
    path("rider/offline/", views.rider_go_offline, name="rider_go_offline"),
    path("rider/accept/<int:delivery_id>/", views.rider_accept_delivery, name="rider_accept_delivery"),
    path("rider/status/<int:delivery_id>/", views.rider_update_status, name="rider_update_status"),
    path("api/rider-location/", views.api_rider_current_location, name="api_rider_current_location"),
    path("api/location/<int:delivery_id>/", views.api_rider_location, name="api_rider_location"),
    path("api/admin-location/<int:delivery_id>/", views.api_admin_delivery_location, name="api_admin_delivery_location"),
    path("api/quote/", views.api_delivery_quote, name="api_delivery_quote"),
    path("track/<str:tracking_code>/", views.customer_tracking, name="customer_tracking"),
]
