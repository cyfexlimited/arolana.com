from django.urls import path

from . import views

app_name = "arolana_payments"

urlpatterns = [
    path("", views.checkout, name="checkout"),
    path("start/<str:gateway>/", views.start_payment, name="start"),
    path("api/start/<str:gateway>/", views.start_payment_api, name="start_api"),
    path("manual-crypto/<str:reference>/", views.manual_crypto, name="manual_crypto"),
    path("callback/<str:reference>/", views.callback, name="callback"),
    path("cancel/<str:reference>/", views.cancel, name="cancel"),
    path("status/<str:reference>/", views.status, name="status"),
    path("verify/<str:reference>/", views.verify_payment, name="verify"),
    path("api/mobile/initialize/", views.mobile_initialize_payment_api, name="mobile_initialize"),
    path("api/mobile/verify/", views.mobile_verify_payment_api, name="mobile_verify"),
    path("api/mobile/options/", views.mobile_payment_options_api, name="mobile_options"),

    path("paypal/webhook/", views.paypal_webhook, name="paypal_webhook"),
    path("webhooks/paystack/", views.paystack_webhook, name="paystack_webhook"),
    path("webhooks/flutterwave/", views.flutterwave_webhook, name="flutterwave_webhook"),
    path("webhooks/coinbase/", views.coinbase_webhook, name="coinbase_webhook"),
]
