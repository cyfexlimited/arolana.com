"""
ASGI config for arolana_config project.

It exposes the ASGI callable as a module-level variable named ``application``.
For more information on this file, see the Django docs at:
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

# Initialize Django ASGI application early
django_asgi_app = get_asgi_application()

# Try to import channels and configure WebSocket support
try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    
    try:
        from chat.routing import websocket_urlpatterns
    except ImportError:
        websocket_urlpatterns = []
        print("Warning: chat.routing not available")
    
    # Configure the ASGI application with WebSocket support
    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    })
    
except ImportError:
    # Fallback to just ASGI if channels not available
    application = django_asgi_app
    print("Warning: channels not available, WebSocket disabled")