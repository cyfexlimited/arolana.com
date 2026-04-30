from django.shortcuts import redirect, render
from django.http import JsonResponse, HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Currency, CountryCurrency, CurrencyConversionLog
import json
import logging

logger = logging.getLogger(__name__)

def test_currency(request):
    """Debug view to test currency detection"""
    return JsonResponse({
        'session_currency': request.session.get('user_currency'),
        'cookie_currency': request.COOKIES.get('user_currency'),
        'accept_language': request.META.get('HTTP_ACCEPT_LANGUAGE', ''),
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:100],
        'detected_currency': getattr(request, 'user_currency', 'Not set'),
        'detected_symbol': getattr(request, 'currency_symbol', 'Not set'),
        'middleware_ran': True
    })

def switch_currency(request):
    """Switch user's currency - saves to session AND cookie"""
    if request.method == 'POST':
        currency_code = request.POST.get('code')
        next_url = request.POST.get('next', '/')
    else:
        currency_code = request.GET.get('code')
        next_url = request.GET.get('next', '/')
    
    if currency_code:
        try:
            currency = Currency.objects.get(code=currency_code.upper(), is_active=True)
            request.session['user_currency'] = currency.code
            request.session['user_currency_set'] = True
            request.session.modified = True
            
            response = redirect(next_url)
            response.set_cookie('user_currency', currency.code, max_age=31536000, httponly=False, samesite='Lax')
            
            print(f"✅ Currency switched to: {currency.code} ({currency.symbol})")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'currency': currency.code,
                    'symbol': currency.symbol
                })
            
            return response
            
        except Currency.DoesNotExist:
            print(f"❌ Currency not found: {currency_code}")
    
    return redirect(next_url)

def auto_detect_currency(request):
    """Automatically detect and set currency based on visitor's IP"""
    if request.session.get('user_currency_set') or request.COOKIES.get('user_currency'):
        return
    
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0]
    else:
        ip_address = request.META.get('REMOTE_ADDR')
    
    try:
        from currency.geo.ip_geolocation import IPGeolocationService, get_currency_for_country
        geo_service = IPGeolocationService()
        country_code = geo_service.get_country_code(ip_address)
        
        if country_code:
            currency_code = get_currency_for_country(country_code)
            try:
                currency = Currency.objects.get(code=currency_code, is_active=True)
                request.session['user_currency'] = currency.code
                request.session['user_currency_set'] = True
                request.session.modified = True
                print(f"🌍 Auto-detected currency: {currency.code} for country: {country_code}")
                return
            except Currency.DoesNotExist:
                pass
    except Exception as e:
        print(f"Auto-detect error: {e}")

def currency_settings(request):
    """Currency settings page"""
    currencies = Currency.objects.filter(is_active=True)
    user_currency = request.session.get('user_currency', 'USD')
    
    if not request.session.get('user_currency_set') and not request.COOKIES.get('user_currency'):
        auto_detect_currency(request)
        user_currency = request.session.get('user_currency', 'USD')
    
    context = {
        'currencies': currencies,
        'user_currency': user_currency,
    }
    return render(request, 'currency/settings.html', context)

def get_exchange_rate(request, from_currency, to_currency):
    """Get exchange rate between two currencies"""
    try:
        from_curr = Currency.objects.get(code=from_currency.upper(), is_active=True)
        to_curr = Currency.objects.get(code=to_currency.upper(), is_active=True)
        
        rate = float(to_curr.exchange_rate) / float(from_curr.exchange_rate)
        
        return JsonResponse({
            'success': True,
            'from_currency': from_currency.upper(),
            'to_currency': to_currency.upper(),
            'rate': rate,
        })
    except Currency.DoesNotExist as e:
        return JsonResponse({'success': False, 'error': f'Currency not found: {e}'})

@csrf_exempt
@require_http_methods(["POST"])
def convert_amount(request):
    """Convert amount between currencies"""
    try:
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON. Please send a valid JSON body.'
            })
        
        amount = data.get('amount', 0)
        from_code = data.get('from_currency', 'USD')
        to_code = data.get('to_currency', 'USD')
        
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid amount value'})
        
        try:
            from_currency = Currency.objects.get(code=from_code.upper(), is_active=True)
            to_currency = Currency.objects.get(code=to_code.upper(), is_active=True)
        except Currency.DoesNotExist as e:
            return JsonResponse({'success': False, 'error': f'Currency not found: {e}'})
        
        rate = float(to_currency.exchange_rate) / float(from_currency.exchange_rate)
        converted = amount * rate
        
        return JsonResponse({
            'success': True,
            'original_amount': amount,
            'converted_amount': round(converted, 2),
            'formatted': to_currency.format_amount(converted),
            'rate': round(rate, 4),
            'from_currency': from_code.upper(),
            'to_currency': to_code.upper()
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def currency_info(request):
    """Get information about all currencies"""
    currencies = Currency.objects.filter(is_active=True)
    user_currency = request.session.get('user_currency', 'USD')
    
    data = {
        'success': True,
        'base_currency': user_currency,
        'currencies': []
    }
    
    for currency in currencies:
        data['currencies'].append({
            'code': currency.code,
            'symbol': currency.symbol,
            'name': currency.name,
            'exchange_rate': float(currency.exchange_rate),
            'is_base': currency.is_base,
        })
    
    return JsonResponse(data)

def get_current_currency(request):
    """API endpoint to get current currency"""
    currency_code = request.session.get('user_currency')
    if not currency_code:
        currency_code = request.COOKIES.get('user_currency', 'USD')
    
    try:
        currency = Currency.objects.get(code=currency_code, is_active=True)
        return JsonResponse({
            'success': True,
            'code': currency.code,
            'symbol': currency.symbol,
            'name': currency.name,
            'exchange_rate': float(currency.exchange_rate)
        })
    except Currency.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Currency not found'})

def set_currency_ajax(request):
    """AJAX endpoint to set currency without page reload"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            currency_code = data.get('currency')
            
            if currency_code:
                currency = Currency.objects.get(code=currency_code.upper(), is_active=True)
                request.session['user_currency'] = currency.code
                request.session['user_currency_set'] = True
                request.session.modified = True
                
                response = JsonResponse({
                    'success': True,
                    'currency': currency.code,
                    'symbol': currency.symbol,
                    'message': f'Currency changed to {currency.code} ({currency.symbol})'
                })
                response.set_cookie('user_currency', currency.code, max_age=31536000)
                return response
                
        except Currency.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Currency not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@staff_member_required
def update_exchange_rates(request):
    """Update exchange rates from external API (admin only)"""
    if request.method == 'POST':
        return JsonResponse({'success': True, 'message': 'Rates updated'})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def debug_currency(request):
    """Debug view to test currency settings"""
    user_currency = request.session.get('user_currency', 'USD')
    cookie_currency = request.COOKIES.get('user_currency', 'Not set')
    currencies = Currency.objects.filter(is_active=True)
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Inter', Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
            .container {{ max-width: 800px; margin: 0 auto; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; }}
            .status {{ background: #e0f2fe; padding: 15px; border-radius: 8px; margin: 20px 0; }}
            .currency-list {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0; }}
            .currency-btn {{ background: #3b82f6; color: white; padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; }}
            .currency-btn:hover {{ background: #2563eb; }}
            .info {{ background: #fef3c7; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        </style>
        <title>Currency Debug</title>
    </head>
    <body>
        <div class="container">
            <h1>💰 Currency Debug Information</h1>
            
            <div class="status">
                <h3>Current Status:</h3>
                <p><strong>Session Currency:</strong> {user_currency}</p>
                <p><strong>Cookie Currency:</strong> {cookie_currency}</p>
                <p><strong>Display Symbol:</strong> {getattr(request, 'currency_symbol', '$')}</p>
            </div>
            
            <div class="currency-list">
                <h3>Available Currencies:</h3>
                <ul>
    """
    for c in currencies:
        html += f"<li><strong>{c.code}</strong>: {c.symbol} - {c.name} (Rate: {c.exchange_rate})</li>"
    
    html += f"""
                </ul>
            </div>
            
            <div class="currency-list">
                <h3>Switch Currency (POST Form):</h3>
                <form method="POST" action="/currency/switch/">
                    <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
                    <input type="hidden" name="next" value="/currency/debug/">
    """
    
    for c in currencies:
        html += f'<button type="submit" name="code" value="{c.code}" class="currency-btn" style="margin: 5px;">{c.code} {c.symbol}</button>'
    
    html += """
                </form>
            </div>
            
            <div class="info">
                <h3>Quick Links:</h3>
                <p><a href="/products/">Go to Products Page</a> | <a href="/currency/verify/">Verify Page</a></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return HttpResponse(html)

def force_test(request):
    """Force test page for currency"""
    return render(request, 'currency/force_test.html')

def check_session(request):
    """Check what's in the session"""
    user_currency = request.session.get('user_currency', 'NOT SET')
    cookie_currency = request.COOKIES.get('user_currency', 'NOT SET')
    
    html = f"""
    <html>
    <body style="font-family: Arial; padding: 20px;">
        <h1>Session & Cookie Check</h1>
        <p><strong>Session Currency:</strong> {user_currency}</p>
        <p><strong>Cookie Currency:</strong> {cookie_currency}</p>
        <h2>Switch Currency:</h2>
        <p>
    """
    
    currencies = Currency.objects.filter(is_active=True)
    for c in currencies:
        html += f'<a href="/currency/switch/?code={c.code}&next=/currency/check-session/" style="background: blue; color: white; padding: 5px 10px; text-decoration: none; margin: 5px; display: inline-block;">Set {c.code} ({c.symbol})</a> '
    
    html += """
        </p>
        <h2>Links:</h2>
        <p><a href="/products/">Go to Products Page</a> | <a href="/currency/debug/">Debug Page</a></p>
    </body>
    </html>
    """
    return HttpResponse(html)

def verify_currency(request):
    """Verify currency system is working"""
    return render(request, 'currency/verify.html')

def detect_currency(request):
    """API endpoint to detect and suggest currency based on IP and browser language"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0]
    else:
        ip_address = request.META.get('REMOTE_ADDR')
    
    if ip_address in ['127.0.0.1', 'localhost', '::1'] or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
        accept_language = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
        # Priority mapping - specific country codes first
        lang_map = {
            # English variants - specific countries
            'en-GB': 'GBP',
            'en-UK': 'GBP', 
            'en-US': 'USD',
            'en-CA': 'CAD',
            'en-AU': 'AUD',
            'en-NZ': 'NZD',
            'en-NG': 'NGN',
            'en-ZA': 'ZAR',
            'en-IN': 'INR',
            'en-PK': 'PKR',
            'en-BD': 'BDT',
            'en-LK': 'LKR',
            'en-PH': 'PHP',
            'en-MY': 'MYR',
            'en-SG': 'SGD',
            # Japanese
            'ja-JP': 'JPY',
            'ja': 'JPY',
            # European
            'fr-FR': 'EUR', 'fr': 'EUR',
            'de-DE': 'EUR', 'de': 'EUR',
            'es-ES': 'EUR', 'es': 'EUR',
            'it-IT': 'EUR', 'it': 'EUR',
            'pt-PT': 'EUR', 'pt': 'EUR',
            'nl-NL': 'EUR', 'nl': 'EUR',
            # Asian
            'zh-CN': 'CNY', 'zh': 'CNY',
            'ko-KR': 'KRW', 'ko': 'KRW',
            'ru-RU': 'RUB', 'ru': 'RUB',
            'ar-AE': 'AED', 'ar': 'AED',
            'hi-IN': 'INR', 'hi': 'INR',
            'tr-TR': 'TRY', 'tr': 'TRY',
            'pl-PL': 'PLN', 'pl': 'PLN',
            'sv-SE': 'SEK', 'sv': 'SEK',
            'no-NO': 'NOK', 'no': 'NOK',
            'da-DK': 'DKK', 'da': 'DKK',
            'he-IL': 'ILS', 'he': 'ILS',
            'th-TH': 'THB', 'th': 'THB',
            'vi-VN': 'VND', 'vi': 'VND',
            # Fallback for generic English
            'en': 'USD'
        }
        primary_lang = accept_language.split(',')[0] if accept_language else 'en-US'
        suggested_currency = lang_map.get(primary_lang, 'USD')
        
        return JsonResponse({
            'ip': ip_address,
            'country_code': 'LOCAL',
            'suggested_currency': suggested_currency,
            'current_currency': request.session.get('user_currency', 'USD'),
            'detection_method': 'browser_language',
            'accept_language': accept_language
        })
    
    try:
        import requests
        response = requests.get(f'http://ip-api.com/json/{ip_address}', timeout=2)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                country_code = data.get('countryCode')
                
                country_currency_map = {
                    'US': 'USD', 'GB': 'GBP', 'CA': 'CAD', 'AU': 'AUD',
                    'NG': 'NGN', 'DE': 'EUR', 'FR': 'EUR', 'ES': 'EUR',
                    'IT': 'EUR', 'NL': 'EUR', 'JP': 'JPY', 'CN': 'CNY',
                    'KR': 'KRW', 'RU': 'RUB', 'IN': 'INR', 'BR': 'BRL',
                    'MX': 'MXN', 'ZA': 'ZAR', 'CH': 'CHF', 'SE': 'SEK',
                    'NO': 'NOK', 'DK': 'DKK', 'PL': 'PLN', 'TR': 'TRY'
                }
                suggested_currency = country_currency_map.get(country_code, 'USD')
                
                return JsonResponse({
                    'ip': ip_address,
                    'country_code': country_code,
                    'country': data.get('country'),
                    'city': data.get('city'),
                    'suggested_currency': suggested_currency,
                    'current_currency': request.session.get('user_currency', 'USD'),
                    'detection_method': 'ip_geolocation'
                })
    except Exception as e:
        pass
    
    return JsonResponse({
        'ip': ip_address,
        'country_code': 'UNKNOWN',
        'suggested_currency': 'USD',
        'current_currency': request.session.get('user_currency', 'USD'),
        'detection_method': 'fallback'
    })

def diagnose_currency(request):
    """Diagnostic endpoint to check currency detection"""
    import requests
    
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    real_ip = x_forwarded_for.split(',')[0] if x_forwarded_for else request.META.get('REMOTE_ADDR')
    
    geo_data = {}
    try:
        response = requests.get(f'http://ip-api.com/json/{real_ip}', timeout=2)
        if response.status_code == 200:
            geo_data = response.json()
    except:
        pass
    
    accept_language = request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    session_currency = request.session.get('user_currency')
    cookie_currency = request.COOKIES.get('user_currency')
    manual_set = request.session.get('user_currency_set', False)
    
    from .models import Currency
    currencies = Currency.objects.filter(is_active=True).values('code', 'symbol', 'exchange_rate')
    
    return JsonResponse({
        'detected_ip': real_ip,
        'x_forwarded_for': x_forwarded_for,
        'geo_location': geo_data,
        'browser_language': accept_language,
        'session_currency': session_currency,
        'cookie_currency': cookie_currency,
        'manual_override': manual_set,
        'available_currencies': list(currencies),
        'suggested_currency': geo_data.get('countryCode', 'USD') if geo_data else 'USD'
    })
