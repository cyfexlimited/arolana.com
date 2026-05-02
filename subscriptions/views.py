from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import SubscriptionPlan, VendorSubscription
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
    
    # Check if already has active subscription
    existing = VendorSubscription.objects.filter(
        vendor=request.user,
        is_active=True,
        end_date__gt=timezone.now()
    ).first()
    
    if existing:
        messages.warning(request, f'You already have an active {existing.plan.display_name} subscription.')
        return redirect('subscriptions:plans')
    
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
    vendor_profile.subscription_plan = plan.name
    vendor_profile.subscription_end_date = end_date
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
    vendor_profile.subscription_plan = 'basic'
    vendor_profile.save()
    
    messages.success(request, 'Your subscription has been cancelled.')
    return redirect('subscriptions:plans')

@login_required
def subscription_history(request):
    """View subscription history"""
    subscriptions = VendorSubscription.objects.filter(vendor=request.user).order_by('-created_at')
    return render(request, 'subscriptions/history.html', {'subscriptions': subscriptions})
