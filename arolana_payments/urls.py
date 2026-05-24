from django.urls import path

from . import views

app_name = "arolana_payments"

urlpatterns = [
    path("", views.checkout, name="checkout"),
    path("start/<str:gateway>/", views.start_payment, name="start"),
    path("manual-crypto/<str:reference>/", views.manual_crypto, name="manual_crypto"),
    path("callback/<str:reference>/", views.callback, name="callback"),
    path("cancel/<str:reference>/", views.cancel, name="cancel"),
    path("status/<str:reference>/", views.status, name="status"),
    path("verify/<str:reference>/", views.verify_payment, name="verify"),

    path("webhooks/flutterwave/", views.flutterwave_webhook, name="flutterwave_webhook"),
    path("webhooks/coinbase/", views.coinbase_webhook, name="coinbase_webhook"),
]
