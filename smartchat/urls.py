from django.urls import path
from . import views

app_name = "smartchat"

urlpatterns = [
    # Customer robot chat API - current names
    path("api/message/", views.api_message, name="api_message"),
    path("api/request-admin/", views.api_request_admin, name="api_request_admin"),
    path("api/poll/", views.api_poll, name="api_poll"),

    # Customer robot chat API - compatibility aliases
    path("api/message/", views.api_message, name="message"),
    path("api/request-admin/", views.api_request_admin, name="request_admin_handoff"),
    path("api/poll/", views.api_poll, name="poll"),

    # Admin pages
    path("admin/inbox/", views.admin_inbox, name="admin_inbox"),
    path("admin/conversation/<int:conversation_id>/", views.admin_conversation, name="admin_conversation"),
    path("admin/conversation/<int:conversation_id>/reply/", views.admin_reply, name="admin_reply"),
    path("admin/conversation/<int:conversation_id>/close/", views.admin_close, name="admin_close"),
    path("admin/conversation/<int:conversation_id>/poll/", views.admin_poll, name="admin_poll"),
]