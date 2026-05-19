from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/chat/<int:room_id>/', consumers.ChatConsumer.as_asgi()),
    path('ws/vendor/<int:vendor_room_id>/', consumers.VendorChatConsumer.as_asgi()),
    path('ws/support/', consumers.SupportConsumer.as_asgi()),
]
