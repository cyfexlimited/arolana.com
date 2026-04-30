from django.urls import path
from django.http import HttpResponse

def orders_home(request):
    return HttpResponse("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>My Orders - Arolana</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
                h1 { color: #333; }
                .coming-soon { text-align: center; padding: 50px; background: #f9f9f9; border-radius: 8px; }
                .btn { display: inline-block; padding: 10px 20px; background: #3b82f6; color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>My Orders</h1>
                <div class="coming-soon">
                    <i class="fas fa-box-open" style="font-size: 48px; color: #3b82f6;"></i>
                    <h2>Orders Page Coming Soon</h2>
                    <p>Your order history and tracking will appear here.</p>
                    <a href="/" class="btn">Continue Shopping</a>
                </div>
            </div>
        </body>
        </html>
    """)

def order_detail(request, order_number):
    return HttpResponse(f"<h1>Order #{order_number}</h1><p>Order details coming soon.</p>")

app_name = 'orders'

urlpatterns = [
    path('', orders_home, name='list'),
    path('<str:order_number>/', order_detail, name='detail'),
]