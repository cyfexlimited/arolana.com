import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'django-insecure-arolana-super-secret-key'
DEBUG = True
ALLOWED_HOSTS = ['*']

# Jazzmin must be first in INSTALLED_APPS
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
    
    # Third party apps
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
    
    # Local apps
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

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
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

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'core.context_processors.global_context',
                'footer_menu.context_processors.footer_menus',
                'core.admin_context.admin_context',
                'core.context_processors.admin_notifications',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'arolana_config.wsgi.application'
ASGI_APPLICATION = 'arolana_config.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
]

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Crispy forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "tailwind"
CRISPY_TEMPLATE_PACK = "tailwind"

# Authentication URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Channels/WebSocket
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

# Currency settings
CURRENCY_DEFAULT = 'USD'
CURRENCY_SESSION_KEY = 'user_currency'

# ============ CKEDITOR 5 CONFIGURATION ============
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
                {'model': 'paragraph', 'title': 'Paragraph', 'class': 'ck-heading_paragraph'},
                {'model': 'heading1', 'view': 'h1', 'title': 'Heading 1', 'class': 'ck-heading_heading1'},
                {'model': 'heading2', 'view': 'h2', 'title': 'Heading 2', 'class': 'ck-heading_heading2'},
                {'model': 'heading3', 'view': 'h3', 'title': 'Heading 3', 'class': 'ck-heading_heading3'},
                {'model': 'heading4', 'view': 'h4', 'title': 'Heading 4', 'class': 'ck-heading_heading4'},
            ]
        },
        'image': {
            'toolbar': ['imageTextAlternative', 'imageStyle:full', 'imageStyle:side'],
            'styles': ['full', 'side']
        },
        'table': {
            'contentToolbar': ['tableColumn', 'tableRow', 'mergeTableCells']
        },
        'fontSize': {
            'options': [9, 11, 13, 'default', 17, 19, 21, 27, 35],
            'supportAllValues': True
        },
        'fontFamily': {
            'options': [
                'default',
                'Arial, Helvetica, sans-serif',
                'Courier New, Courier, monospace',
                'Georgia, serif',
                'Times New Roman, Times, serif',
                'Verdana, Geneva, sans-serif'
            ],
            'supportAllValues': True
        },
        'alignment': {
            'options': ['left', 'center', 'right', 'justify']
        },
        'uiColor': '#F8FAFC',
        'skin': 'moono-lisa',
    },
    'minimal': {
        'toolbar': ['bold', 'italic', 'underline', '|', 'bulletedList', 'numberedList'],
    }
}

CKEDITOR_5_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
CKEDITOR_5_UPLOAD_PATH = "uploads/ckeditor5/"
CKEDITOR_5_CUSTOM_CSS = '/static/css/ckeditor-custom.css'

# ============ AUTHENTICATION SETTINGS ============
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = 1
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_LOGOUT_ON_GET = True
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']

# Google OAuth Settings
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
    }
}

# OTP Settings
OTP_VALIDITY_MINUTES = 10
OTP_LENGTH = 6
MAX_OTP_ATTEMPTS = 3

# ============ EMAIL CONFIGURATION ============
if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    DEFAULT_FROM_EMAIL = 'webmaster@localhost'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@arolana.com')
    EMAIL_TIMEOUT = 30

# Site URL
SITE_URL = 'http://localhost:8000' if DEBUG else 'https://arolana.com'

# ============ JAZZMIN ADMIN DASHBOARD ============
JAZZMIN_SETTINGS = {
    "site_title": "Arolana Admin",
    "site_header": "Arolana",
    "site_brand": "Arolana",
    "site_logo": "/static/admin/images/arolana-logo.png",  # Full static path
    "site_logo_classes": "img-circle elevation-3",
    "site_icon": "/static/admin/images/favicon.ico",
    "welcome_sign": "Welcome to Arolana Admin",
    "copyright": "Arolana.com",
    "search_model": ["accounts.User", "products.Product", "orders.Order"],
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    "theme": "darkly",
    "dark_mode_theme": "darkly",
    "show_sidebar": True,
    "navigation_expanded": False,
    "sidebar_fixed": True,
}

# Custom CSS for Jazzmin (create file without using settings variable here)
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
css_dir = os.path.join(BASE_DIR, 'static', 'admin', 'css')
os.makedirs(css_dir, exist_ok=True)

css_file = os.path.join(css_dir, 'jazzmin-custom.css')
if not os.path.exists(css_file):
    with open(css_file, 'w') as f:
        f.write("""
/* Fix logo display */
.brand-link .brand-image {
    float: left;
    margin-right: 10px;
    max-height: 33px;
    width: auto;
}
.brand-link .brand-text {
    display: inline-block;
    vertical-align: middle;
}
/* Ensure logo shows in sidebar */
.main-sidebar .brand-link img {
    max-height: 33px;
    width: auto;
}
""")

JAZZMIN_SETTINGS["custom_css"] = "/static/admin/css/jazzmin-custom.css"

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-primary",
    "accent": "accent-primary",
    "navbar": "navbar-dark navbar-primary",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "darkly",
    "dark_mode_theme": "darkly",
}

# Twilio Settings
TWILIO_ACCOUNT_SID = ''
TWILIO_AUTH_TOKEN = ''
TWILIO_PHONE_NUMBER = ''

# Account adapter
ACCOUNT_ADAPTER = 'accounts.adapters.CustomAccountAdapter'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomSocialAccountAdapter'