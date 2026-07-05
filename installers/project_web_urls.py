from django.urls import path

from . import views


app_name = "projects"

urlpatterns = [
    path("", views.projects_directory, name="directory"),
    path("<slug:slug>/", views.project_detail, name="detail"),
    path("<slug:slug>/save/", views.save_project, name="save"),
]
