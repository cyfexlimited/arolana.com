from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/chat/<str:room_name>/', consumers.ChatConsumer.as_asgi()),
    path('ws/vendor/<str:vendor_id>/', consumers.VendorChatConsumer.as_asgi()),
    path('ws/support/', consumers.SupportConsumer.as_asgi()),
]
