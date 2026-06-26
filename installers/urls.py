from django.urls import path

from . import views

app_name = "installers"

urlpatterns = [
    path("", views.directory, name="directory"),
    path("register/", views.register_provider, name="register"),
    path("dashboard/", views.provider_dashboard, name="provider_dashboard"),
    path("dashboard/services/add/", views.add_provider_service, name="add_service"),
    path("dashboard/portfolio/add/", views.add_portfolio, name="add_portfolio"),
    path("request-quote/", views.request_quote, name="request_quote"),
    path("request-quote/success/", views.quote_success, name="quote_success"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("<slug:slug>/review/", views.submit_review, name="submit_review"),
    path("<slug:slug>/", views.provider_detail, name="provider_detail"),
]

