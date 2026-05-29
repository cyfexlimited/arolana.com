from django.urls import path

from . import views


app_name = "landing_pages"

urlpatterns = [
    path("<slug:slug>/", views.landing_page_detail, name="detail"),
]
