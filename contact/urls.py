from django.urls import path
from . import views

app_name = "contact"

urlpatterns = [
    path("", views.contact_view, name="index"),
    path("vendor/<int:vendor_id>/", views.contact_view, name="vendor"),
]