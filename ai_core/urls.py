from django.urls import path

from . import views

app_name = "ai_core"

urlpatterns = [
    path("api/ai-core/status/", views.ai_core_status_api, name="status_api"),
]
