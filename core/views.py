from django.shortcuts import render
from django.http import HttpResponse
from products.models import Product
from currency.models import Currency

def debug_home(request):
    """Debug view to test currency on homepage"""
    products = Product.objects.filter(is_active=True)[:5]
    
    html = "<html><body><h1>Currency Debug</h1>"
    html += f"<p>Session Currency: {request.session.get('user_currency', 'NOT SET')}</p>"
    html += "<h2>Products:</h2><ul>"
    
    from currency.templatetags.currency_filters import currency
    
    for product in products:
        price_usd = product.price
        price_converted = currency(price_usd, request)
        html += f"<li>{product.name}: ${price_usd} USD = {price_converted}</li>"
    
    html += "</ul>"
    html += "<p><a href='/currency/switch/?code=USD&next=/debug/'>Set USD</a> | "
    html += "<a href='/currency/switch/?code=NGN&next=/debug/'>Set NGN</a></p>"
    html += "<p><a href='/'>Back to Home</a></p>"
    html += "</body></html>"
    
    return HttpResponse(html)
