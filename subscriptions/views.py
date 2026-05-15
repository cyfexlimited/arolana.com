from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import SubscriptionPlan, VendorSubscription, normalize_subscription_tier, get_tier_limits
from vendors.models import VendorProfile

@login_required
def subscription_plans(request):
    """View all subscription plans for vendors"""
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('order', 'price_monthly')
    
    # Get user's current subscription if they are a vendor
    current_subscription = None
    if hasattr(request.user, 'vendor_profile'):
        current_subscription = VendorSubscription.objects.filter(
            vendor=request.user,
            is_active=True,
            end_date__gt=timezone.now()
        ).first()
    
    context = {
        'plans': plans,
        'current_subscription': current_subscription,
    }
    return render(request, 'subscriptions/plans.html', context)

@login_required
def subscribe(request, plan_id):
    """Subscribe to a plan"""
    plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)
    
    # Check if user is a vendor
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You need to become a vendor first.')
        return redirect('vendors:become')
    
    # Replace any existing active subscription so vendors can upgrade/downgrade cleanly.
    existing = VendorSubscription.objects.filter(
        vendor=request.user,
        is_active=True,
        end_date__gt=timezone.now()
    ).first()
    
    if existing:
        existing.is_active = False
        existing.auto_renew = False
        existing.save(update_fields=['is_active', 'auto_renew', 'updated_at'])
    
    # Create subscription (30 days)
    from django.utils import timezone
    end_date = timezone.now() + timezone.timedelta(days=30)
    
    subscription = VendorSubscription.objects.create(
        vendor=request.user,
        plan=plan,
        start_date=timezone.now(),
        end_date=end_date,
        is_active=True,
        auto_renew=False
    )
    
    # Update vendor profile
    vendor_profile = request.user.vendor_profile
    tier = normalize_subscription_tier(plan.name)
    limits = get_tier_limits(tier)
    vendor_profile.subscription_tier = tier
    vendor_profile.subscription_expiry = end_date
    vendor_profile.priority_score = limits['priority_score']
    vendor_profile.save()
    
    messages.success(request, f'Successfully subscribed to {plan.display_name}!')
    return redirect('subscriptions:plans')

@login_required
def cancel_subscription(request, subscription_id):
    """Cancel a subscription"""
    subscription = get_object_or_404(VendorSubscription, id=subscription_id, vendor=request.user)
    subscription.is_active = False
    subscription.auto_renew = False
    subscription.save()
    
    # Update vendor profile
    vendor_profile = request.user.vendor_profile
    vendor_profile.subscription_tier = 'free'
    vendor_profile.subscription_expiry = None
    vendor_profile.priority_score = 0
    vendor_profile.save(update_fields=['subscription_tier', 'subscription_expiry', 'priority_score', 'updated_at'])
    
    messages.success(request, 'Your subscription has been cancelled.')
    return redirect('subscriptions:plans')

@login_required
def subscription_history(request):
    """View subscription history"""
    subscriptions = VendorSubscription.objects.filter(vendor=request.user).order_by('-created_at')
    return render(request, 'subscriptions/history.html', {'subscriptions': subscriptions})
