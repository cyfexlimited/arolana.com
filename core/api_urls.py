from django.urls import path

from . import api_views

app_name = "quotes_api"

urlpatterns = [
    path("", api_views.quote_list_api, name="list"),
    path("create/", api_views.quote_create_api, name="create"),
    path("<int:quote_id>/", api_views.quote_detail_api, name="detail"),
    path("<int:quote_id>/vendor-response/", api_views.vendor_response_api, name="vendor_response"),
    path("<int:quote_id>/admin-message/", api_views.admin_vendor_message_api, name="admin_message"),
    path("<int:quote_id>/admin-customer-response/", api_views.admin_customer_response_api, name="admin_customer_response"),
    path("<int:quote_id>/internal-note/", api_views.admin_internal_note_api, name="internal_note"),
    path("<int:quote_id>/status/", api_views.quote_status_api, name="status"),
]
