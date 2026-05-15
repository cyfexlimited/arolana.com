import os
from pathlib import Path
from decouple import config
from datetime import timedelta
import warnings
import logging
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ============ SECURITY & ENVIRONMENT ============
SECRET_KEY = config('SECRET_KEY', default='django-insecure-arolana-super-secret-key')
DEBUG = config('DEBUG', default=False, cast=bool)

def csv_config(name, default=''):
    return [
        item.strip().strip('"').strip("'")
        for item in config(name, default=default).split(',')
        if item.strip()
    ]

ALLOWED_HOSTS = csv_config(
    'ALLOWED_HOSTS',
    default='arolana.com,www.arolana.com,localhost,127.0.0.1'
)

REQUIRED_ALLOWED_HOSTS = [
    'arolana.com',
    'www.arolana.com',
    'localhost',
    '127.0.0.1',
    'agile-wonder-production-dfa7.up.railway.app',
    '.railway.app',
    '.up.railway.app',
    'healthcheck.railway.app',
]

RAILWAY_PUBLIC_DOMAIN = config('RAILWAY_PUBLIC_DOMAIN', default='')
if RAILWAY_PUBLIC_DOMAIN:
    REQUIRED_ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

for host in REQUIRED_ALLOWED_HOSTS:
    if host and host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

CSRF_TRUSTED_ORIGINS = [
    'https://arolana.com',
    'https://www.arolana.com',
    'https://agile-wonder-production-dfa7.up.railway.app',
    'https://*.railway.app',
    'https://*.up.railway.app',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# ============ AD SETTINGS ============
DISPLAY_ARTICLE_TOP_AD = True
DISPLAY_ARTICLE_AFTER_HEADER_AD = True
DISPLAY_ARTICLE_MID_AD = True
DISPLAY_ARTICLE_NATIVE_AD = True
DISPLAY_ARTICLE_BEFORE_CONCLUSION_AD = True
DISPLAY_ARTICLE_AFTER_AUTHOR_AD = True
DISPLAY_ARTICLE_FOOTER_AD = True

DISPLAY_SIDEBAR_SEARCH = True
DISPLAY_SIDEBAR_TOP_AD = True
DISPLAY_SIDEBAR_NEWSLETTER = True
DISPLAY_SIDEBAR_MID_AD = True
DISPLAY_SIDEBAR_POPULAR = True
DISPLAY_SIDEBAR_BOTTOM_AD = True
DISPLAY_SIDEBAR_CATEGORIES = True
DISPLAY_SIDEBAR_STICKY_AD = True

ARTICLE_CAROUSEL_TOP_COUNT = 1
ARTICLE_CAROUSEL_TOP_INTERVAL = 8000
ARTICLE_CAROUSEL_NATIVE_COUNT = 1
ARTICLE_CAROUSEL_NATIVE_INTERVAL = 5000
ARTICLE_CAROUSEL_FOOTER_COUNT = 1
ARTICLE_CAROUSEL_FOOTER_INTERVAL = 8000
SIDEBAR_CAROUSEL_TOP_COUNT = 2
SIDEBAR_CAROUSEL_TOP_INTERVAL = 5000
SIDEBAR_CAROUSEL_MID_COUNT = 2
SIDEBAR_CAROUSEL_MID_INTERVAL = 4000
SIDEBAR_CAROUSEL_BOTTOM_COUNT = 1
SIDEBAR_CAROUSEL_BOTTOM_INTERVAL = 6000
SIDEBAR_CAROUSEL_STICKY_COUNT = 1
SIDEBAR_CAROUSEL_STICKY_INTERVAL = 8000

# ============ INSTALLED APPS ============
INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sites',
    'taggit',
    'rest_framework',
    'corsheaders',
    'django_ckeditor_5',
    'crispy_forms',
    'crispy_tailwind',
    'django_htmx',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.facebook',
    'core',
    'accounts',
    'vendors',
    'products',
    'orders',
    'blog',
    'chat',
    'notifications',
    'hero_banners',
    'footer_menu',
    'ads',
    'contact',
    'homepage',
    'newsletter',
    'pages',
    'videos',
    'manufacturers',
    'subscriptions',
    'kyc',
    'reports',
    'currency',
    'search_ai',
    'dashboard',
    'channels',
]

# ============ MIDDLEWARE ============
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'currency.middleware.CurrencyMiddleware',
    'currency.middleware.CurrencyContextMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'arolana_config.urls'
WSGI_APPLICATION = 'arolana_config.wsgi.application'
ASGI_APPLICATION = 'arolana_config.asgi.application'

# ============ DATABASE ============
DATABASE_URL = config('DATABASE_URL', default=None)
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ============ TEMPLATES ============
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'core.context_processors.global_context',
                'footer_menu.context_processors.footer_menus',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'blog.context_processors.blog_settings',
            ],
        },
    },
]

# ============ AUTHENTICATION ============
AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

# ============ ALLAUTH ============
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PASSWORD_MIN_LENGTH = 8
ACCOUNT_PASSWORD_RESET_TOKEN_EXPIRY = timedelta(days=3)

ACCOUNT_RATE_LIMITS = {
    'login_failed': '5/5m',
    'reset_password': '3/1h',
    'change_password': '5/1h',
    'signup': '5/1h',
}

ACCOUNT_ADAPTER = 'accounts.adapters.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomSocialAccountAdapter'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_STORE_TOKENS = True

GOOGLE_OAUTH_CLIENT_ID = config(
    'GOOGLE_OAUTH_CLIENT_ID',
    default=config('GOOGLE_CLIENT_ID', default='')
)
GOOGLE_OAUTH_CLIENT_SECRET = config(
    'GOOGLE_OAUTH_CLIENT_SECRET',
    default=config('GOOGLE_CLIENT_SECRET', default='')
)

GOOGLE_SOCIALACCOUNT_PROVIDER = {
    'SCOPE': ['profile', 'email'],
    'AUTH_PARAMS': {
        'access_type': 'online',
        'prompt': 'select_account',
    },
    'OAUTH_PKCE_ENABLED': True,
}
if GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET:
    GOOGLE_SOCIALACCOUNT_PROVIDER['APP'] = {
        'client_id': GOOGLE_OAUTH_CLIENT_ID,
        'secret': GOOGLE_OAUTH_CLIENT_SECRET,
        'key': '',
        'name': 'Google',
    }

SOCIALACCOUNT_PROVIDERS = {
    'google': GOOGLE_SOCIALACCOUNT_PROVIDER,
    'facebook': {
        'METHOD': 'oauth2',
        'SCOPE': ['email', 'public_profile'],
        'AUTH_PARAMS': {'auth_type': 'reauthenticate'},
        'FIELDS': ['id', 'email', 'name', 'first_name', 'last_name'],
        'EXCHANGE_TOKEN': True,
        'VERSION': 'v13.0',
    }
}

# ============ STATIC & MEDIA ============
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = config('MEDIA_URL', default='/media/')
if not MEDIA_URL.endswith('/'):
    MEDIA_URL = f'{MEDIA_URL}/'
MEDIA_ROOT = BASE_DIR / 'media'
SERVE_MEDIA = config('SERVE_MEDIA', default=False, cast=bool)

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default='')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='auto')
AWS_S3_ADDRESSING_STYLE = config('AWS_S3_ADDRESSING_STYLE', default='path')
AWS_DEFAULT_ACL = config('AWS_DEFAULT_ACL', default='public-read')
AWS_S3_FILE_OVERWRITE = config('AWS_S3_FILE_OVERWRITE', default=False, cast=bool)
AWS_QUERYSTRING_AUTH = config('AWS_QUERYSTRING_AUTH', default=False, cast=bool)
AWS_QUERYSTRING_EXPIRE = config('AWS_QUERYSTRING_EXPIRE', default=3600, cast=int)
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': config('AWS_S3_CACHE_CONTROL', default='max-age=31536000, public'),
}
OPTIMIZED_MEDIA_ENABLED = config('OPTIMIZED_MEDIA_ENABLED', default=True, cast=bool)

if AWS_STORAGE_BUCKET_NAME and AWS_S3_ENDPOINT_URL:
    MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/media/"
    STORAGES['default'] = {
        'BACKEND': 'core.storages.CachedS3MediaStorage',
    }

# ============ CKEDITOR 5 ============
CKEDITOR_5_CONFIGS = {
    'default': {
        'toolbar': [
            'heading', '|', 'bold', 'italic', 'underline', 'strikethrough',
            '|', 'bulletedList', 'numberedList', 'todoList',
            '|', 'link', 'imageUpload', 'blockQuote', 'codeBlock',
            '|', 'insertTable', 'mediaEmbed', 'fontSize', 'fontFamily',
            '|', 'alignment', 'highlight', 'sourceEditing'
        ],
        'heading': {
            'options': [
                {'model': 'paragraph', 'title': 'Paragraph'},
                {'model': 'heading1', 'view': 'h1', 'title': 'Heading 1'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Heading 2'},
            ]
        },
        'image': {'toolbar': ['imageTextAlternative', 'imageStyle:full', 'imageStyle:side']},
        'table': {'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells']},
        'fontSize': {'options': [9, 11, 13, 'default', 17, 19, 21, 27, 35], 'supportAllValues': True},
        'fontFamily': {'options': ['default', 'Arial', 'Courier New', 'Georgia', 'Times New Roman', 'Verdana']},
        'alignment': {'options': ['left', 'center', 'right', 'justify']},
    },
}
CKEDITOR_5_UPLOAD_PATH = 'uploads/ckeditor5/'
CKEDITOR_5_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# ============ CHANNELS ============
REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

CURRENCY_DEFAULT = 'USD'
CURRENCY_SESSION_KEY = 'user_currency'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'tailwind'
CRISPY_TEMPLATE_PACK = 'tailwind'

# ============ EMAIL ============
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=False, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=20, cast=int)
EMAIL_ALLOW_UNAUTHENTICATED_SMTP = config('EMAIL_ALLOW_UNAUTHENTICATED_SMTP', default=False, cast=bool)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER or 'noreply@arolana.com')
SERVER_EMAIL = config('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)
EMAIL_CONFIGURED = (
    EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend'
    or (
        bool(EMAIL_HOST)
        and bool(EMAIL_PORT)
        and bool(DEFAULT_FROM_EMAIL)
        and (
            EMAIL_ALLOW_UNAUTHENTICATED_SMTP
            or (bool(EMAIL_HOST_USER) and bool(EMAIL_HOST_PASSWORD))
        )
    )
)

# ============ SECURITY ============
if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    CSRF_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SAMESITE = 'Lax'
else:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
    SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)
    CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
    SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
    CSRF_COOKIE_SAMESITE = 'Strict'
    SESSION_COOKIE_SAMESITE = 'Strict'

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_AGE = 86400
SESSION_COOKIE_HTTPONLY = True

# ============ JAZZMIN ============
os.makedirs(os.path.join(BASE_DIR, 'static', 'admin', 'css'), exist_ok=True)

JAZZMIN_SETTINGS = {
    'site_title': 'Arolana Admin',
    'site_header': 'Arolana',
    'site_brand': 'Arolana',
    'site_logo': '/static/admin/images/arolana-logo.png',
    'site_logo_classes': 'img-circle elevation-3',
    'welcome_sign': 'Welcome to Arolana Admin Dashboard',
    'copyright': 'Arolana.com',
    'search_model': ['accounts.User', 'products.Product', 'orders.Order'],
    'show_sidebar': True,
    'navigation_expanded': False,
    'sidebar_fixed': True,
    'theme': 'darkly',
    'dark_mode_theme': 'darkly',
    'changeform_format': 'horizontal_tabs',
    'show_ui_builder': False,
}

JAZZMIN_UI_TWEAKS = {
    'navbar_small_text': False,
    'brand_small_text': False,
    'brand_colour': 'navbar-primary',
    'accent': 'accent-primary',
    'navbar': 'navbar-dark navbar-primary',
    'no_navbar_border': False,
    'navbar_fixed': True,
    'sidebar_fixed': True,
    'sidebar': 'sidebar-dark-primary',
    'sidebar_nav_small_text': False,
    'sidebar_disable_expand': False,
    'theme': 'darkly',
    'dark_mode_theme': 'darkly',
}

# ============ LOGGING ============
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {'format': '{levelname} {asctime} {module} {message}', 'style': '{'},
        'simple': {'format': '{levelname} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
        'file': {'class': 'logging.FileHandler', 'filename': BASE_DIR / 'logs/arolana.log', 'formatter': 'verbose'},
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO'},
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': True},
    },
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SITE_URL = config('SITE_URL', default='https://arolana.com')
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# ============ CACHING ============
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
            'KEY_PREFIX': 'arolana',
            'TIMEOUT': 300,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# ============ REST FRAMEWORK ============
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
    },
}

# ============ CORS ============
CORS_ALLOWED_ORIGINS = [
    'https://arolana.com',
    'https://www.arolana.com',
    'https://agile-wonder-production-dfa7.up.railway.app',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

CORS_ALLOW_CREDENTIALS = True

# ============ SILENCE WARNINGS ============
warnings.filterwarnings('ignore', category=DeprecationWarning, module='allauth')
warnings.filterwarnings('ignore', category=DeprecationWarning, module='django_ckeditor_5')
warnings.filterwarnings('ignore', category=RuntimeWarning, module='products.models')

if DEBUG:
    logging.getLogger('django.request').setLevel(logging.ERROR)
    logging.getLogger('django.server').setLevel(logging.ERROR)
    logging.getLogger('currency.middleware').setLevel(logging.WARNING)
    warnings.filterwarnings('ignore', message='.*development server.*')
    warnings.filterwarnings('ignore', module='currency.middleware')

class Suppress404Filter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return not ('favicon.ico' in msg or 'wishlist/count' in msg)

logging.getLogger('django.request').addFilter(Suppress404Filter())
