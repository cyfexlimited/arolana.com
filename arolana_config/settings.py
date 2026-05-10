import os
from pathlib import Path
from decouple import config
from datetime import timedelta
import dj_database_url
import warnings
import logging

# =========================================================
# BASE DIRECTORY
# =========================================================
BASE_DIR = Path(__file__).resolve().parent.parent

# =========================================================
# SECURITY
# =========================================================
SECRET_KEY = config(
    'SECRET_KEY',
    default='django-insecure-change-this-in-production'
)

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='*'
).split(',')

# =========================================================
# CSRF TRUSTED ORIGINS
# =========================================================
CSRF_TRUSTED_ORIGINS = []

for host in ALLOWED_HOSTS:
    host = host.strip()

    if host and host not in ['localhost', '127.0.0.1', '*']:
        CSRF_TRUSTED_ORIGINS.append(f'https://{host}')
        CSRF_TRUSTED_ORIGINS.append(f'https://www.{host}')

if DEBUG:
    CSRF_TRUSTED_ORIGINS.extend([
        'http://localhost:8000',
        'http://127.0.0.1:8000',
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    ])

# =========================================================
# INSTALLED APPS
# =========================================================
INSTALLED_APPS = [
    'jazzmin',

    # Django Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sites',

    # Third Party Apps
    'rest_framework',
    'corsheaders',
    'django_filters',
    'django_ckeditor_5',
    'crispy_forms',
    'crispy_tailwind',
    'django_htmx',
    'taggit',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.facebook',
    'channels',

    # Local Apps
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
    'dashboard',
]

# =========================================================
# MIDDLEWARE
# =========================================================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',

    # WhiteNoise
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',

    # CORS
    'corsheaders.middleware.CorsMiddleware',

    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # HTMX
    'django_htmx.middleware.HtmxMiddleware',

    # Custom Middleware
    'currency.middleware.CurrencyMiddleware',
    'currency.middleware.CurrencyContextMiddleware',

    # AllAuth
    'allauth.account.middleware.AccountMiddleware',
]

# =========================================================
# URLS / ASGI / WSGI
# =========================================================
ROOT_URLCONF = 'arolana_config.urls'

WSGI_APPLICATION = 'arolana_config.wsgi.application'
ASGI_APPLICATION = 'arolana_config.asgi.application'

# =========================================================
# DATABASE
# =========================================================
if DEBUG:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config(
            default=config('DATABASE_URL'),
            conn_max_age=600,
            ssl_require=True
        )
    }

# =========================================================
# TEMPLATES
# =========================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',

        'DIRS': [
            BASE_DIR / 'templates'
        ],

        'APP_DIRS': True,

        'OPTIONS': {
            'context_processors': [
                'core.context_processors.global_context',
                'footer_menu.context_processors.footer_menus',

                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# =========================================================
# AUTH USER MODEL
# =========================================================
AUTH_USER_MODEL = 'accounts.User'

# =========================================================
# PASSWORD VALIDATORS
# =========================================================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# =========================================================
# PASSWORD HASHERS
# =========================================================
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# =========================================================
# ALLAUTH
# =========================================================
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_PASSWORD_MIN_LENGTH = 8
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_SESSION_REMEMBER = True

ACCOUNT_PASSWORD_RESET_TOKEN_EXPIRY = timedelta(days=3)

ACCOUNT_RATE_LIMITS = {
    'login_failed': '5/5m',
    'reset_password': '3/h',
    'change_password': '5/h',
    'signup': '5/h',
}

# =========================================================
# SOCIAL AUTH
# =========================================================
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {
            'access_type': 'online'
        },
        'OAUTH_PKCE_ENABLED': True,
    },

    'facebook': {
        'METHOD': 'oauth2',
        'SCOPE': ['email', 'public_profile'],
        'AUTH_PARAMS': {
            'auth_type': 'reauthenticate'
        },
        'FIELDS': [
            'id',
            'email',
            'name',
            'first_name',
            'last_name'
        ],
        'EXCHANGE_TOKEN': True,
        'VERSION': 'v13.0',
    }
}

# =========================================================
# STATIC FILES
# =========================================================
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static'
]

STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
# =========================================================
# WHITE NOISE FIX (IMPORTANT FOR YOUR ERROR)
# =========================================================

# 🔥 This fixes: bootstrap.bundle.min.js.map MissingFileError
# Optional extra safety (recommended)
WHITENOISE_SKIP_COMPRESS_EXTENSIONS = (
    'map',
)

WHITENOISE_IGNORE_EXTENSIONS = ('map',)
WHITENOISE_MANIFEST_STRICT = False
WHITENOISE_AUTOREFRESH = True
# =========================================================
# MEDIA FILES
# =========================================================
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# =========================================================
# CKEDITOR
# =========================================================
CKEDITOR_5_UPLOAD_PATH = 'uploads/ckeditor5/'

CKEDITOR_5_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

# =========================================================
# CHANNELS / REDIS
# =========================================================
if DEBUG:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [
                    config(
                        'REDIS_URL',
                        default='redis://localhost:6379'
                    )
                ]
            },
        },
    }

# =========================================================
# CACHING
# =========================================================
if DEBUG:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': config(
                'REDIS_URL',
                default='redis://localhost:6379/1'
            ),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
            'KEY_PREFIX': 'arolana',
            'TIMEOUT': 300,
        }
    }

# =========================================================
# CRISPY FORMS
# =========================================================
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# =========================================================
# EMAIL
# =========================================================
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

    EMAIL_HOST = config(
        'EMAIL_HOST',
        default='smtp.gmail.com'
    )

    EMAIL_PORT = config(
        'EMAIL_PORT',
        default=587,
        cast=int
    )

    EMAIL_USE_TLS = config(
        'EMAIL_USE_TLS',
        default=True,
        cast=bool
    )

    EMAIL_HOST_USER = config(
        'EMAIL_HOST_USER',
        default=''
    )

    EMAIL_HOST_PASSWORD = config(
        'EMAIL_HOST_PASSWORD',
        default=''
    )

DEFAULT_FROM_EMAIL = config(
    'DEFAULT_FROM_EMAIL',
    default='noreply@arolana.com'
)

# =========================================================
# SECURITY SETTINGS
# =========================================================
if DEBUG:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
else:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

SECURE_PROXY_SSL_HEADER = (
    'HTTP_X_FORWARDED_PROTO',
    'https'
)
USE_X_FORWARDED_HOST = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = 'DENY'

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 86400

# =========================================================
# JAZZMIN
# =========================================================
JAZZMIN_SETTINGS = {
    "site_title": "Arolana Admin",
    "site_header": "Arolana",
    "site_brand": "Arolana",
    "welcome_sign": "Welcome to Arolana Admin Dashboard",
    "copyright": "Arolana.com",
    "show_sidebar": True,
    "navigation_expanded": False,
    "sidebar_fixed": True,
    "theme": "darkly",
    "dark_mode_theme": "darkly",
}

# =========================================================
# LOGGING
# =========================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },

    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}

# =========================================================
# INTERNATIONALIZATION
# =========================================================
LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True
USE_TZ = True

# =========================================================
# DEFAULT AUTO FIELD
# =========================================================
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =========================================================
# SITE URL
# =========================================================
SITE_URL = config(
    'SITE_URL',
    default='http://localhost:8000'
)

# =========================================================
# REST FRAMEWORK
# =========================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],

    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],

    'DEFAULT_PAGINATION_CLASS':
        'rest_framework.pagination.PageNumberPagination',

    'PAGE_SIZE': 20,
}

# =========================================================
# CORS
# =========================================================
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',

    'https://arolana.com',
    'https://www.arolana.com',
]

CORS_ALLOW_CREDENTIALS = True

# =========================================================
# WARNINGS
# =========================================================
warnings.filterwarnings(
    'ignore',
    category=DeprecationWarning,
    module='allauth'
)

warnings.filterwarnings(
    'ignore',
    category=DeprecationWarning,
    module='django_ckeditor_5'
)

# =========================================================
# STARTUP LOGS
# =========================================================
print(
    f"🚀 Arolana running in "
    f"{'DEVELOPMENT' if DEBUG else 'PRODUCTION'} mode"
)

print(f"📍 Site URL: {SITE_URL}")