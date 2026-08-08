import re
from urllib.parse import parse_qs, urlparse


BOT_KEYWORDS = [
    "bot",
    "crawl",
    "spider",
    "slurp",
    "bingpreview",
    "facebookexternalhit",
    "whatsapp",
    "telegrambot",
    "twitterbot",
    "linkedinbot",
    "preview",
    "crawler",
    "scanner",
    "scan",
    "headless",
    "python-requests",
    "curl",
    "wget",
    "httpclient",
    "go-http-client",
]


SUSPICIOUS_SCAN_PATHS = (
    # Environment/config files
    ".env",
    "env.",
    "env.production",
    "env.local",
    "env.dev",
    "env.development",
    "env.sample",
    "env.testing",
    "env.staging",
    "env.prod",
    "env.old",
    "env.bak",
    "env.backup",
    "env.save",
    "env.live",
    "env.template",
    "env.dist",
    "env.example",

    # PHP / WordPress probes
    "phpinfo",
    "wp-admin",
    "wp-login",
    "xmlrpc.php",
    "wp-config",
    "wp-content",
    "wp-includes",
    "wp-json",
    "wordpress",
    "gravitysmtp",
    "chosen.php",
    "wp-good.php",
    "wp-header",
    "shell.php",
    "mailer.php",
    "upload.php",
    "file.php",

    # Backups / database dumps
    "backup",
    "backup.sql",
    "dump.sql",
    "database.sql",
    "db.sql",
    "mysql.sql",
    "pgsql.sql",
    "postgres.sql",
    "sqlite.sql",
    "data.sql",
    "db_backup",
    "backup.zip",
    "backup.tar",
    "backup.gz",

    # Cloud/service credentials
    ".aws",
    "aws/credentials",
    "aws.yml",
    "aws.yaml",
    "aws.json",
    "aws_s3_config",
    "aws/config",
    "credentials",
    "gcloud",
    "firebase",
    "service-account",
    "service_account",
    "google-services",
    "google-service",
    "s3_config",
    "s3-bucket",
    "s3_bucket",

    # Framework/app config probes
    "config/database",
    "config/mail",
    "config/filesystems",
    "config/app",
    "config/cache",
    "config/session",
    "appsettings",
    "appsettings.json",
    "appsettings.production",
    "appsettings.development",
    "appsettings.staging",
    "settings.json",
    "settings.local",
    "local.settings",
    "web.config",
    "server.config",

    # DevOps / deployment files
    "compose.yaml",
    "compose.yml",
    "docker-compose",
    "dockerfile",
    "terraform",
    "terraform.tfstate",
    "tfstate",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock",
    "vercel.json",
    "netlify.toml",
    "circle.yml",
    "conf.yaml",
    "conf.yml",
    "config.yml",
    "config.yaml",
    "serverless.yml",
    "serverless.yaml",

    # Common exposed folders/files
    "vendor/env",
    "public/.env",
    "public_html/.env",
    "application/.env",
    "assets/.env",
    "docker/.env",
    "frontend/.env",
    "backend/.env",
    "core/.env",
    "api/.env",
    "app/.env",
    "html/.env",
    "www/.env",
    "dev/.env",
    "site/.env",
    "test/.env",
    "config/.env",
    ".git",
    ".svn",
    ".hg",
    ".ds_store",
    "id_rsa",
    "id_dsa",
    "private.key",
    "private.pem",

    # Phishing / fake campaign / random landing-page probes
    "/lander/",
    "/land/",
    "/landing/",
    "/campaign/",
    "/quiz/",
    "/sber",
    "/sbr",
    "/sberbank",
    "/sberbank-quiz",
    "/sberquiz",
    "/testsber",
    "/rosneft",
    "/sovkombank",
    "/tink",
    "/tink_chat",
    "/cabinet",
    "/bank/",
    "/haan",
    "/bull",
    "/cosm-box",
    "/uz---cosm-box",

    # Login/account scanner paths that are not Arolana’s real login/register routes
    "/login",
    "/login/",
    "/signin",
    "/signin/",
    "/auth",
    "/auth/",
    "/account/login",
    "/user/login",
    "/admin/login",
)


SUSPICIOUS_EXTENSIONS = (
    ".php",
    ".asp",
    ".aspx",
    ".jsp",
    ".cgi",
    ".pl",
    ".sql",
    ".bak",
    ".old",
    ".save",
    ".swp",
    ".tmp",
    ".temp",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".rar",
    ".pem",
    ".key",
    ".crt",
    ".ini",
    ".log",
)


STATIC_EXTENSIONS = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
)


def get_client_ip(request):
    """
    Get real visitor IP.
    Supports Cloudflare and proxy headers.
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip.strip()

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip.strip()

    return request.META.get("REMOTE_ADDR", "") or ""


def get_country(request):
    """
    Country from Cloudflare.

    Cloudflare sends CF-IPCountry.
    In Django request.META, it usually appears as HTTP_CF_IPCOUNTRY.

    This only works when:
    - Cloudflare proxy is active/orange
    - IP Geolocation is enabled
    - visitor uses arolana.com, not Railway domain
    """
    possible_headers = [
        "HTTP_CF_IPCOUNTRY",
        "CF_IPCOUNTRY",
        "CF-IPCountry",
        "HTTP_X_COUNTRY_CODE",
        "HTTP_X_APPENGINE_COUNTRY",
    ]

    for header in possible_headers:
        country = request.META.get(header, "")
        if country:
            country = str(country).strip().upper()
            if country and country != "XX":
                return country[:10]

    return ""


def get_user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:1000]


def get_referrer(request):
    return request.META.get("HTTP_REFERER", "")[:1000]


def get_referrer_domain(referrer):
    if not referrer:
        return ""

    try:
        parsed = urlparse(referrer)
        return parsed.netloc.lower().replace("www.", "")[:255]
    except Exception:
        return ""


def get_utm_data(url):
    """
    Read marketing tracking data from URL:
    ?utm_source=whatsapp&utm_medium=status&utm_campaign=coming_soon
    """
    data = {
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "utm_content": "",
        "utm_term": "",
    }

    if not url:
        return data

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        for key in data.keys():
            value = query.get(key, [""])[0]
            data[key] = str(value).strip()[:255]

    except Exception:
        pass

    return data


def detect_traffic_source(referrer="", page_url=""):
    """
    Gives a founder-friendly traffic source name.
    """
    utm = get_utm_data(page_url)

    if utm.get("utm_source"):
        return utm.get("utm_source", "")[:100]

    domain = get_referrer_domain(referrer)

    if not domain:
        return "direct"

    if "arolana.com" in domain:
        return "internal"

    if "google." in domain:
        return "google"

    if "facebook." in domain or "fb." in domain:
        return "facebook"

    if "instagram." in domain:
        return "instagram"

    if "tiktok." in domain:
        return "tiktok"

    if "youtube." in domain or "youtu.be" in domain:
        return "youtube"

    if "linkedin." in domain:
        return "linkedin"

    if "x.com" in domain or "twitter." in domain:
        return "x-twitter"

    if "whatsapp" in domain:
        return "whatsapp"

    return domain[:100]


def is_bot_user_agent(user_agent):
    if not user_agent:
        return False

    ua = user_agent.lower()
    return any(keyword in ua for keyword in BOT_KEYWORDS)


def get_device_type(user_agent):
    ua = (user_agent or "").lower()

    if "ipad" in ua or "tablet" in ua:
        return "tablet"

    if "mobile" in ua or "iphone" in ua or "android" in ua:
        if "android" in ua and "mobile" not in ua:
            return "tablet"
        return "mobile"

    if "windows" in ua or "macintosh" in ua or "linux" in ua or "x11" in ua:
        return "desktop"

    return "unknown"


def get_browser(user_agent):
    ua = user_agent or ""

    if "Edg/" in ua or "Edge/" in ua:
        return "Edge"

    if "OPR/" in ua or "Opera" in ua:
        return "Opera"

    if "SamsungBrowser/" in ua:
        return "Samsung Internet"

    if "Chrome/" in ua and "Chromium" not in ua and "Edg/" not in ua:
        return "Chrome"

    if "Firefox/" in ua:
        return "Firefox"

    if "Safari/" in ua and "Chrome/" not in ua:
        return "Safari"

    return "Unknown"


def get_operating_system(user_agent):
    ua = (user_agent or "").lower()

    if "windows" in ua:
        return "Windows"

    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "iOS"

    if "mac os x" in ua or "macintosh" in ua:
        return "macOS"

    if "android" in ua:
        return "Android"

    if "linux" in ua:
        return "Linux"

    return "Unknown"


def normalize_path(path):
    if not path:
        return "/"
    return path[:1000]


def is_random_scanner_path(path):
    """
    Detect random scanner paths like:
    /vNyFhhL5
    /GJcjXsGY/
    /5fH7sTTJ
    /262LBNFp

    These are usually automated probes, not real customer visits.
    """
    if not path:
        return False

    clean_path = str(path).strip("/")

    if not clean_path:
        return False

    # Ignore multi-level real routes like /products/category/...
    if "/" in clean_path:
        return False

    # Ignore file paths
    if "." in clean_path:
        return False

    # Random scanner campaign slugs usually fall in this length.
    if len(clean_path) < 5 or len(clean_path) > 14:
        return False

    has_letter = any(ch.isalpha() for ch in clean_path)
    has_upper = any(ch.isupper() for ch in clean_path)
    has_lower = any(ch.islower() for ch in clean_path)
    has_digit = any(ch.isdigit() for ch in clean_path)

    # Mixed upper/lower/digit slug style: /vNyFhhL5, /GJcjXsGY, /5fH7sTTJ
    if has_letter and (has_digit or (has_upper and has_lower)):
        return True

    return False


def should_skip_tracking(request):
    """
    Keep analytics clean and fast.

    Skips:
    - admin
    - static/media files
    - analytics endpoint
    - health checks
    - hacker/scanner paths like .env, phpinfo.php, backup.sql
    - PHP/WordPress/server/config probe URLs
    - phishing/fake lander campaign paths
    - random one-segment scanner slugs
    """
    path = request.path or ""
    lower_path = path.lower()

    skip_prefixes = (
        "/admin/",
        "/static/",
        "/media/",
        "/favicon.ico",
        "/robots.txt",
        "/sitemap.xml",
        "/analytics/",
        "/visitor-analytics/",
        "/api/health",
        "/health",
        "/healthz",
    )

    if lower_path.startswith(skip_prefixes):
        return True

    if any(keyword in lower_path for keyword in SUSPICIOUS_SCAN_PATHS):
        return True

    if is_random_scanner_path(path):
        return True

    if lower_path.endswith(STATIC_EXTENSIONS):
        return True

    if lower_path.endswith(SUSPICIOUS_EXTENSIONS):
        return True

    return False


def clean_clicked_text(text):
    if not text:
        return ""

    text = re.sub(r"\s+", " ", str(text)).strip()
    return text[:500]


def clean_url(url):
    if not url:
        return ""

    return str(url).strip()[:1000]


def clean_event_type(event_type):
    allowed = {
        "button",
        "link",
        "product",
        "category",
        "landing_cta",
        "vendor",
        "whatsapp",
        "phone",
        "email",
        "video",
        "recommendation_click",
        "recommendation_impression",
        "unknown",
    }

    event_type = str(event_type or "unknown").strip().lower()

    if event_type in allowed:
        return event_type

    return "unknown"


def guess_event_type(clicked_url="", clicked_text="", element_tag="", data_event_type=""):
    if data_event_type:
        return clean_event_type(data_event_type)

    url = (clicked_url or "").lower()
    text = (clicked_text or "").lower()
    tag = (element_tag or "").lower()

    if "wa.me" in url or "whatsapp" in url:
        return "whatsapp"

    if url.startswith("tel:"):
        return "phone"

    if url.startswith("mailto:"):
        return "email"

    if "youtube.com" in url or "youtu.be" in url or "video" in text:
        return "video"

    if "/products/" in url or "/product/" in url:
        return "product"

    if "/categories/" in url or "/category/" in url:
        return "category"

    if "/vendors/" in url or "/vendor/" in url or "/store/" in url:
        return "vendor"

    if "landing" in url or "campaign" in url or "cta" in text or "shop now" in text or "learn more" in text:
        return "landing_cta"

    if tag == "button":
        return "button"

    if tag == "a":
        return "link"

    return "unknown"