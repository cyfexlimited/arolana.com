from django import template
from django.template.defaultfilters import stringfilter
from decimal import Decimal
import re
from datetime import timedelta

register = template.Library()

# ========== HELPER FUNCTIONS ==========

def parse_youtube_id(url):
    """Extract YouTube video ID from URL"""
    if not url:
        return None
    
    patterns = [
        r'youtube\.com/watch\?v=([^&]+)',
        r'youtu\.be/([^?]+)',
        r'youtube\.com/embed/([^?]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def parse_vimeo_id(url):
    """Extract Vimeo video ID from URL"""
    if not url:
        return None
    match = re.search(r'vimeo\.com/(\d+)', url)
    return match.group(1) if match else None

# ========== VIDEO FILTERS ==========

@register.filter
def extract_video_id(url):
    """Extract YouTube or Vimeo video ID from URL"""
    if not url:
        return None
    
    video_id = parse_youtube_id(url)
    if video_id:
        return video_id
    
    video_id = parse_vimeo_id(url)
    return video_id

@register.filter
def get_embed_url(url):
    """Convert YouTube/Vimeo URL to embed URL"""
    video_id = parse_youtube_id(url)
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}"
    
    video_id = parse_vimeo_id(url)
    if video_id:
        return f"https://player.vimeo.com/video/{video_id}"
    
    return url

@register.filter
def get_thumbnail_url(url):
    """Get YouTube thumbnail URL"""
    video_id = parse_youtube_id(url)
    if video_id:
        return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    return '/static/images/video-placeholder.png'

@register.filter
def get_thumbnail(video_url, size='hqdefault'):
    """Extract YouTube thumbnail from video URL"""
    if not video_url:
        return '/static/images/video-placeholder.png'
    
    video_id = parse_youtube_id(video_url)
    if video_id:
        if size == 'maxresdefault':
            return f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg'
        return f'https://img.youtube.com/vi/{video_id}/{size}.jpg'
    
    video_id = parse_vimeo_id(video_url)
    if video_id:
        return f'https://vumbnail.com/{video_id}.jpg'
    
    return '/static/images/video-placeholder.png'

# ========== CURRENCY FILTERS ==========

@register.filter
def currency(value, request):
    """Format price with currency symbol based on user's currency"""
    if not value:
        return '₦0'
    
    try:
        # Get user currency from session or cookie
        user_currency = None
        if request and hasattr(request, 'session'):
            user_currency = request.session.get('user_currency')
        if not user_currency and request and hasattr(request, 'COOKIES'):
            user_currency = request.COOKIES.get('user_currency')
        if not user_currency:
            user_currency = 'NGN'
        
        # Currency symbols mapping
        currency_symbols = {
            'NGN': '₦',
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'INR': '₹',
            'AUD': 'A$',
            'CAD': 'C$',
            'CNY': '¥',
        }
        
        symbol = currency_symbols.get(user_currency, user_currency)
        
        # Try to convert price using database rates
        try:
            from currency.models import Currency
            usd_currency = Currency.objects.filter(code='USD', is_active=True).first()
            target_currency = Currency.objects.filter(code=user_currency, is_active=True).first()
            
            if usd_currency and target_currency and usd_currency != target_currency:
                # Convert from USD to target currency
                rate = float(target_currency.exchange_rate) / float(usd_currency.exchange_rate)
                converted = float(value) * rate
                
                if user_currency == 'NGN':
                    formatted_value = f"{converted:,.0f}"
                else:
                    formatted_value = f"{converted:,.2f}"
                return f"{symbol}{formatted_value}"
            else:
                # Fallback to direct display with symbol
                if isinstance(value, (int, float)):
                    if user_currency == 'NGN':
                        formatted_value = f"{value:,.0f}"
                    else:
                        formatted_value = f"{value:,.2f}"
                    return f"{symbol}{formatted_value}"
                return f"{symbol}{value}"
        except Exception as e:
            print(f"Currency conversion error: {e}")
            # Fallback to direct display
            if isinstance(value, (int, float)):
                if user_currency == 'NGN':
                    formatted_value = f"{value:,.0f}"
                else:
                    formatted_value = f"{value:,.2f}"
                return f"{symbol}{formatted_value}"
            return f"{symbol}{value}"
            
    except Exception as e:
        print(f"Currency filter error: {e}")
        return f"₦{value}"

@register.simple_tag(takes_context=True)
def current_currency_symbol(context):
    """Get current currency symbol"""
    request = context.get('request')
    if request and hasattr(request, 'session'):
        currency = request.session.get('user_currency', 'NGN')
    else:
        currency = 'NGN'
    
    symbols = {'NGN': '₦', 'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'INR': '₹', 'AUD': 'A$', 'CAD': 'C$'}
    return symbols.get(currency, '₦')

@register.simple_tag(takes_context=True)
def current_currency_code(context):
    """Get current currency code"""
    request = context.get('request')
    if request and hasattr(request, 'session'):
        return request.session.get('user_currency', 'NGN')
    return 'NGN'

# ========== RATING FILTERS ==========

@register.filter
def rating_stars(rating):
    """Convert numeric rating to star HTML"""
    if not rating:
        rating = 0
    
    try:
        rating = float(rating)
        full_stars = int(rating)
        half_star = 1 if (rating % 1) >= 0.5 else 0
        empty_stars = 5 - full_stars - half_star
        
        stars = []
        for _ in range(full_stars):
            stars.append('<i class="fas fa-star text-yellow-400"></i>')
        if half_star:
            stars.append('<i class="fas fa-star-half-alt text-yellow-400"></i>')
        for _ in range(empty_stars):
            stars.append('<i class="far fa-star text-yellow-400"></i>')
        
        return ''.join(stars)
    except Exception:
        return '<i class="fas fa-star text-gray-300"></i>' * 5

@register.filter
def rating_percentage(rating):
    """Convert rating to percentage (0-100)"""
    try:
        return int((float(rating) / 5) * 100)
    except (ValueError, TypeError):
        return 0

@register.filter
def get_review_stats(reviews):
    """Get review statistics from review queryset"""
    if not reviews:
        return {'total': 0, 'average': 0, 'distribution': {1:0, 2:0, 3:0, 4:0, 5:0}}
    
    total = reviews.count()
    if total == 0:
        return {'total': 0, 'average': 0, 'distribution': {1:0, 2:0, 3:0, 4:0, 5:0}}
    
    from django.db.models import Avg
    average = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
    
    distribution = {1:0, 2:0, 3:0, 4:0, 5:0}
    for rating in range(1, 6):
        distribution[rating] = reviews.filter(rating=rating).count()
    
    return {
        'total': total,
        'average': round(average, 1),
        'distribution': distribution,
    }

# ========== PRICE & DISCOUNT FILTERS ==========

@register.filter
def discount_price(price, compare_price):
    """Calculate discount percentage"""
    try:
        if compare_price and compare_price > price:
            return int(((compare_price - price) / compare_price) * 100)
        return 0
    except (ValueError, TypeError):
        return 0

@register.filter
def final_price(product, variant=None):
    """Get final price including variant adjustment"""
    base_price = float(product.price)
    if variant and hasattr(variant, 'price_adjustment'):
        return base_price + float(variant.price_adjustment)
    return base_price

@register.filter
def get_price_range(products):
    """Get min and max price from products queryset"""
    if not products:
        return {'min': 0, 'max': 0}
    
    min_price = float('inf')
    max_price = float('-inf')
    
    for product in products:
        price = float(product.price)
        min_price = min(min_price, price)
        max_price = max(max_price, price)
    
    return {
        'min': min_price if min_price != float('inf') else 0, 
        'max': max_price if max_price != float('-inf') else 0
    }

@register.filter
def calculate_delivery_date(days_min, days_max):
    """Calculate estimated delivery date range"""
    from django.utils import timezone
    today = timezone.now().date()
    start_date = today + timedelta(days=days_min)
    end_date = today + timedelta(days=days_max)
    
    if start_date == end_date:
        return start_date.strftime('%b %d')
    return f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"

# ========== VARIANT FILTERS ==========

@register.filter
def get_variant_price(variant_data, variant_id):
    """Get variant price from JSON data"""
    if not variant_data or not variant_id:
        return None
    return variant_data.get(str(variant_id), {}).get('price')

@register.filter
def get_variant_stock(variant_data, variant_id):
    """Get variant stock from JSON data"""
    if not variant_data or not variant_id:
        return None
    return variant_data.get(str(variant_id), {}).get('stock')

@register.filter
def get_variant_sku(variant_data, variant_id):
    """Get variant SKU from JSON data"""
    if not variant_data or not variant_id:
        return None
    return variant_data.get(str(variant_id), {}).get('sku')

@register.filter
def get_variant_image(variant_data, variant_id):
    """Get variant image from JSON data"""
    if not variant_data or not variant_id:
        return None
    return variant_data.get(str(variant_id), {}).get('image')

# ========== DICTIONARY & LIST FILTERS ==========

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key, 0)
    return 0

@register.filter
def split(value, delimiter=','):
    """Split string by delimiter"""
    if not value:
        return []
    if isinstance(value, str):
        return value.split(delimiter)
    return value

@register.filter
def extract_filename(value):
    """Extract filename from path"""
    return value.split('/')[-1] if '/' in value else value

@register.filter
def truncate_chars(value, max_length):
    """Truncate string to max characters"""
    if not value:
        return ''
    if len(value) <= max_length:
        return value
    return value[:max_length - 3] + '...'

@register.filter
def format_number(value):
    """Format number with commas"""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return value

@register.filter
def default(value, default_value):
    """Return default value if value is None or empty"""
    if value is None or value == '':
        return default_value
    return value

@register.filter
def dict_lookup(dictionary, key):
    """Look up value in dictionary by key"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def is_in_csv(csv_string, value):
    """Check if value is in comma-separated string"""
    if not csv_string:
        return False
    values = [v.strip() for v in csv_string.split(',')]
    return str(value).strip() in values

@register.filter
def get_range(value):
    """Create a range for loop"""
    try:
        return range(int(value))
    except (ValueError, TypeError):
        return range(0)

@register.filter
def list_contains(lst, item):
    """Check if list contains item"""
    if not lst:
        return False
    return item in lst

@register.filter
def first_item(lst):
    """Get first item from list"""
    if not lst:
        return None
    return lst[0]

@register.filter
def last_item(lst):
    """Get last item from list"""
    if not lst:
        return None
    return lst[-1]

# ========== WISHLIST FILTERS ==========

@register.filter
def is_in_wishlist(product, user):
    """Check if product is in user's wishlist"""
    if not user or not user.is_authenticated:
        return False
    from products.models import Wishlist
    return Wishlist.objects.filter(user=user, product=product).exists()

# ========== MATH FILTERS ==========

@register.filter
def mul(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def div(value, arg):
    """Divide the value by the argument"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def multiply(value, arg):
    """Alias for mul"""
    return mul(value, arg)

@register.filter
def divide(value, arg):
    """Alias for div"""
    return div(value, arg)

@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return value

@register.filter
def add(value, arg):
    """Add arg to value"""
    try:
        return float(value) + float(arg)
    except (ValueError, TypeError):
        return value

@register.filter
def percentage(value, total):
    """Calculate percentage"""
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError):
        return 0

# ========== TIME FILTERS ==========

@register.filter
def time_ago(date):
    """Calculate time ago from date"""
    if not date:
        return ''
    from django.utils import timezone
    now = timezone.now()
    diff = now - date
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return 'just now'
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f'{minutes} minute{"s" if minutes > 1 else ""} ago'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours} hour{"s" if hours > 1 else ""} ago'
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f'{days} day{"s" if days > 1 else ""} ago'
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f'{weeks} week{"s" if weeks > 1 else ""} ago'
    else:
        return date.strftime('%b %d, %Y')

# ========== QUERY TRANSFORM ==========

@register.simple_tag
def query_transform(request, **kwargs):
    """Transform query string with new parameters"""
    updated = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            updated.pop(key, None)
        else:
            updated[key] = value
    return updated.urlencode()

@register.simple_tag
def active_category(request, slug):
    """Check if category is active in URL"""
    if request.GET.get('category') == slug:
        return 'active'
    return ''

# ========== JSON HELPERS ==========

@register.filter
def safe_json(value):
    """Convert value to safe JSON string"""
    import json
    try:
        return json.dumps(value)
    except:
        return '{}'