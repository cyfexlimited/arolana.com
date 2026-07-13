from django.urls import path

from . import views


app_name = "provider_workspace"

urlpatterns = [
    path("", views.workspace_dashboard, name="dashboard"),
    path("profile/", views.workspace_profile, name="profile"),
    path("services/", views.workspace_services, name="services"),
    path("services/add/", views.workspace_services, name="service_add"),
    path("services/<int:service_id>/", views.workspace_services, name="service_edit"),
    path("projects/", views.provider_projects, name="projects"),
    path("projects/add/", views.add_portfolio, name="project_add"),
    path("projects/leads/", views.provider_project_leads, name="project_leads"),
    path("projects/<int:project_id>/", views.provider_project_edit, name="project_edit"),
    path("projects/<int:project_id>/media/", views.provider_project_media, name="project_media"),
    path("projects/<int:project_id>/analytics/", views.provider_project_analytics, name="project_analytics"),
    path("quote-requests/", views.workspace_quote_requests, name="quote_requests"),
    path("reviews/", views.workspace_reviews, name="reviews"),
    path("subscription/", views.workspace_subscription, name="subscription"),
    path("coverage/", views.workspace_availability, name="coverage"),
    path("availability/", views.workspace_availability, name="availability"),
    path("kyc/", views.workspace_kyc, name="kyc"),
    path("analytics/", views.workspace_analytics, name="analytics"),
    path("notifications/", views.workspace_notifications, name="notifications"),
    path("settings/", views.workspace_settings, name="settings"),
]
