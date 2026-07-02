from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    # Homepage
    path("", views.home, name="home"),

    # Legal / static pages
    path("terms-and-conditions/", views.terms_and_conditions, name="terms_and_conditions"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("return-policy/", views.return_policy, name="return_policy"),
    path("returns/", views.return_policy, name="returns"),
    path("shipping/", views.shipping_policy, name="shipping_policy"),
    path("help/", views.help_center, name="help_center"),
    path("contact/", views.contact_page, name="contact"),

    # Quote request
    path("quote/vendor/", views.request_vendor_quote, name="request_vendor_quote"),

    # Debug should not own homepage
    path("debug/", views.debug_home, name="debug_home"),
]