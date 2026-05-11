import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

django_asgi_app = get_asgi_application()

# Try to configure WebSocket support
try:
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    
    # Import chat routing
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
    application = django_asgi_app
    print("Warning: channels not available, WebSocket disabled")
