import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

# Initialize Django ASGI application early
django_asgi_app = get_asgi_application()

# Import channels after Django setup
try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    
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
except ImportError:
    # Fallback to just ASGI if channels not available
    application = django_asgi_app
    print("Warning: channels not available, WebSocket disabled")