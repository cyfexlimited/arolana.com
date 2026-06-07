from django.urls import path
from . import views

app_name = "smartchat"

urlpatterns = [
    # Customer / Visitor Chat API
    path("api/message/", views.api_message, name="api_message"),
    path("api/upload-image/", views.api_upload_image, name="api_upload_image"),
    path("api/guest-contact/", views.api_guest_contact, name="api_guest_contact"),
    path("api/request-admin/", views.api_request_admin, name="api_request_admin"),
    path("api/poll/", views.api_poll, name="api_poll"),
    path("api/typing/", views.api_typing, name="api_typing"),

    # Compatibility aliases
    path("api/message/", views.api_message, name="message"),
    path("api/upload-image/", views.api_upload_image, name="upload_image"),
    path("api/guest-contact/", views.api_guest_contact, name="guest_contact"),
    path("api/request-admin/", views.api_request_admin, name="request_admin_handoff"),
    path("api/poll/", views.api_poll, name="poll"),
    path("api/typing/", views.api_typing, name="typing"),

    # Admin pages
    path("admin/inbox/", views.admin_inbox, name="admin_inbox"),
    path("admin/conversation/<int:conversation_id>/", views.admin_conversation, name="admin_conversation"),
    path("admin/conversation/<int:conversation_id>/reply/", views.admin_reply, name="admin_reply"),
    path("admin/conversation/<int:conversation_id>/close/", views.admin_close, name="admin_close"),
    path("admin/conversation/<int:conversation_id>/poll/", views.admin_poll, name="admin_poll"),
    path("admin/conversation/<int:conversation_id>/typing/", views.admin_typing, name="admin_typing"),


    path("api/mobile/start/", views.mobile_smartchat_start_api, name="mobile_smartchat_start_api"),
    path("api/mobile/send/", views.mobile_smartchat_send_api, name="mobile_smartchat_send_api"),
    path("api/mobile/upload-image/", views.mobile_smartchat_upload_image_api, name="mobile_smartchat_upload_image_api"),
    path("api/mobile/poll/", views.mobile_smartchat_poll_api, name="mobile_smartchat_poll_api"),
    path("api/mobile/mark-read/", views.mobile_smartchat_mark_read_api, name="mobile_smartchat_mark_read_api"),

    # Arolana Chat operations assistant
    path("api/operations/message/", views.operations_message_api, name="operations_message_api"),
    path("api/operations/tickets/", views.operations_tickets_api, name="operations_tickets_api"),
    path("api/operations/tickets/create/", views.operations_create_ticket_api, name="operations_create_ticket_api"),

]
