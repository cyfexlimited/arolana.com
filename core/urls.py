from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("quote/vendor/", views.request_vendor_quote, name="request_vendor_quote"),
    path("quotes/<int:quote_id>/", views.customer_quote_request_detail, name="customer_quote_request_detail"),
    path("debug/", views.debug_home, name="debug_home"),
]
