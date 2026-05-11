from django.conf import settings

def blog_settings(request):
    """
    Context processor for blog settings.
    Makes ad display settings available in all blog templates.
    """
    
    return {
        # Main content ad controls
        'display_ad_top': getattr(settings, 'DISPLAY_ARTICLE_TOP_AD', True),
        'display_ad_after_header': getattr(settings, 'DISPLAY_ARTICLE_AFTER_HEADER_AD', True),
        'display_ad_mid_1': getattr(settings, 'DISPLAY_ARTICLE_MID_AD', True),
        'display_ad_native': getattr(settings, 'DISPLAY_ARTICLE_NATIVE_AD', True),
        'display_ad_before_conclusion': getattr(settings, 'DISPLAY_ARTICLE_BEFORE_CONCLUSION_AD', True),
        'display_ad_after_author': getattr(settings, 'DISPLAY_ARTICLE_AFTER_AUTHOR_AD', True),
        'display_ad_footer': getattr(settings, 'DISPLAY_ARTICLE_FOOTER_AD', True),
        
        # Sidebar ad controls
        'display_sidebar_search': getattr(settings, 'DISPLAY_SIDEBAR_SEARCH', True),
        'display_sidebar_ad_top': getattr(settings, 'DISPLAY_SIDEBAR_TOP_AD', True),
        'display_sidebar_newsletter': getattr(settings, 'DISPLAY_SIDEBAR_NEWSLETTER', True),
        'display_sidebar_ad_mid': getattr(settings, 'DISPLAY_SIDEBAR_MID_AD', True),
        'display_sidebar_popular': getattr(settings, 'DISPLAY_SIDEBAR_POPULAR', True),
        'display_sidebar_ad_bottom': getattr(settings, 'DISPLAY_SIDEBAR_BOTTOM_AD', True),
        'display_sidebar_categories': getattr(settings, 'DISPLAY_SIDEBAR_CATEGORIES', True),
        'display_sidebar_sticky': getattr(settings, 'DISPLAY_SIDEBAR_STICKY_AD', True),
        
        # Carousel settings (counts and intervals)
        'carousel_top_count': getattr(settings, 'ARTICLE_CAROUSEL_TOP_COUNT', 1),
        'carousel_top_interval': getattr(settings, 'ARTICLE_CAROUSEL_TOP_INTERVAL', 8000),
        'carousel_native_count': getattr(settings, 'ARTICLE_CAROUSEL_NATIVE_COUNT', 1),
        'carousel_native_interval': getattr(settings, 'ARTICLE_CAROUSEL_NATIVE_INTERVAL', 5000),
        'carousel_footer_count': getattr(settings, 'ARTICLE_CAROUSEL_FOOTER_COUNT', 1),
        'carousel_footer_interval': getattr(settings, 'ARTICLE_CAROUSEL_FOOTER_INTERVAL', 8000),
        'carousel_sidebar_top_count': getattr(settings, 'SIDEBAR_CAROUSEL_TOP_COUNT', 2),
        'carousel_sidebar_top_interval': getattr(settings, 'SIDEBAR_CAROUSEL_TOP_INTERVAL', 5000),
        'carousel_sidebar_mid_count': getattr(settings, 'SIDEBAR_CAROUSEL_MID_COUNT', 2),
        'carousel_sidebar_mid_interval': getattr(settings, 'SIDEBAR_CAROUSEL_MID_INTERVAL', 4000),
        'carousel_sidebar_bottom_count': getattr(settings, 'SIDEBAR_CAROUSEL_BOTTOM_COUNT', 1),
        'carousel_sidebar_bottom_interval': getattr(settings, 'SIDEBAR_CAROUSEL_BOTTOM_INTERVAL', 6000),
        'carousel_sidebar_sticky_count': getattr(settings, 'SIDEBAR_CAROUSEL_STICKY_COUNT', 1),
        'carousel_sidebar_sticky_interval': getattr(settings, 'SIDEBAR_CAROUSEL_STICKY_INTERVAL', 8000),
    }