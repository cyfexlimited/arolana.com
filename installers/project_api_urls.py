from django.urls import path

from . import project_api


app_name = "projects_api"

urlpatterns = [
    path("", project_api.PublicProjectListAPIView.as_view(), name="list"),
    path("featured/", project_api.FeaturedProjectsAPIView.as_view(), name="featured"),
    path("categories/", project_api.ProjectCategoriesAPIView.as_view(), name="categories"),
    path("providers/<int:provider_id>/", project_api.ProviderPublicProjectsAPIView.as_view(), name="provider_projects"),
    path("<slug:project_ref>/", project_api.PublicProjectDetailAPIView.as_view(), name="detail"),
    path("<slug:project_ref>/save/", project_api.ProjectSaveAPIView.as_view(), name="save"),
    path("<slug:project_ref>/report/", project_api.ProjectReportAPIView.as_view(), name="report"),
    path("<slug:project_ref>/share-track/", project_api.ProjectEventAPIView.as_view(event_type="share"), name="share_track"),
    path("<slug:project_ref>/view-track/", project_api.ProjectEventAPIView.as_view(event_type="view"), name="view_track"),
    path("<slug:project_ref>/video-view-track/", project_api.ProjectEventAPIView.as_view(event_type="video_view"), name="video_view_track"),
    path("<slug:project_ref>/request-similar-quote/", project_api.ProjectSimilarQuoteAPIView.as_view(), name="request_similar_quote"),
]


provider_project_urlpatterns = [
    path("projects/", project_api.ProviderProjectsAPIView.as_view(), name="provider_projects"),
    path("projects/entitlements/", project_api.ProviderProjectEntitlementsAPIView.as_view(), name="provider_project_entitlements"),
    path("projects/leads/", project_api.ProviderProjectLeadsAPIView.as_view(), name="provider_project_leads"),
    path("projects/<int:project_id>/", project_api.ProviderProjectDetailAPIView.as_view(), name="provider_project_detail"),
    path("projects/<int:project_id>/submit/", project_api.ProviderProjectSubmitAPIView.as_view(), name="provider_project_submit"),
    path("projects/<int:project_id>/media/", project_api.ProviderProjectMediaAPIView.as_view(), name="provider_project_media"),
    path("projects/<int:project_id>/media/<int:media_id>/", project_api.ProviderProjectMediaDeleteAPIView.as_view(), name="provider_project_media_delete"),
    path("projects/<int:project_id>/analytics/", project_api.ProviderProjectAnalyticsAPIView.as_view(), name="provider_project_analytics"),
]


staff_project_urlpatterns = [
    path("projects/", project_api.StaffProjectsAPIView.as_view(), name="staff_projects"),
    path("projects/<int:project_id>/", project_api.StaffProjectDetailAPIView.as_view(), name="staff_project_detail"),
    path("projects/<int:project_id>/approve/", project_api.StaffProjectApproveAPIView.as_view(), name="staff_project_approve"),
    path("projects/<int:project_id>/require-changes/", project_api.StaffProjectRequireChangesAPIView.as_view(), name="staff_project_require_changes"),
    path("projects/<int:project_id>/reject/", project_api.StaffProjectRejectAPIView.as_view(), name="staff_project_reject"),
    path("projects/<int:project_id>/feature/", project_api.StaffProjectFeatureAPIView.as_view(), name="staff_project_feature"),
    path("projects/<int:project_id>/verify/", project_api.StaffProjectVerifyAPIView.as_view(), name="staff_project_verify"),
]
