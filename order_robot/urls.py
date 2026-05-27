from django.urls import path

from . import views


app_name = "order_robot"

urlpatterns = [
    path("status/<str:order_number>/", views.robot_status, name="status"),
]
