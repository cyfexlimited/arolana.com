from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.orders_home, name="list"),
    path("track/", views.track_order, name="track"),
    path("delivery-quote/", views.delivery_quote, name="delivery_quote"),
    path("delivery-quote-request/", views.delivery_quote_request, name="delivery_quote_request"),

    # Mobile API
    path(
        "api/mobile/orders/create/",
        views.mobile_authenticated_order_create_api,
        name="mobile_authenticated_order_create_api",
    ),
    path(
        "api/mobile/orders/history/",
        views.mobile_authenticated_orders_history_api,
        name="mobile_authenticated_orders_history_api",
    ),
    path(
        "api/mobile/orders/<int:order_id>/",
        views.mobile_authenticated_order_detail_api,
        name="mobile_authenticated_order_detail_api",
    ),
    path(
        "api/mobile/orders/<int:order_id>/tracking/",
        views.mobile_authenticated_order_tracking_api,
        name="mobile_authenticated_order_tracking_api",
    ),
    path(
        "api/mobile/tracking/<str:tracking_code>/",
        views.mobile_authenticated_tracking_code_api,
        name="mobile_authenticated_tracking_code_api",
    ),

    path("<str:order_number>/", views.order_detail, name="detail"),


    path(
        "api/mobile/orders/cancel/",
        views.mobile_authenticated_order_cancel_api,
        name="mobile_authenticated_order_cancel_api",
    ),


    path(
        "api/mobile/orders/receipt/",
        views.mobile_authenticated_order_receipt_pdf_api,
        name="mobile_authenticated_order_receipt_pdf_api",
    ),

]
