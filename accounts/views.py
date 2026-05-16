import re
import logging
import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.validators import validate_email
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from allauth.socialaccount.adapter import get_adapter as get_socialaccount_adapter
from django.utils.text import slugify
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from .models import User, UserProfile, UserOTP, UserActivityLog, NewsletterSubscriber, Address
from products.models import RecentlyViewed, Wishlist
from .utils.otp_utils import create_otp, verify_otp
from .utils.messaging import send_registration_messages, sync_newsletter_subscriber
from .tokens import account_activation_token

logger = logging.getLogger(__name__)

# Import notification models
try:
    from notifications.models import Notification
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    logger.warning("⚠️ Notifications app not installed")

# ==================== HELPER FUNCTIONS ====================

def create_notification(user, notification_type, title, message, link=''):
    """Helper function to create notification with error handling"""
    if NOTIFICATIONS_AVAILABLE and user and user.is_authenticated:
        try:
            Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                link=link
            )
            logger.info(f"✅ Notification created for {user.username}: {title}")
        except Exception as e:
            logger.error(f"Error creating notification: {e}")

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def log_user_activity(user, action, request, details=None):
    """Helper to log user activity"""
    try:
        UserActivityLog.objects.create(
            user=user,
            action=action,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            details=details or {}
        )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")

def get_social_apps_context(request=None):
    """Get social apps availability for template context"""
    try:
        adapter = get_socialaccount_adapter(request)
        google_app = bool(adapter.list_apps(request, provider='google'))
        facebook_app = bool(adapter.list_apps(request, provider='facebook'))
        return {
            'google_app_exists': google_app,
            'facebook_app_exists': facebook_app,
        }
    except Exception as e:
        logger.warning(f"Could not fetch social apps: {e}")
        return {
            'google_app_exists': False,
            'facebook_app_exists': False,
        }

def unique_store_slug(store_name):
    from vendors.models import VendorProfile

    base_slug = slugify(store_name) or 'seller'
    slug = base_slug
    counter = 2
    while VendorProfile.objects.filter(store_slug=slug).exists():
        slug = f'{base_slug}-{counter}'
        counter += 1
    return slug

def create_business_profile_for_user(user, account_type, business_name, business_description=''):
    if account_type not in ['vendor', 'manufacturer']:
        return None

    from vendors.models import VendorProfile

    store_name = business_name or user.get_full_name() or user.username or user.email.split('@')[0]
    profile, created = VendorProfile.objects.get_or_create(
        user=user,
        defaults={
            'store_name': store_name,
            'store_slug': unique_store_slug(store_name),
            'description': business_description or f'{store_name} storefront on Arolana.',
            'is_verified': False,
            'subscription_tier': 'free',
        },
    )
    if not created:
        profile.store_name = store_name
        if business_description:
            profile.description = business_description
        profile.save()
    return profile

def get_vendor_profile(user):
    try:
        return user.vendor_profile
    except ObjectDoesNotExist:
        return None

def has_active_otp(user, otp_type='email'):
    return UserOTP.objects.filter(
        user=user,
        otp_type=otp_type,
        is_used=False,
        expires_at__gt=timezone.now(),
    ).exists()

# ==================== NEWSLETTER ====================

def newsletter_subscribe(request):
    """Handle newsletter subscription (no login required)"""
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            try:
                validate_email(email)
                subscriber, created = NewsletterSubscriber.objects.get_or_create(
                    email=email,
                    defaults={'is_active': True}
                )
                if created:
                    messages.success(request, f'Successfully subscribed to newsletter with {email}!')
                else:
                    if subscriber.is_active:
                        messages.info(request, f'Email {email} is already subscribed.')
                    else:
                        subscriber.is_active = True
                        subscriber.save()
                        messages.success(request, f'Successfully re-subscribed with {email}!')
            except ValidationError:
                messages.error(request, 'Please provide a valid email address.')
        else:
            messages.error(request, 'Please provide an email address.')
        return redirect(request.META.get('HTTP_REFERER', '/'))
    return redirect('/')

# ==================== AUTHENTICATION ====================

def login_view(request):
    """Enhanced login with email/phone and OTP support"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        remember = request.POST.get('remember') == 'on'
        
        if not identifier or not password:
            messages.error(request, 'Please fill in all fields')
            return render(request, 'accounts/login.html', get_social_apps_context(request))
        
        # Try to find user by email or username
        user = None
        if '@' in identifier:
            try:
                user = User.objects.get(email__iexact=identifier)
            except User.DoesNotExist:
                pass
        else:
            try:
                user = User.objects.get(username__iexact=identifier)
            except User.DoesNotExist:
                try:
                    user = User.objects.get(phone_number=identifier)
                except User.DoesNotExist:
                    pass
        
        if user and user.check_password(password):
            ip_address = get_client_ip(request)
            
            # Check if 2FA is enabled
            if getattr(user, 'two_factor_enabled', False):
                otp = create_otp(user, user.email, 'login')
                if otp:
                    request.session['pre_2fa_user_id'] = user.id
                    messages.info(request, f"Please enter the OTP sent to {user.email}")
                    return redirect('accounts:verify_2fa')
                else:
                    messages.error(request, "Failed to send OTP. Please try again.")
            else:
                # Regular login
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                
                if not remember:
                    request.session.set_expiry(0)
                
                log_user_activity(user, 'login', request, {'method': 'password'})
                create_notification(
                    user, 'success', '🔐 New Login Detected',
                    f'You logged in from IP: {ip_address} at {timezone.now().strftime("%I:%M %p")}',
                    '/accounts/profile/'
                )
                
                messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
                next_url = request.POST.get('next') or request.GET.get('next') or 'home'
                return redirect(next_url)
        else:
            log_user_activity(None, 'failed_login', request, {'identifier': identifier[:50]})
            messages.error(request, "Invalid email/username or password.")
    
    return render(request, 'accounts/login.html', get_social_apps_context(request))

def register_view(request):
    """Enhanced registration with email verification."""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        username = request.POST.get('username', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        account_type = request.POST.get('account_type', 'customer')
        business_name = request.POST.get('business_name', '').strip()
        business_description = request.POST.get('business_description', '').strip()
        newsletter_opt_in = request.POST.get('newsletter') == 'on'
        terms = request.POST.get('terms') == 'on'

        allowed_account_types = ['customer', 'vendor', 'manufacturer']
        if account_type not in allowed_account_types:
            account_type = 'customer'
        
        errors = []
        
        # Email validation
        if not email:
            errors.append('Email is required')
        else:
            try:
                validate_email(email)
                if User.objects.filter(email__iexact=email).exists():
                    errors.append('Email already registered')
            except ValidationError:
                errors.append('Please enter a valid email address')
        
        # Username validation
        if not username:
            errors.append('Username is required')
        elif len(username) < 3:
            errors.append('Username must be at least 3 characters')
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            errors.append('Username can only contain letters, numbers, and underscores')
        elif User.objects.filter(username__iexact=username).exists():
            errors.append('Username already taken')
        
        # Password validation
        if not password:
            errors.append('Password is required')
        else:
            if len(password) < 8:
                errors.append('Password must be at least 8 characters')
            if not any(c.isupper() for c in password):
                errors.append('Password must contain at least one uppercase letter')
            if not any(c.islower() for c in password):
                errors.append('Password must contain at least one lowercase letter')
            if not any(c.isdigit() for c in password):
                errors.append('Password must contain at least one number')
            if password != confirm_password:
                errors.append('Passwords do not match')
        
        # Terms acceptance
        if not terms:
            errors.append('You must agree to the Terms of Service')

        if account_type in ['vendor', 'manufacturer'] and not business_name:
            errors.append('Business or brand name is required for seller accounts')
        
        if errors:
            context = {
                'email': email, 'username': username, 'first_name': first_name,
                'last_name': last_name, 'phone_number': phone_number,
                'account_type': account_type, 'business_name': business_name,
                'business_description': business_description
            }
            context.update(get_social_apps_context(request))
            for error in errors:
                messages.error(request, error)
            return render(request, 'accounts/register.html', context)
        
        # Create user
        user = User.objects.create_user(
            username=username, email=email, password=password,
            first_name=first_name, last_name=last_name,
            user_type=account_type
        )
        
        if phone_number:
            user.phone_number = phone_number
            user.save()
        
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'newsletter_subscription': newsletter_opt_in,
                'promo_emails': newsletter_opt_in,
                'marketing_emails': newsletter_opt_in,
            }
        )
        sync_newsletter_subscriber(user, subscribe=newsletter_opt_in, source='registration')
        business_profile = create_business_profile_for_user(user, account_type, business_name, business_description)
        if business_profile:
            try:
                from kyc.models import KYCRecord
                KYCRecord.objects.get_or_create(
                    vendor=business_profile,
                    defaults={
                        'legal_business_name': business_profile.store_name,
                        'business_email': user.email,
                        'business_phone': phone_number or '',
                        'authorized_person_name': user.get_full_name() or username,
                        'authorized_person_email': user.email,
                        'authorized_person_phone': phone_number or '',
                    }
                )
            except Exception as e:
                logger.warning(f'Could not create KYC record for {user.email}: {e}')
        
        create_notification(
            user, 'success', '🎉 Welcome to Arolana!',
            'Thank you for joining Arolana.com. Start exploring our products and enjoy exclusive deals!',
            '/products/'
        )
        email_otp = create_otp(user, user.email, 'email')
        send_registration_messages(user, request)
        
        log_user_activity(user, 'register', request, {'method': 'email'})
        
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)
        request.session['email_verification_send_failed'] = not bool(email_otp)
        
        if not email_otp:
            messages.error(request, 'Your account was created, but the verification email could not be sent. Please try Resend Code or contact support.')
        elif account_type in ['vendor', 'manufacturer']:
            messages.success(request, f"Welcome to Arolana, {username}! Verify your email, then complete KYC before uploading products.")
        else:
            messages.success(request, f"Welcome to Arolana, {username}! Verify your email to secure your account.")
        return redirect('accounts:verify_email')
    
    context = get_social_apps_context(request)
    return render(request, 'accounts/register.html', context)

def logout_view(request):
    """Enhanced logout with activity logging"""
    if request.user.is_authenticated:
        username = request.user.username
        log_user_activity(request.user, 'logout', request, {})
        create_notification(request.user, 'info', '👋 Logged Out', 'You have been logged out of your account', '/accounts/login/')
        logout(request)
        return render(request, 'accounts/logout.html', {'username': username})
    else:
        messages.info(request, "You were not logged in.")

    return render(request, 'accounts/logout.html')

# ==================== PROFILE & SETTINGS ====================

@login_required
def profile_view(request):
    """User profile page"""
    vendor_profile = get_vendor_profile(request.user)
    try:
        kyc_record = vendor_profile.kyc_record if vendor_profile else None
    except ObjectDoesNotExist:
        kyc_record = None
    return render(request, 'accounts/profile.html', {
        'user': request.user,
        'vendor_profile': vendor_profile,
        'kyc_record': kyc_record,
    })

@login_required
def edit_profile(request):
    """Edit user profile"""
    if request.method == 'POST':
        request.user.first_name = request.POST.get('first_name', '').strip()
        request.user.last_name = request.POST.get('last_name', '').strip()
        request.user.phone_number = request.POST.get('phone_number', '').strip() or None
        
        if request.FILES.get('avatar'):
            request.user.avatar = request.FILES.get('avatar')
        
        request.user.save()
        
        if hasattr(request.user, 'profile'):
            request.user.profile.bio = request.POST.get('bio', '').strip()
            request.user.profile.newsletter_subscription = request.POST.get('newsletter') == 'on'
            request.user.profile.promo_emails = request.POST.get('promo_emails') == 'on'
            request.user.profile.marketing_emails = request.POST.get('marketing_emails') == 'on'
            request.user.profile.company = request.POST.get('company', '').strip()
            request.user.profile.location = request.POST.get('location', '').strip()
            request.user.profile.website = request.POST.get('website', '').strip()
            request.user.profile.save()

        vendor_profile = get_vendor_profile(request.user)
        if vendor_profile:
            vendor_profile.store_name = request.POST.get('store_name', vendor_profile.store_name).strip() or vendor_profile.store_name
            vendor_profile.description = request.POST.get('store_description', vendor_profile.description).strip() or vendor_profile.description
            if request.FILES.get('store_logo'):
                vendor_profile.store_logo = request.FILES.get('store_logo')
            if request.FILES.get('store_banner'):
                vendor_profile.store_banner = request.FILES.get('store_banner')
            vendor_profile.save()

        sync_newsletter_subscriber(
            request.user,
            subscribe=request.POST.get('newsletter') == 'on',
            source='profile',
        )
        
        create_notification(request.user, 'system', '👤 Profile Updated', 'Your profile information has been updated successfully.', '/accounts/profile/')
        messages.success(request, "Profile updated successfully!")
        return redirect('accounts:profile')
    
    return render(request, 'accounts/edit_profile.html', {
        'vendor_profile': get_vendor_profile(request.user),
    })

@login_required
def change_password(request):
    """Change user password"""
    if request.method == 'POST':
        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if not request.user.check_password(current_password):
            messages.error(request, "Current password is incorrect.")
            return redirect('accounts:change_password')
        
        if new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
            return redirect('accounts:change_password')
        
        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect('accounts:change_password')
        
        request.user.set_password(new_password)
        request.user.save()
        request.user.backend = 'django.contrib.auth.backends.ModelBackend'
        
        create_notification(request.user, 'system', '🔑 Password Changed', 'Your password has been changed successfully.', '/accounts/profile/')
        log_user_activity(request.user, 'password_change', request, {'method': 'manual'})
        
        messages.success(request, "Password changed successfully! Please login with your new password.")
        return redirect('accounts:login')
    
    return render(request, 'accounts/change_password.html')

# ==================== ADDRESS MANAGEMENT ====================

@login_required
def addresses_view(request):
    """Display all user addresses"""
    addresses = Address.objects.filter(user=request.user, is_active=True)
    return render(request, 'accounts/addresses.html', {'addresses': addresses})

@login_required
def add_address(request):
    """Add a new address"""
    if request.method == 'POST':
        address = Address.objects.create(
            user=request.user,
            address_line1=request.POST.get('address_line1', '').strip(),
            address_line2=request.POST.get('address_line2', '').strip(),
            city=request.POST.get('city', '').strip(),
            state=request.POST.get('state', '').strip(),
            postal_code=request.POST.get('postal_code', '').strip(),
            country=request.POST.get('country', 'US'),
            is_default=request.POST.get('is_default') == 'on',
            is_shipping=True,
            is_billing=request.POST.get('is_billing') == 'on'
        )
        
        create_notification(request.user, 'system', '📍 New Address Added', f'A new address has been added to your account.', '/accounts/addresses/')
        messages.success(request, 'Address added successfully!')
        return redirect('accounts:addresses')
    
    return render(request, 'accounts/add_address.html')

@login_required
def edit_address(request, pk):
    """Edit an existing address"""
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    if request.method == 'POST':
        address.address_line1 = request.POST.get('address_line1', '').strip()
        address.address_line2 = request.POST.get('address_line2', '').strip()
        address.city = request.POST.get('city', '').strip()
        address.state = request.POST.get('state', '').strip()
        address.postal_code = request.POST.get('postal_code', '').strip()
        address.country = request.POST.get('country', 'US')
        address.is_default = request.POST.get('is_default') == 'on'
        address.is_billing = request.POST.get('is_billing') == 'on'
        address.save()
        
        messages.success(request, 'Address updated successfully!')
        return redirect('accounts:addresses')
    
    return render(request, 'accounts/edit_address.html', {'address': address})

@login_required
def delete_address(request, pk):
    """Delete an address"""
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    was_default = address.is_default
    address.delete()
    
    if was_default:
        first_address = Address.objects.filter(user=request.user).first()
        if first_address:
            first_address.is_default = True
            first_address.save()
    
    messages.success(request, 'Address deleted successfully!')
    return redirect('accounts:addresses')

@login_required
def set_default_address(request, pk):
    """Set an address as default"""
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    Address.objects.filter(user=request.user).update(is_default=False)
    address.is_default = True
    address.save()
    
    messages.success(request, 'Default address updated successfully!')
    return redirect('accounts:addresses')

# ==================== WISHLIST & HISTORY ====================

@login_required
def wishlist_view(request):
    """User wishlist page"""
    wishlist_items = Wishlist.objects.filter(user=request.user).select_related('product')
    return render(request, 'accounts/wishlist.html', {'wishlist_items': wishlist_items})

@login_required
def clear_wishlist(request):
    """Clear all wishlist items"""
    Wishlist.objects.filter(user=request.user).delete()
    messages.success(request, 'Wishlist cleared successfully!')
    return redirect('accounts:wishlist')

@login_required
def browsing_history(request):
    """User browsing history page"""
    history = RecentlyViewed.objects.filter(user=request.user).select_related('product').order_by('-viewed_at')[:50]
    return render(request, 'accounts/browsing_history.html', {'history': history})

@login_required
def clear_browsing_history(request):
    """Clear all browsing history"""
    RecentlyViewed.objects.filter(user=request.user).delete()
    messages.success(request, 'Browsing history cleared successfully!')
    return redirect('accounts:browsing_history')

@login_required
def remove_history_item(request, item_id):
    """Remove a single item from browsing history"""
    if request.method == 'POST':
        try:
            item = RecentlyViewed.objects.get(id=item_id, user=request.user)
            item.delete()
            return JsonResponse({'success': True})
        except RecentlyViewed.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Item not found'})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

# ==================== SUBSCRIPTIONS ====================

@login_required
def subscriptions_view(request):
    """Email subscription preferences"""
    profile = request.user.profile
    
    if request.method == 'POST':
        profile.newsletter_subscription = request.POST.get('newsletter') == 'on'
        profile.promo_emails = request.POST.get('promo_emails') == 'on'
        profile.order_updates = request.POST.get('order_updates') == 'on'
        profile.marketing_emails = request.POST.get('marketing_emails') == 'on'
        profile.save()
        
        create_notification(request.user, 'system', '📧 Email Preferences Updated', 'Your email subscription preferences have been updated.', '/accounts/subscriptions/')
        messages.success(request, 'Your email preferences have been updated!')
        return redirect('accounts:subscriptions')
    
    return render(request, 'accounts/subscriptions.html')

# ==================== API ENDPOINTS ====================

@login_required
def wishlist_count(request):
    """Return wishlist count as JSON"""
    from django.http import JsonResponse
    count = request.user.wishlist_items.count()
    return JsonResponse({'count': count})

@require_GET
def social_apps_status(request):
    """Check if social apps are configured"""
    context = get_social_apps_context(request)
    return JsonResponse(context)

@require_GET
def check_username(request):
    username = request.GET.get('username', '').strip()
    exists = User.objects.filter(username__iexact=username).exists() if username else False
    return JsonResponse({'exists': exists})

@require_GET
def check_email(request):
    email = request.GET.get('email', '').strip()
    exists = User.objects.filter(email__iexact=email).exists() if email else False
    return JsonResponse({'exists': exists})

@require_GET
def recent_activity_api(request):
    """Get recent user activity via AJAX"""
    if not request.user.is_authenticated:
        return JsonResponse({'activities': []})
    
    activities = UserActivityLog.objects.filter(user=request.user)[:20].values('action', 'timestamp', 'ip_address', 'user_agent')
    return JsonResponse({'success': True, 'activities': list(activities)})

# ==================== 2FA & SECURITY ====================

def verify_2fa(request):
    """Two-factor authentication verification"""
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please login again.')
        return redirect('accounts:login')
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        success, message = verify_otp(user, otp_code, 'login')
        
        if success:
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            del request.session['pre_2fa_user_id']
            
            create_notification(user, 'success', '🔐 2FA Login Successful', 'You logged in using two-factor authentication', '/accounts/profile/')
            log_user_activity(user, 'login_2fa', request, {'method': '2fa_otp'})
            
            messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
            next_url = request.GET.get('next', 'home')
            return redirect(next_url)
        else:
            messages.error(request, message)
    
    return render(request, 'accounts/verify_2fa.html', {'user': user})

def forgot_password(request):
    """Password reset request page"""
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        
        if not identifier:
            messages.error(request, 'Please enter your email address.')
            return render(request, 'accounts/forgot_password.html')
        
        try:
            user = User.objects.get(email__iexact=identifier)
            otp = create_otp(user, user.email, 'password_reset')
            if otp:
                request.session['reset_user_id'] = user.id
                messages.success(request, f"We've sent a verification code to {user.email}")
                return redirect('accounts:reset_password_verify')
            else:
                messages.error(request, "Failed to send OTP. Please try again.")
        except User.DoesNotExist:
            messages.info(request, "If an account exists with that email, you will receive a password reset link.")
            return render(request, 'accounts/forgot_password.html')
    
    return render(request, 'accounts/forgot_password.html')

def reset_password_verify(request):
    """Password reset with OTP verification"""
    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.error(request, 'Session expired. Please request a new password reset.')
        return redirect('accounts:forgot_password')
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        
        if not otp_code or len(otp_code) != 6:
            messages.error(request, 'Please enter a valid 6-digit verification code.')
        elif not new_password or len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        elif new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
        else:
            success, message = verify_otp(user, otp_code, 'password_reset')
            if success:
                user.set_password(new_password)
                user.save()
                del request.session['reset_user_id']
                create_notification(user, 'system', '🔑 Password Changed', 'Your password has been successfully changed.', '/accounts/login/')
                messages.success(request, "Password reset successfully! Please login with your new password.")
                return redirect('accounts:login')
            else:
                messages.error(request, message)
    
    return render(request, 'accounts/reset_password_verify.html', {'user': user, 'contact_method': user.email})

@login_required
def enable_2fa(request):
    """Enable two-factor authentication"""
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        success, message = verify_otp(request.user, otp_code, 'login')
        
        if success:
            request.user.two_factor_enabled = True
            request.user.save()
            
            backup_codes = [''.join(random.choices(string.digits, k=8)) for _ in range(8)]
            create_notification(request.user, 'system', '🛡️ 2FA Enabled', 'Two-factor authentication has been enabled on your account.', '/accounts/security/')
            messages.success(request, "2FA enabled successfully!")
            return render(request, 'accounts/enable_2fa.html', {'backup_codes': backup_codes})
        else:
            messages.error(request, message)
    
    otp = create_otp(request.user, request.user.email, 'login')
    if otp:
        messages.info(request, f"An OTP has been sent to {request.user.email}")
    else:
        messages.error(request, 'We could not send your 2FA code. Please try again or contact support.')
    return render(request, 'accounts/enable_2fa.html')

@login_required
def disable_2fa(request):
    """Disable two-factor authentication"""
    if request.method == 'POST':
        password = request.POST.get('password')
        
        if not request.user.check_password(password):
            messages.error(request, "Incorrect password. Please try again.")
            return render(request, 'accounts/disable_2fa.html')
        
        request.user.two_factor_enabled = False
        request.user.save()
        
        create_notification(request.user, 'system', '🔓 2FA Disabled', 'Two-factor authentication has been disabled on your account.', '/accounts/security/')
        messages.success(request, "Two-factor authentication has been disabled.")
        return redirect('accounts:security_settings')
    
    return render(request, 'accounts/disable_2fa.html')

@login_required
def security_settings(request):
    """Security settings page"""
    recent_activities = UserActivityLog.objects.filter(user=request.user)[:10]
    return render(request, 'accounts/security_settings.html', {
        'user': request.user,
        'recent_activities': recent_activities,
        'has_2fa': getattr(request.user, 'two_factor_enabled', False),
        'email_verified': request.user.email_verified,
    })

def verify_email_token(request, uidb64, token):
    """Verify email from a signed email link."""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and account_activation_token.check_token(user, token):
        if not user.email_verified:
            user.email_verified = True
            user.save()
            UserOTP.objects.filter(user=user, otp_type='email', is_used=False).update(is_used=True)
            create_notification(user, 'system', 'Email Verified', 'Your email address has been successfully verified!', '/accounts/profile/')
            messages.success(request, 'Email verified successfully!')
        else:
            messages.info(request, 'Your email is already verified.')

        if not request.user.is_authenticated:
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
        return redirect('accounts:security_settings')

    messages.error(request, 'The email verification link is invalid or expired. Please request a new verification email.')
    if request.user.is_authenticated:
        return redirect('accounts:security_settings')
    return redirect('accounts:login')

@login_required
def verify_email(request):
    """Verify email address with OTP"""
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        success, message = verify_otp(request.user, otp_code, 'email')
        
        if success:
            request.user.email_verified = True
            request.user.save()
            create_notification(request.user, 'system', '✅ Email Verified', 'Your email address has been successfully verified!', '/accounts/profile/')
            messages.success(request, "Email verified successfully!")
            return redirect('accounts:security_settings')
        else:
            messages.error(request, message)
    else:
        send_failed_on_register = request.session.pop('email_verification_send_failed', False)
        if not send_failed_on_register and not has_active_otp(request.user, 'email'):
            otp = create_otp(request.user, request.user.email, 'email')
            if otp:
                messages.info(request, f"Verification code sent to {request.user.email}")
            else:
                messages.error(request, 'We could not send your verification email. Please try again or contact support.')
    
    return render(request, 'accounts/verify_email.html', {'user': request.user})

@login_required
def verify_phone(request):
    """Phone verification is paused until SMS delivery is needed."""
    messages.info(request, 'Phone verification is not required right now. Email verification is enough to secure your account.')
    return redirect('accounts:security_settings')

@login_required
@require_POST
def resend_verification_email(request):
    """Resend email verification OTP"""
    otp = create_otp(request.user, request.user.email, 'email')
    if otp:
        return JsonResponse({'success': True, 'message': 'Verification code resent successfully'})
    return JsonResponse({'success': False, 'error': 'Failed to send verification code'})

@login_required
def logout_all_devices(request):
    """Logout user from all other devices"""
    if request.method == 'POST':
        current_session_key = request.session.session_key
        
        for session in Session.objects.all():
            session_data = session.get_decoded()
            if session_data.get('_auth_user_id') == str(request.user.id) and session.session_key != current_session_key:
                session.delete()
        
        create_notification(request.user, 'system', '🔐 Logged out from other devices', 'You have been logged out from all other devices.', '/accounts/security/')
        messages.success(request, "Logged out from all other devices.")
        return redirect('accounts:security_settings')
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def session_activity(request):
    """View active sessions"""
    sessions = []
    current_session_key = request.session.session_key
    
    for session in Session.objects.all():
        session_data = session.get_decoded()
        if session_data.get('_auth_user_id') == str(request.user.id):
            sessions.append({
                'session_key': session.session_key,
                'is_current': session.session_key == current_session_key,
                'last_activity': session.expire_date,
                'user_agent': session_data.get('_auth_user_agent', 'Unknown'),
                'ip_address': session_data.get('_auth_user_ip', 'Unknown'),
            })
    
    return render(request, 'accounts/session_activity.html', {'sessions': sessions})

@login_required
def terminate_session(request, session_key):
    """Terminate a specific session"""
    if request.method == 'POST':
        if session_key == request.session.session_key:
            messages.error(request, "Cannot terminate your current session.")
        else:
            try:
                session = Session.objects.get(session_key=session_key)
                session_data = session.get_decoded()
                if session_data.get('_auth_user_id') == str(request.user.id):
                    session.delete()
                    messages.success(request, "Session terminated successfully.")
                else:
                    messages.error(request, "Session not found.")
            except Session.DoesNotExist:
                messages.error(request, "Session not found.")
        
        return redirect('accounts:session_activity')
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def notification_preferences(request):
    """User notification preferences"""
    from notifications.models import NotificationPreference
    
    prefs, created = NotificationPreference.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        prefs.email_notifications = request.POST.get('email_notifications') == 'on'
        prefs.push_notifications = request.POST.get('push_notifications') == 'on'
        prefs.cart_updates = request.POST.get('cart_updates') == 'on'
        prefs.order_updates = request.POST.get('order_updates') == 'on'
        prefs.promotions = request.POST.get('promotions') == 'on'
        prefs.save()
        
        messages.success(request, "Notification preferences updated!")
        return redirect('accounts:notification_preferences')
    
    return render(request, 'accounts/notification_preferences.html', {'prefs': prefs})

@login_required
def delete_account(request):
    """Delete user account"""
    if request.method == 'POST':
        password = request.POST.get('password')
        confirm = request.POST.get('confirm') == 'on'
        
        if not confirm:
            messages.error(request, "Please confirm account deletion.")
            return render(request, 'accounts/delete_account.html')
        
        if not request.user.check_password(password):
            messages.error(request, "Incorrect password.")
            return render(request, 'accounts/delete_account.html')
        
        try:
            UserActivityLog.objects.create(
                user=request.user,
                action='account_deleted',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                details={'reason': request.POST.get('reason', '')}
            )
        except Exception as e:
            logger.error(f"Failed to log account deletion: {e}")
        
        username = request.user.username
        logout(request)
        User.objects.filter(username=username).delete()
        
        messages.success(request, f"Account '{username}' has been deleted successfully.")
        return redirect('home')
    
    return render(request, 'accounts/delete_account.html')

# ==================== RESEND OTP FUNCTIONS ====================

@require_http_methods(["POST"])
@csrf_exempt
def resend_password_otp(request):
    """Resend OTP for password reset"""
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'error': 'Session expired'})
    
    try:
        user = User.objects.get(id=user_id)
        otp = create_otp(user, user.email, 'password_reset')
        if otp:
            return JsonResponse({'success': True, 'message': 'OTP resent successfully'})
        return JsonResponse({'success': False, 'error': 'Failed to send OTP'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'})

@require_http_methods(["POST"])
@csrf_exempt
def resend_2fa_otp(request):
    """Resend OTP for 2FA verification"""
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'error': 'Session expired'})
    
    try:
        user = User.objects.get(id=user_id)
        otp = create_otp(user, user.email, 'login')
        if otp:
            create_notification(user, 'system', '📧 2FA Code Resent', 'A new verification code has been sent to your email.', '/accounts/login/')
            return JsonResponse({'success': True, 'message': 'OTP resent successfully'})
        return JsonResponse({'success': False, 'error': 'Failed to send OTP'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'})

@require_http_methods(["POST"])
@csrf_exempt
def resend_2fa_setup_otp(request):
    """Resend OTP for 2FA setup"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    otp = create_otp(request.user, request.user.email, 'login')
    if otp:
        create_notification(request.user, 'system', '📧 2FA Setup Code Resent', f'A new verification code has been sent to {request.user.email}', '/accounts/enable-2fa/')
        return JsonResponse({'success': True, 'message': 'Verification code resent successfully'})
    return JsonResponse({'success': False, 'error': 'Failed to send verification code'})

@login_required
@require_http_methods(["POST"])
def send_phone_verification(request):
    """Phone verification is paused until SMS delivery is needed."""
    return JsonResponse({
        'success': False,
        'error': 'Phone verification is not required right now. Please use email verification.',
    })

@login_required
@require_http_methods(["POST"])
def send_verification_email(request):
    """Send email verification OTP"""
    otp = create_otp(request.user, request.user.email, 'email')
    if otp:
        return JsonResponse({'success': True, 'message': 'Verification email sent'})
    return JsonResponse({'success': False, 'error': 'Failed to send email'})
