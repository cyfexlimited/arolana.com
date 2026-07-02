from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.debug_home, name="debug_home"),
    path("quote/vendor/", views.request_vendor_quote, name="request_vendor_quote"),
]