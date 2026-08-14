from django.urls import path

from . import views


app_name = "installers"


urlpatterns = [
    # ------------------------------------------------------------------
    # PROJECTS
    # ------------------------------------------------------------------
    path(
        "projects/",
        views.projects_directory,
        name="projects_directory",
    ),
    path(
        "projects/<slug:slug>/",
        views.project_detail,
        name="project_detail",
    ),
    path(
        "projects/<slug:slug>/save/",
        views.save_project,
        name="save_project",
    ),

    # ------------------------------------------------------------------
    # INSTALLER / SERVICE PROVIDER DIRECTORY
    # ------------------------------------------------------------------
    path(
        "",
        views.directory,
        name="directory",
    ),

    # ------------------------------------------------------------------
    # PROVIDER REGISTRATION
    # ------------------------------------------------------------------
    path(
        "register/",
        views.register_provider,
        name="register",
    ),

    # ------------------------------------------------------------------
    # PROVIDER DASHBOARD
    # ------------------------------------------------------------------
    path(
        "dashboard/",
        views.provider_dashboard,
        name="provider_dashboard",
    ),
    path(
        "dashboard/services/add/",
        views.add_provider_service,
        name="add_service",
    ),
    path(
        "dashboard/portfolio/add/",
        views.add_portfolio,
        name="add_portfolio",
    ),
    path(
        "dashboard/projects/",
        views.provider_projects,
        name="provider_projects",
    ),
    path(
        "dashboard/projects/add/",
        views.add_portfolio,
        name="provider_project_add",
    ),
    path(
        "dashboard/projects/leads/",
        views.provider_project_leads,
        name="provider_project_leads",
    ),
    path(
        "dashboard/projects/<int:project_id>/",
        views.provider_project_edit,
        name="provider_project_edit",
    ),
    path(
        "dashboard/projects/<int:project_id>/media/",
        views.provider_project_media,
        name="provider_project_media",
    ),
    path(
        "dashboard/projects/<int:project_id>/analytics/",
        views.provider_project_analytics,
        name="provider_project_analytics",
    ),

    # ------------------------------------------------------------------
    # QUOTES
    # ------------------------------------------------------------------
    path(
        "request-quote/",
        views.request_quote,
        name="request_quote",
    ),
    path(
        "request-quote/success/",
        views.quote_success,
        name="quote_success",
    ),

    # ------------------------------------------------------------------
    # SERVICE CATEGORIES
    #
    # IMPORTANT:
    # These routes must appear BEFORE the generic provider-slug routes.
    # ------------------------------------------------------------------
    path(
        "category/",
        views.category_directory,
        name="category_directory",
    ),
    path(
        "category/<slug:slug>/",
        views.category_detail,
        name="category_detail",
    ),

    # ------------------------------------------------------------------
    # PROVIDER SERVICES
    # ------------------------------------------------------------------
    path(
        "<slug:provider_slug>/services/<int:service_id>/",
        views.service_detail,
        name="service_detail",
    ),

    # ------------------------------------------------------------------
    # PROVIDER REVIEWS
    # ------------------------------------------------------------------
    path(
        "<slug:slug>/review/",
        views.submit_review,
        name="submit_review",
    ),

    # ------------------------------------------------------------------
    # PROVIDER PROFILE
    #
    # Keep this LAST because <slug:slug>/ is a catch-all provider route.
    # ------------------------------------------------------------------
    path(
        "<slug:slug>/",
        views.provider_detail,
        name="provider_detail",
    ),
]