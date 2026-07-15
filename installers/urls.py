from django.urls import path

from . import views

app_name = "installers"

urlpatterns = [
    path("projects/", views.projects_directory, name="projects_directory"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("projects/<slug:slug>/save/", views.save_project, name="save_project"),
    path("", views.directory, name="directory"),
    path("register/", views.register_provider, name="register"),
    path("dashboard/", views.provider_dashboard, name="provider_dashboard"),
    path("dashboard/services/add/", views.add_provider_service, name="add_service"),
    path("dashboard/portfolio/add/", views.add_portfolio, name="add_portfolio"),
    path("dashboard/projects/", views.provider_projects, name="provider_projects"),
    path("dashboard/projects/add/", views.add_portfolio, name="provider_project_add"),
    path("dashboard/projects/leads/", views.provider_project_leads, name="provider_project_leads"),
    path("dashboard/projects/<int:project_id>/", views.provider_project_edit, name="provider_project_edit"),
    path("dashboard/projects/<int:project_id>/media/", views.provider_project_media, name="provider_project_media"),
    path("dashboard/projects/<int:project_id>/analytics/", views.provider_project_analytics, name="provider_project_analytics"),
    path("request-quote/", views.request_quote, name="request_quote"),
    path("request-quote/success/", views.quote_success, name="quote_success"),
    path("category/<slug:slug>/", views.category_detail, name="category_detail"),
    path("<slug:provider_slug>/services/<int:service_id>/", views.service_detail, name="service_detail"),
    path("<slug:slug>/review/", views.submit_review, name="submit_review"),
    path("<slug:slug>/", views.provider_detail, name="provider_detail"),
]
