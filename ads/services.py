from django.utils import timezone
from django.core.cache import cache
from .models import AdBanner, AdPlacement, AdImpression
import random
import logging

logger = logging.getLogger(__name__)

class AdService:
    """Advanced ad service with rotation, targeting, and analytics"""
    
    def __init__(self):
        self.cache_timeout = 300  # 5 minutes cache
    
    def get_ad(self, placement_slug, user=None, request=None):
        """Get an ad for a specific placement with advanced rotation"""
        try:            placement = AdPlacement.objects.get(slug=placement_slug, is_active=True)
        except AdPlacement.DoesNotExist:
            logger.warning(f"Placement not found: {placement_slug}")
            return None
        
        now = timezone.now()
        
        # Get active banners for this placement with caching
        cache_key = f"ad_banners_{placement_slug}"
        banners = cache.get(cache_key)
        
        if banners is None:
            banners = AdBanner.objects.filter(
                placement=placement,
                is_active=True,
                campaign__status='active',
                campaign__approved=True,
                campaign__start_date__lte=now
            ).exclude(
                campaign__end_date__isnull=False,
                campaign__end_date__lt=now
            ).select_related('campaign', 'placement')
            
            cache.set(cache_key, banners, self.cache_timeout)
        
        if not banners.exists():
            logger.info(f"No active banners for placement: {placement_slug}")
            return None
        
        # Apply advanced filtering and targeting
        eligible_banners = []
        
        for banner in banners:
            campaign = banner.campaign
            
            # Check budget
            if campaign.spent >= campaign.budget:
                continue
            
            # Apply user targeting
            if user and user.is_authenticated:
                if campaign.targeting == 'logged_in':
                    pass  # User is logged in, good
                elif campaign.targeting == 'guest':
                    continue
            else:
                if campaign.targeting == 'logged_in':
                    continue
            
            # Apply frequency capping
            if request and hasattr(request, 'session'):
                session_id = request.session.session_key
                if session_id:
                    today = timezone.now().date()
                    impressions_today = AdImpression.objects.filter(
                        banner=banner,
                        session_id=session_id,
                        timestamp__date=today
                    ).count()
                    
                    if impressions_today >= campaign.frequency_cap:
                        continue
            
            eligible_banners.append(banner)
        
        if not eligible_banners:
            return None
        
        # Smart ad rotation based on performance
        banners_with_score = []
        for banner in eligible_banners:
            # Calculate performance score
            score = self._calculate_ad_score(banner)
            banners_with_score.append((banner, score))
        
        # Sort by score (higher score = better performance)
        banners_with_score.sort(key=lambda x: x[1], reverse=True)
        
        # Weighted random selection based on score
        total_score = sum(score for _, score in banners_with_score)
        if total_score > 0:
            random_val = random.uniform(0, total_score)
            cumulative = 0
            for banner, score in banners_with_score:
                cumulative += score
                if random_val <= cumulative:
                    selected_banner = banner
                    break
            else:
                selected_banner = banners_with_score[0][0]
        else:
            # If all scores are zero, pick random
            selected_banner = random.choice(eligible_banners)
        
        # Track delivery
        self._track_delivery(selected_banner)
        
        logger.info(f"Ad delivered: {selected_banner.title} for placement {placement_slug}")
        
        return selected_banner
    
    def _calculate_ad_score(self, banner):
        """Calculate ad performance score for rotation"""
        # Base score
        score = 1.0
        
        # CTR factor (higher CTR = higher priority)
        if banner.impressions > 0:
            ctr = banner.clicks / banner.impressions
            score += ctr * 10
        
        # Priority factor
        score += banner.priority * 2
        
        # Discount factor (promote discounted items)
        if banner.campaign.discount_percent:
            score += banner.campaign.discount_percent / 10
        
        # Freshness factor (newer campaigns get boost)
        days_since_created = (timezone.now() - banner.created_at).days
        if days_since_created < 7:
            score += (7 - days_since_created) * 0.5
        
        # Budget remaining factor
        if banner.campaign.budget > 0:
            budget_remaining = (banner.campaign.budget - banner.campaign.spent) / banner.campaign.budget
            score += budget_remaining * 2
        
        return score
    
    def _track_delivery(self, banner):
        """Track ad delivery for analytics"""
        # Update last delivered timestamp
        banner.last_delivered = timezone.now()
        banner.save(update_fields=['last_delivered'])
    
    def get_ads_batch(self, placement_slug, count=3, user=None, request=None):
        """Get multiple ads for a placement (for carousels)"""
        ads = []
        for _ in range(count):
            ad = self.get_ad(placement_slug, user, request)
            if ad and ad not in ads:
                ads.append(ad)
            else:
                break
        return ads
    
    def get_sidebar_ad(self, user=None, request=None):
        """Get ad for sidebar placement"""
        return self.get_ad('sidebar', user, request)
    
    def get_footer_ad(self, user=None, request=None):
        """Get ad for footer placement"""
        return self.get_ad('footer', user, request)
    
    def get_homepage_ad(self, user=None, request=None):
        """Get ad for homepage placement"""
        return self.get_ad('homepage-hero', user, request)
    
    def get_category_ad(self, user=None, request=None):
        """Get ad for category page placement"""
        return self.get_ad('category', user, request)
    
    def get_product_ad(self, product=None, user=None, request=None):
        """Get product-specific ad"""
        if product and product.category:
            # Try to get ad for specific product category
            category_slug = f"product_{product.category.slug}"
            ad = self.get_ad(category_slug, user, request)
            if ad:
                return ad
        return self.get_ad('product-page', user, request)
    
    def clear_cache(self, placement_slug=None):
        """Clear ad cache"""
        if placement_slug:
            cache_key = f"ad_banners_{placement_slug}"
            cache.delete(cache_key)
        else:
            # Clear all ad caches
            cache.delete_pattern("ad_banners_*")
        logger.info(f"Cache cleared for placement: {placement_slug or 'all'}")

# Singleton instance for easy access
ad_service = AdService()

# Convenience functions
def get_ad(placement_slug, user=None, request=None):
    """Get an ad for a specific placement"""
    return ad_service.get_ad(placement_slug, user, request)

def get_sidebar_ad(user=None, request=None):
    """Get ad for sidebar placement"""
    return ad_service.get_sidebar_ad(user, request)

def get_footer_ad(user=None, request=None):
    """Get ad for footer placement"""
    return ad_service.get_footer_ad(user, request)

def get_homepage_ad(user=None, request=None):
    """Get ad for homepage placement"""
    return ad_service.get_homepage_ad(user, request)

def get_category_ad(user=None, request=None):
    """Get ad for category page placement"""
    return ad_service.get_category_ad(user, request)

def get_product_ad(product=None, user=None, request=None):
    """Get product-specific ad"""
    return ad_service.get_product_ad(product, user, request)

def get_ads_batch(placement_slug, count=3, user=None, request=None):
    """Get multiple ads for a placement"""
    return ad_service.get_ads_batch(placement_slug, count, user, request)

def clear_ad_cache(placement_slug=None):
    """Clear ad cache"""
    ad_service.clear_cache(placement_slug)