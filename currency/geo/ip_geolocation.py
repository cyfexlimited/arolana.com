import requests
from django.core.cache import cache

class IPGeolocationService:
    """IP geolocation service using multiple free APIs"""
    
    def __init__(self):
        self.apis = [
            ('http://ip-api.com/json/{ip}', lambda x: x.get('countryCode')),
            ('https://ipapi.co/{ip}/json/', lambda x: x.get('country_code')),
            ('https://freeipapi.com/api/json/{ip}', lambda x: x.get('countryCode')),
        ]
    
    def get_country_code(self, ip_address):
        """Get country code from IP address"""
        # Only skip truly local IPs
        if ip_address in ['127.0.0.1', 'localhost', '::1']:
            return None
        
        # Check cache
        cache_key = f"ip_geo_{ip_address}"
        cached = cache.get(cache_key)
        if cached:
            return cached
        
        # Try each API
        for api_template, parser in self.apis:
            try:
                api_url = api_template.format(ip=ip_address)
                response = requests.get(api_url, timeout=3)
                
                if response.status_code == 200:
                    data = response.json()
                    country_code = parser(data)
                    
                    if country_code and len(country_code) == 2:
                        cache.set(cache_key, country_code, 86400)
                        return country_code
                        
            except Exception as e:
                print(f"IP geolocation API error: {e}")
                continue
        
        return None

# Country to currency mapping (including Japan)
COUNTRY_CURRENCY_MAP = {
    # Asia
    'JP': 'JPY',  # Japan - Yen
    'CN': 'CNY', 'IN': 'INR', 'KR': 'KRW', 'SG': 'SGD',
    'MY': 'MYR', 'TH': 'THB', 'VN': 'VND', 'ID': 'IDR', 'PH': 'PHP',
    'PK': 'PKR', 'BD': 'BDT', 'LK': 'LKR', 'NP': 'NPR', 'HK': 'HKD',
    'TW': 'TWD', 'SA': 'SAR', 'AE': 'AED', 'IL': 'ILS', 'KW': 'KWD',
    'QA': 'QAR', 'OM': 'OMR', 'BH': 'BHD',
    # Africa
    'NG': 'NGN', 'ZA': 'ZAR', 'EG': 'EGP', 'KE': 'KES', 'GH': 'GHS',
    'MA': 'MAD', 'TN': 'TND', 'DZ': 'DZD', 'UG': 'UGX', 'TZ': 'TZS',
    # Americas
    'US': 'USD', 'CA': 'CAD', 'MX': 'MXN', 'BR': 'BRL', 'AR': 'ARS',
    'CL': 'CLP', 'CO': 'COP', 'PE': 'PEN', 'VE': 'VES',
    # Europe
    'GB': 'GBP', 'DE': 'EUR', 'FR': 'EUR', 'ES': 'EUR', 'IT': 'EUR',
    'NL': 'EUR', 'BE': 'EUR', 'CH': 'CHF', 'SE': 'SEK', 'NO': 'NOK',
    'DK': 'DKK', 'PL': 'PLN', 'RU': 'RUB', 'TR': 'TRY', 'UA': 'UAH',
    # Oceania
    'AU': 'AUD', 'NZ': 'NZD',
}

def get_currency_for_country(country_code):
    """Map country code to currency"""
    return COUNTRY_CURRENCY_MAP.get(country_code, 'USD')
