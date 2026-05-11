"""
ASGI config for arolana_config project.

It exposes the ASGI callable as a module-level variable named ``application``.
For more information on this file, see the Django docs at:
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

# Initialize Django ASGI application early to ensure the AppRegistry is populated
django_asgi_app = get_asgi_application()

# Import chat routing after Django setup to avoid circular imports
try:
    from chat.routing import websocket_urlpatterns
except ImportError:
    websocket_urlpatterns = []

# Configure the ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
