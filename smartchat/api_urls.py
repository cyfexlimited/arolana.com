from django.urls import path

from . import api_views

app_name = "smartchat_api"

urlpatterns = [
    path("start/", api_views.start, name="start"),
    path("conversations/", api_views.conversations, name="conversations"),
    path("conversation/<int:conversation_id>/", api_views.conversation_detail, name="conversation"),
    path("message/", api_views.message, name="message"),
    path("feedback/", api_views.feedback, name="feedback"),
    path("request-human/", api_views.request_human, name="request_human"),
    path("unread-count/", api_views.unread_count, name="unread_count"),
    path("mark-read/", api_views.mark_read, name="mark_read"),
]
