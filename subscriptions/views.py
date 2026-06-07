from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import SubscriptionPlan, VendorSubscription, apply_vendor_subscription_benefits, normalize_subscription_tier, get_tier_limits
from vendors.models import VendorProfile
from arolana_payments.models import PaymentMethod, PaymentStatus, PaymentTransaction
from arolana_payments.services import gateway_is_available, get_gateway_options

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
        'subscription_benefits_image_url': '/static/images/arolana-vendor-subscription-benefits.png',
        'payment_gateways': get_gateway_options(include_inactive=True),
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
    
    vendor_profile = request.user.vendor_profile

    if plan.price_monthly <= 0:
        from staff_mobile.views import _activate_free_vendor_plan

        _activate_free_vendor_plan(vendor_profile, plan)
        messages.success(request, f'Successfully activated {plan.vendor_label}.')
        return redirect('subscriptions:plans')

    gateway = (request.POST.get('payment_gateway') or request.GET.get('payment_gateway') or PaymentMethod.PAYSTACK).lower()
    is_available, disabled_reason = gateway_is_available(gateway)
    if not is_available:
        messages.error(request, disabled_reason or 'Selected payment gateway is not available yet.')
        return redirect('subscriptions:plans')

    try:
        from staff_mobile.views import _hosted_subscription_checkout_url, _subscription_receipt

        payment = _subscription_receipt(vendor_profile, plan, gateway=gateway, status=PaymentStatus.PENDING)
        checkout_url = _hosted_subscription_checkout_url(request, payment)
    except Exception as error:
        messages.error(request, f'Unable to start subscription checkout: {error}')
        return redirect('subscriptions:plans')

    if not checkout_url:
        messages.error(request, 'Payment gateway did not return a checkout link. Please try another gateway.')
        return redirect('subscriptions:plans')

    messages.info(request, 'Payment initialized. Complete checkout, then verify your payment from the vendor dashboard or staff app.')
    return redirect(checkout_url)

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
    vendor_profile.subscription_active = False
    vendor_profile.subscription_started_at = None
    vendor_profile.subscription_expires_at = None
    vendor_profile.subscription_expiry = None
    vendor_profile.priority_score = 0
    vendor_profile.save(update_fields=['subscription_tier', 'subscription_active', 'subscription_started_at', 'subscription_expires_at', 'subscription_expiry', 'priority_score', 'updated_at'])
    apply_vendor_subscription_benefits(vendor_profile, 'free')
    
    messages.success(request, 'Your subscription has been cancelled.')
    return redirect('subscriptions:plans')

@login_required
def subscription_history(request):
    """View subscription history"""
    if not hasattr(request.user, 'vendor_profile'):
        messages.error(request, 'You need to become a vendor first.')
        return redirect('vendors:become')

    current_subscription = VendorSubscription.objects.filter(
        vendor=request.user,
        is_active=True,
        end_date__gt=timezone.now()
    ).select_related('plan').first()

    invoices = PaymentTransaction.objects.filter(
        user=request.user,
        checkout_data__purpose='vendor_subscription',
    ).order_by('-created_at')

    subscriptions = VendorSubscription.objects.filter(
        vendor=request.user
    ).select_related('plan').order_by('-created_at')

    return render(request, 'subscriptions/history.html', {
        'vendor_profile': request.user.vendor_profile,
        'current_subscription': current_subscription,
        'invoices': invoices,
        'subscriptions': subscriptions,
    })
