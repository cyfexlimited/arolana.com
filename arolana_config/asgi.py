import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from chat import consumers

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        URLRouter([
            path('ws/chat/<str:room_name>/', consumers.ChatConsumer.as_asgi()),
            path('ws/vendor/<str:vendor_id>/', consumers.VendorChatConsumer.as_asgi()),
            path('ws/support/', consumers.SupportConsumer.as_asgi()),
        ])
    ),
})
