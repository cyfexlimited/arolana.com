from django.db.models import Q, Avg, Count, Sum, F
from django.utils import timezone
from datetime import timedelta
from .models import VendorProfile, VendorFollow
from orders.models import Order, OrderItem
from products.models import Product, ProductReview
from accounts.models import User
import random

class VendorRankingAlgorithm:
    """Advanced algorithm for vendor ranking and recommendations"""
    
    @staticmethod
    def calculate_vendor_score(vendor):
        """Calculate overall vendor score based on multiple factors"""
        score = 0
        
        # Rating factor (40% weight)
        rating_score = float(vendor.rating_avg) / 5 * 40
        score += rating_score
        
        # Sales factor (30% weight)
        sales_score = min(vendor.total_sales / 1000, 30)
        score += sales_score
        
        # Verification factor (10% weight)
        if vendor.is_verified:
            score += 10
        
        # Response time factor (10% weight)
        # Assuming good response time
        score += 10
        
        # Fulfillment rate factor (10% weight)
        # Assuming good fulfillment
        score += 10
        
        # Bonus for followers (additional 5 points)
        follower_bonus = min(vendor.followers.count() / 100, 5)
        score += follower_bonus
        
        return round(score, 2)
    
    @staticmethod
    def get_top_rated_vendors(limit=24):
        """Get vendors sorted by highest rating"""
        return VendorProfile.objects.filter(
            is_verified=True, 
            is_active=True,
            rating_avg__gt=0
        ).order_by('-rating_avg', '-total_sales')[:limit]
    
    @staticmethod
    def get_trending_vendors(limit=24):
        """Get trending vendors based on recent sales"""
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        # Get vendors with recent sales
        recent_sales = OrderItem.objects.filter(
            order__created_at__gte=thirty_days_ago,
            order__status='delivered'
        ).values('product__vendor').annotate(
            recent_sales=Sum('quantity')
        ).order_by('-recent_sales')
        
        vendor_ids = [item['product__vendor'] for item in recent_sales]
        
        # Add random shuffle for variety
        vendors = list(VendorProfile.objects.filter(
            id__in=vendor_ids,
            is_verified=True,
            is_active=True
        ))
        random.shuffle(vendors)
        
        return vendors[:limit] if len(vendors) >= limit else vendors
    
    @staticmethod
    def get_top_selling_vendors(limit=24):
        """Get vendors with highest total sales"""
        return VendorProfile.objects.filter(
            is_verified=True,
            is_active=True,
            total_sales__gt=0
        ).order_by('-total_sales')[:limit]
    
    @staticmethod
    def get_featured_vendors(limit=8):
        """Get featured vendors (high rating + high sales)"""
        return VendorProfile.objects.filter(
            is_verified=True,
            is_active=True,
            rating_avg__gte=4.5,
            total_sales__gte=10
        ).order_by('-rating_avg', '-total_sales')[:limit]
    
    @staticmethod
    def get_recommended_vendors(user, limit=4):
        """Get personalized vendor recommendations for a user"""
        if not user.is_authenticated:
            # Return random top vendors for non-authenticated users
            vendors = list(VendorProfile.objects.filter(
                is_verified=True,
                is_active=True
            ).order_by('-rating_avg')[:10])
            random.shuffle(vendors)
            return vendors[:limit]
        
        # Get user's purchase history
        user_orders = Order.objects.filter(user=user, status='delivered')
        
        # Get categories user bought from
        purchased_categories = set()
        for order in user_orders:
            for item in order.items.all():
                if item.product.category:
                    purchased_categories.add(item.product.category.id)
        
        # Get vendors in those categories
        if purchased_categories:
            recommended = VendorProfile.objects.filter(
                is_verified=True,
                is_active=True,
                user__products__category__id__in=purchased_categories
            ).distinct().order_by('-rating_avg', '-total_sales')[:limit]
        else:
            # If no purchase history, return top rated vendors
            recommended = VendorProfile.objects.filter(
                is_verified=True,
                is_active=True
            ).order_by('-rating_avg', '-total_sales')[:limit]
        
        # Shuffle for variety
        recommended_list = list(recommended)
        random.shuffle(recommended_list)
        
        return recommended_list[:limit]
    
    @staticmethod
    def get_similar_vendors(vendor, limit=4):
        """Get similar vendors based on product categories"""
        # Get categories of the vendor's products
        product_categories = vendor.user.products.filter(
            is_active=True
        ).values_list('category', flat=True).distinct()
        
        # Find vendors with similar product categories
        similar = VendorProfile.objects.filter(
            is_verified=True,
            is_active=True,
            user__products__category__in=product_categories
        ).exclude(id=vendor.id).distinct().order_by('-rating_avg')[:limit]
        
        return similar
    
    @staticmethod
    def update_vendor_metrics(vendor):
        """Update vendor metrics based on recent activity"""
        # Update total sales
        total_sales = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__status='delivered'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        vendor.total_sales = total_sales
        
        # Update total revenue
        total_revenue = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__status='delivered'
        ).aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0
        
        vendor.total_revenue = total_revenue
        
        # Update average rating
        avg_rating = ProductReview.objects.filter(
            product__vendor=vendor.user,
            is_active=True
        ).aggregate(avg=Avg('rating'))['avg'] or 0
        
        vendor.rating_avg = round(avg_rating, 2)
        
        vendor.save()
        return vendor
    
    @staticmethod
    def get_vendor_performance_data(vendor):
        """Get detailed performance data for vendor dashboard"""
        thirty_days_ago = timezone.now() - timedelta(days=30)
        
        # Sales trend (last 30 days)
        recent_sales = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__status='delivered',
            order__created_at__gte=thirty_days_ago
        ).aggregate(total=Sum('quantity'))['total'] or 0
        
        # Revenue trend
        recent_revenue = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__status='delivered',
            order__created_at__gte=thirty_days_ago
        ).aggregate(total=Sum(F('quantity') * F('price')))['total'] or 0
        
        # Customer count
        unique_customers = OrderItem.objects.filter(
            product__vendor=vendor.user,
            order__status='delivered'
        ).values('order__user').distinct().count()
        
        return {
            'recent_sales': recent_sales,
            'recent_revenue': float(recent_revenue),
            'unique_customers': unique_customers,
            'follower_count': vendor.followers.count(),
            'total_products': vendor.user.products.filter(is_active=True).count(),
            'average_rating': vendor.rating_avg,
        }

class VendorRecommendationEngine:
    """Engine for generating vendor recommendations"""
    
    @staticmethod
    def get_personalized_recommendations(user, limit=8):
        """Get personalized recommendations based on user behavior"""
        recommendations = []
        
        # 1. Based on browsing history
        recently_viewed = user.recently_viewed.all()[:5]
        if recently_viewed:
            viewed_vendors = set()
            for viewed in recently_viewed:
                if viewed.product and viewed.product.vendor:
                    viewed_vendors.add(viewed.product.vendor)
            
            for vendor in viewed_vendors:
                recommendations.append({
                    'vendor': vendor,
                    'reason': 'You viewed their products',
                    'score': 80
                })
        
        # 2. Based on purchase history
        purchased_orders = Order.objects.filter(user=user, status='delivered')
        if purchased_orders:
            purchased_vendors = set()
            for order in purchased_orders:
                for item in order.items.all():
                    if item.product and item.product.vendor:
                        purchased_vendors.add(item.product.vendor)
            
            for vendor in purchased_vendors:
                recommendations.append({
                    'vendor': vendor,
                    'reason': 'You purchased from them',
                    'score': 100
                })
        
        # 3. Based on followed vendors
        followed = VendorFollow.objects.filter(user=user)
        for follow in followed:
            recommendations.append({
                'vendor': follow.vendor,
                'reason': 'You follow them',
                'score': 90
            })
        
        # Remove duplicates and sort by score
        unique_recs = {}
        for rec in recommendations:
            vendor_id = rec['vendor'].id
            if vendor_id not in unique_recs or rec['score'] > unique_recs[vendor_id]['score']:
                unique_recs[vendor_id] = rec
        
        sorted_recs = sorted(unique_recs.values(), key=lambda x: x['score'], reverse=True)
        
        # If not enough recommendations, add top rated vendors
        if len(sorted_recs) < limit:
            existing_ids = [rec['vendor'].id for rec in sorted_recs]
            top_vendors = VendorProfile.objects.filter(
                is_verified=True,
                is_active=True
            ).exclude(id__in=existing_ids).order_by('-rating_avg')[:limit - len(sorted_recs)]
            
            for vendor in top_vendors:
                sorted_recs.append({
                    'vendor': vendor,
                    'reason': 'Top rated vendor',
                    'score': 70
                })
        
        return sorted_recs[:limit]