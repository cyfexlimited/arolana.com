"""
ASGI config for arolana_config project.
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

# Initialize Django ASGI application early to ensure the AppRegistry is populated
django_asgi_app = get_asgi_application()

# Import here to avoid circular imports
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# Import chat routing - wrap in try-catch for deployment
try:
    from chat.routing import websocket_urlpatterns
except ImportError:
    websocket_urlpatterns = []
    print("Warning: chat.routing not available")

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})