from django.urls import path
from . import views

app_name = "smartchat_compat"

urlpatterns = [
    # Backward compatible with your old product detail JavaScript endpoint.
    path("product-chat/", views.api_message, name="product_chat"),
]
