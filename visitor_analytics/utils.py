import re


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
]


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
    Use Cloudflare country header if available.
    Keep blank if unavailable.
    Later, this can be upgraded with GeoIP.
    """
    country = request.META.get("HTTP_CF_IPCOUNTRY", "")
    if country and country.upper() != "XX":
        return country.upper()
    return ""


def get_user_agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:1000]


def get_referrer(request):
    return request.META.get("HTTP_REFERER", "")[:1000]


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

    if "Chrome/" in ua and "Chromium" not in ua and "Edg/" not in ua:
        return "Chrome"

    if "Firefox/" in ua:
        return "Firefox"

    if "Safari/" in ua and "Chrome/" not in ua:
        return "Safari"

    if "SamsungBrowser/" in ua:
        return "Samsung Internet"

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


def should_skip_tracking(request):
    """
    Keep analytics fast and clean.
    Do not track admin, static, media, health checks, analytics endpoints, etc.
    """
    path = request.path or ""

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

    if path.startswith(skip_prefixes):
        return True

    if path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".map")):
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
        "unknown",
    }

    event_type = str(event_type or "unknown").strip().lower()

    if event_type in allowed:
        return event_type

    return "unknown"


def guess_event_type(clicked_url="", clicked_text="", element_tag="", data_event_type=""):
    """
    Detect click type automatically from URL/text/tag/data attribute.
    """
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