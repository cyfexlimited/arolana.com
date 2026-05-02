from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.sessions.models import Session
import logging
import random
import string

from .models import User, UserProfile, UserOTP, UserActivityLog, NewsletterSubscriber, Address
from products.models import RecentlyViewed, Wishlist
from .utils.otp_utils import create_otp, verify_otp

logger = logging.getLogger(__name__)

# Import notification models
try:
    from notifications.models import Notification
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False
    print("⚠️ Notifications app not installed")

def create_notification(user, notification_type, title, message, link=''):
    """Helper function to create notification"""
    if NOTIFICATIONS_AVAILABLE and user:
        try:
            Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                message=message,
                link=link
            )
            print(f"✅ Notification created for {user.username}: {title}")
        except Exception as e:
            print(f"Error creating notification: {e}")

def newsletter_subscribe(request):
    """Handle newsletter subscription (no login required)"""
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
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
        else:
            messages.error(request, 'Please provide a valid email address.')
        return redirect(request.META.get('HTTP_REFERER', '/'))
    return redirect('/')

def login_view(request):
    """Enhanced login with email/phone and OTP support"""
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        identifier = request.POST.get('identifier')
        password = request.POST.get('password')
        
        # Try to find user by email or phone
        user = None
        if '@' in identifier:
            try:
                user = User.objects.get(email=identifier)
            except User.DoesNotExist:
                pass
        else:
            try:
                user = User.objects.get(phone_number=identifier)
            except User.DoesNotExist:
                pass
        
        if user and user.check_password(password):
            # Get IP address for notification
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            # Check if 2FA is enabled
            if getattr(user, 'two_factor_enabled', False):
                # Send OTP and redirect to verification
                otp = create_otp(user, user.email, 'login')
                if otp:
                    request.session['pre_2fa_user_id'] = user.id
                    messages.success(request, f"Please enter the OTP sent to {user.email}")
                    return redirect('accounts:verify_2fa')
                else:
                    messages.error(request, "Failed to send OTP. Please try again.")
            else:
                # Regular login
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                
                # Log activity
                try:
                    UserActivityLog.objects.create(
                        user=user,
                        action='login',
                        ip_address=ip_address,
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                        details={'method': 'password'}
                    )
                except Exception as e:
                    logger.error(f"Failed to log activity: {e}")
                
                # Create login notification
                create_notification(
                    user,
                    'login',
                    '🔐 New Login Detected',
                    f'You logged in from IP: {ip_address} at {timezone.now().strftime("%I:%M %p")}',
                    '/accounts/profile/'
                )
                
                messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
                
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
        else:
            # Log failed attempt
            try:
                UserActivityLog.objects.create(
                    user=None,
                    action='failed_login',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    details={'identifier': identifier[:50] if identifier else 'unknown'}
                )
            except Exception as e:
                logger.error(f"Failed to log failed login: {e}")
            
            messages.error(request, "Invalid email/phone or password.")
    
    return render(request, 'accounts/login.html')

def register_view(request):
    """Enhanced registration with email/phone verification"""
    if request.method == 'POST':
        email = request.POST.get('email')
        username = request.POST.get('username')
        phone_number = request.POST.get('phone_number')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('accounts:register')
        
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered.")
            return redirect('accounts:register')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return redirect('accounts:register')
        
        if phone_number and User.objects.filter(phone_number=phone_number).exists():
            messages.error(request, "Phone number already registered.")
            return redirect('accounts:register')
        
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password
        )
        
        # Set backend for new user
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        
        # Create user profile
        UserProfile.objects.create(user=user)
        
        if phone_number:
            user.phone_number = phone_number
            user.save()
        
        # Create welcome notification
        create_notification(
            user,
            'signup',
            '🎉 Welcome to Arolana!',
            'Thank you for joining Arolana.com. Start exploring our products and enjoy exclusive deals!',
            '/products/'
        )
        
        # Send email verification OTP
        otp = create_otp(user, email, 'email')
        if otp:
            request.session['pending_user_id'] = user.id
            messages.success(request, "Please verify your email address with the OTP sent.")
            return redirect('accounts:verify_email')
        else:
            # Even if OTP fails, user is created
            login(request, user)
            messages.success(request, f"Welcome to Arolana, {username}! Your account has been created.")
            return redirect('home')
    
    return render(request, 'accounts/register.html')

def logout_view(request):
    """Enhanced logout with activity logging"""
    if request.user.is_authenticated:
        # Create logout notification
        create_notification(
            request.user,
            'logout',
            '👋 Logged Out',
            'You have been logged out of your account',
            '/accounts/login/'
        )
        
        try:
            UserActivityLog.objects.create(
                user=request.user,
                action='logout',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                details={}
            )
        except Exception as e:
            logger.error(f"Failed to log logout: {e}")
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('home')

@login_required
def profile_view(request):
    return render(request, 'accounts/profile.html', {'user': request.user})

@login_required
def wishlist_view(request):
    wishlist_items = Wishlist.objects.filter(user=request.user)
    return render(request, 'accounts/wishlist.html', {'wishlist_items': wishlist_items})

@login_required
def browsing_history(request):
    history = RecentlyViewed.objects.filter(user=request.user).order_by('-viewed_at')[:50]
    return render(request, 'accounts/browsing_history.html', {'history': history})

@login_required
def subscriptions_view(request):
    if request.method == 'POST':
        # Update profile preferences
        profile = request.user.profile
        profile.newsletter_subscription = request.POST.get('newsletter') == 'on'
        profile.promo_emails = request.POST.get('promo_emails') == 'on'
        profile.order_updates = request.POST.get('order_updates') == 'on'
        profile.marketing_emails = request.POST.get('marketing_emails') == 'on'
        profile.save()
        
        # Create notification
        create_notification(
            request.user,
            'system',
            '📧 Email Preferences Updated',
            'Your email subscription preferences have been updated.',
            '/accounts/subscriptions/'
        )
        
        messages.success(request, 'Your email preferences have been updated!')
        return redirect('accounts:subscriptions')
    
    return render(request, 'accounts/subscriptions.html')

def verify_2fa(request):
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        return redirect('accounts:login')
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        success, message = verify_otp(user, otp_code, 'login')
        
        if success:
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            del request.session['pre_2fa_user_id']
            
            # Create login notification for 2FA login
            create_notification(
                user,
                'login',
                '🔐 2FA Login Successful',
                f'You logged in using two-factor authentication',
                '/accounts/profile/'
            )
            
            try:
                UserActivityLog.objects.create(
                    user=user,
                    action='login_2fa',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    details={'method': '2fa_otp'}
                )
            except Exception as e:
                logger.error(f"Failed to log 2fa login: {e}")
            
            messages.success(request, f"Welcome back, {user.get_full_name() or user.email}!")
            next_url = request.GET.get('next', 'home')
            return redirect(next_url)
        else:
            messages.error(request, message)
    
    return render(request, 'accounts/verify_2fa.html', {'user': user})

def verify_email(request):
    user_id = request.session.get('pending_user_id')
    if not user_id:
        return redirect('accounts:register')
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        success, message = verify_otp(user, otp_code, 'email')
        
        if success:
            del request.session['pending_user_id']
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user)
            
            # Create email verification notification
            create_notification(
                user,
                'system',
                '✅ Email Verified',
                'Your email address has been successfully verified!',
                '/accounts/profile/'
            )
            
            messages.success(request, "Email verified successfully! Welcome to Arolana.")
            return redirect('home')
        else:
            messages.error(request, message)
    
    return render(request, 'accounts/verify_email.html', {'user': user})

def forgot_password(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier')
        
        user = None
        if '@' in identifier:
            try:
                user = User.objects.get(email=identifier)
            except User.DoesNotExist:
                pass
        else:
            try:
                user = User.objects.get(phone_number=identifier)
            except User.DoesNotExist:
                pass
        
        if user:
            otp = create_otp(user, identifier, 'password_reset')
            if otp:
                request.session['reset_user_id'] = user.id
                messages.success(request, f"Password reset OTP sent to {identifier}")
                return redirect('accounts:reset_password_verify')
            else:
                messages.error(request, "Failed to send OTP. Please try again.")
        else:
            messages.warning(request, "If an account exists with that email/phone, you will receive an OTP.")
    
    return render(request, 'accounts/forgot_password.html')

def reset_password_verify(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('accounts:forgot_password')
    
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('accounts:reset_password_verify')
        
        success, message = verify_otp(user, otp_code, 'password_reset')
        
        if success:
            user.set_password(new_password)
            user.save()
            del request.session['reset_user_id']
            
            # Create password reset notification
            create_notification(
                user,
                'system',
                '🔑 Password Changed',
                'Your password has been successfully changed.',
                '/accounts/login/'
            )
            
            try:
                UserActivityLog.objects.create(
                    user=user,
                    action='password_reset',
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                    details={'method': 'otp'}
                )
            except Exception as e:
                logger.error(f"Failed to log password reset: {e}")
            
            messages.success(request, "Password reset successfully! Please login with your new password.")
            return redirect('accounts:login')
        else:
            messages.error(request, message)
    
    return render(request, 'accounts/reset_password_verify.html', {'user': user})

@require_http_methods(["POST"])
@csrf_exempt
def resend_password_otp(request):
    """Resend OTP for password reset"""
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'error': 'Session expired'})
    
    try:
        user = User.objects.get(id=user_id)
        # Send new OTP
        otp = create_otp(user, user.email, 'password_reset')
        if otp:
            return JsonResponse({'success': True, 'message': 'OTP resent successfully'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to send OTP'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'})

def enable_2fa(request):
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code')
        success, message = verify_otp(request.user, otp_code, 'login')
        
        if success:
            request.user.two_factor_enabled = True
            request.user.save()
            
            # Generate backup codes (optional)
            backup_codes = [''.join(random.choices(string.digits, k=8)) for _ in range(8)]
            
            create_notification(
                request.user,
                'system',
                '🛡️ 2FA Enabled',
                'Two-factor authentication has been enabled on your account.',
                '/accounts/security/'
            )
            
            messages.success(request, "2FA enabled successfully!")
            return render(request, 'accounts/enable_2fa.html', {
                'backup_codes': backup_codes
            })
        else:
            messages.error(request, message)
    
    create_otp(request.user, request.user.email, 'login')
    messages.info(request, f"An OTP has been sent to {request.user.email}")
    
    return render(request, 'accounts/enable_2fa.html')

def disable_2fa(request):
    """Disable 2FA with password confirmation"""
    if request.method == 'POST':
        password = request.POST.get('password')
        
        if not request.user.check_password(password):
            messages.error(request, "Incorrect password. Please try again.")
            return render(request, 'accounts/disable_2fa.html')
        
        request.user.two_factor_enabled = False
        request.user.save()
        
        # Create notification
        create_notification(
            request.user,
            'system',
            '🔓 2FA Disabled',
            'Two-factor authentication has been disabled on your account.',
            '/accounts/security/'
        )
        
        messages.success(request, "Two-factor authentication has been disabled.")
        return redirect('accounts:security_settings')
    
    return render(request, 'accounts/disable_2fa.html')

def recover_2fa(request):
    """Recover 2FA using backup codes"""
    if request.method == 'POST':
        backup_code = request.POST.get('backup_code')
        
        # Check if backup code matches (implement your backup code logic)
        # For now, just redirect
        messages.success(request, "2FA has been disabled using backup code.")
        return redirect('accounts:security_settings')
    
    return render(request, 'accounts/recover_2fa.html')

@login_required
def security_settings(request):
    recent_activities = UserActivityLog.objects.filter(user=request.user)[:10]
    
    context = {
        'user': request.user,
        'recent_activities': recent_activities,
        'has_2fa': getattr(request.user, 'two_factor_enabled', False),
        'email_verified': getattr(request.user, 'email_verified', False),
        'phone_verified': getattr(request.user, 'phone_verified', False),
    }
    return render(request, 'accounts/security_settings.html', context)

@login_required
def edit_profile(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        phone_number = request.POST.get('phone_number')
        
        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.phone_number = phone_number
        
        if request.FILES.get('avatar'):
            request.user.avatar = request.FILES.get('avatar')
        
        request.user.save()
        
        if hasattr(request.user, 'profile'):
            request.user.profile.bio = request.POST.get('bio')
            newsletter = request.POST.get('newsletter') == 'on'
            request.user.profile.newsletter_subscription = newsletter
            request.user.profile.save()
        
        # Create profile update notification
        create_notification(
            request.user,
            'system',
            '👤 Profile Updated',
            'Your profile information has been updated successfully.',
            '/accounts/profile/'
        )
        
        messages.success(request, "Profile updated successfully!")
        return redirect('accounts:profile')
    
    return render(request, 'accounts/edit_profile.html')

@login_required
def change_password(request):
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        if not request.user.check_password(current_password):
            messages.error(request, "Current password is incorrect.")
            return redirect('accounts:change_password')
        
        if new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
            return redirect('accounts:change_password')
        
        # Password strength validation
        if len(new_password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect('accounts:change_password')
        
        if not any(c.isupper() for c in new_password):
            messages.error(request, "Password must contain at least one uppercase letter.")
            return redirect('accounts:change_password')
        
        if not any(c.islower() for c in new_password):
            messages.error(request, "Password must contain at least one lowercase letter.")
            return redirect('accounts:change_password')
        
        if not any(c.isdigit() for c in new_password):
            messages.error(request, "Password must contain at least one number.")
            return redirect('accounts:change_password')
        
        request.user.set_password(new_password)
        request.user.save()
        
        # Set backend after password change
        request.user.backend = 'django.contrib.auth.backends.ModelBackend'
        
        # Create password change notification
        create_notification(
            request.user,
            'system',
            '🔑 Password Changed',
            'Your password has been changed successfully.',
            '/accounts/profile/'
        )
        
        try:
            UserActivityLog.objects.create(
                user=request.user,
                action='password_change',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                details={'method': 'manual'}
            )
        except Exception as e:
            logger.error(f"Failed to log password change: {e}")
        
        messages.success(request, "Password changed successfully! Please login with your new password.")
        return redirect('accounts:login')
    
    return render(request, 'accounts/change_password.html')

@require_http_methods(["POST"])
def send_verification_email(request):
    """Send email verification OTP"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    otp = create_otp(request.user, request.user.email, 'email')
    if otp:
        return JsonResponse({'success': True, 'message': 'Verification email sent'})
    return JsonResponse({'success': False, 'error': 'Failed to send email'})

@require_http_methods(["POST"])
def send_phone_verification(request):
    """Send phone verification OTP"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    if not request.user.phone_number:
        return JsonResponse({'success': False, 'error': 'No phone number on file'})
    
    otp = create_otp(request.user, request.user.phone_number, 'phone')
    if otp:
        return JsonResponse({'success': True, 'message': 'Verification code sent'})
    return JsonResponse({'success': False, 'error': 'Failed to send code'})

@require_http_methods(["POST"])
def logout_all_devices(request):
    """Logout user from all other devices"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    # Keep current session
    current_session_key = request.session.session_key
    
    # Delete all other sessions for this user
    for session in Session.objects.all():
        session_data = session.get_decoded()
        if session_data.get('_auth_user_id') == str(request.user.id) and session.session_key != current_session_key:
            session.delete()
    
    # Create notification
    create_notification(
        request.user,
        'system',
        '🔐 Logged out from other devices',
        'You have been logged out from all other devices.',
        '/accounts/security/'
    )
    
    return JsonResponse({'success': True, 'message': 'Logged out from other devices'})

@require_http_methods(["GET"])
def recent_activity_api(request):
    """API endpoint to get recent activities"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    activities = UserActivityLog.objects.filter(user=request.user)[:20].values(
        'action', 'timestamp', 'ip_address', 'user_agent'
    )
    
    return JsonResponse({
        'success': True,
        'activities': list(activities)
    })

@require_http_methods(["POST"])
@csrf_exempt
def resend_2fa_otp(request):
    """Resend OTP for 2FA verification"""
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'error': 'Session expired'})
    
    try:
        user = User.objects.get(id=user_id)
        # Send new OTP
        otp = create_otp(user, user.email, 'login')
        if otp:
            # Create notification for resend
            create_notification(
                user,
                'system',
                '📧 2FA Code Resent',
                'A new verification code has been sent to your email.',
                '/accounts/login/'
            )
            return JsonResponse({'success': True, 'message': 'OTP resent successfully'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to send OTP'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'})

@require_http_methods(["POST"])
@csrf_exempt
def resend_verification_email(request):
    """Resend email verification OTP"""
    user_id = request.session.get('pending_user_id')
    if not user_id:
        return JsonResponse({'success': False, 'error': 'Session expired'})
    
    try:
        user = User.objects.get(id=user_id)
        # Send new OTP
        otp = create_otp(user, user.email, 'email')
        if otp:
            # Create notification
            create_notification(
                user,
                'system',
                '📧 Verification Code Resent',
                f'A new verification code has been sent to {user.email}',
                '/accounts/verify-email/'
            )
            return JsonResponse({'success': True, 'message': 'Verification code resent successfully'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to send verification code'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'})

@require_http_methods(["POST"])
@csrf_exempt
def resend_2fa_setup_otp(request):
    """Resend OTP for 2FA setup"""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Not authenticated'})
    
    # Send new OTP
    otp = create_otp(request.user, request.user.email, 'login')
    if otp:
        # Create notification
        create_notification(
            request.user,
            'system',
            '📧 2FA Setup Code Resent',
            f'A new verification code has been sent to {request.user.email}',
            '/accounts/enable-2fa/'
        )
        return JsonResponse({'success': True, 'message': 'Verification code resent successfully'})
    else:
        return JsonResponse({'success': False, 'error': 'Failed to send verification code'})

@login_required
def edit_address(request, pk):
    from .models import Address
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    if request.method == 'POST':
        address.address_line1 = request.POST.get('address_line1')
        address.address_line2 = request.POST.get('address_line2', '')
        address.city = request.POST.get('city')
        address.state = request.POST.get('state')
        address.postal_code = request.POST.get('postal_code')
        address.country = request.POST.get('country')
        address.address_type = request.POST.get('address_type', 'home')
        address.is_default = request.POST.get('is_default') == 'on'
        
        address.save()
        
        # Create notification
        create_notification(
            request.user,
            'system',
            '📍 Address Updated',
            f'Your {address.get_address_type_display()} address has been updated successfully.',
            '/accounts/addresses/'
        )
        
        messages.success(request, 'Address updated successfully!')
        return redirect('accounts:addresses')
    
    return render(request, 'accounts/edit_address.html', {'address': address})

@login_required
def add_address(request):
    from .models import Address
    if request.method == 'POST':
        address = Address.objects.create(
            user=request.user,
            address_line1=request.POST.get('address_line1'),
            address_line2=request.POST.get('address_line2', ''),
            city=request.POST.get('city'),
            state=request.POST.get('state'),
            postal_code=request.POST.get('postal_code'),
            country=request.POST.get('country'),
            address_type=request.POST.get('address_type', 'home'),
            is_default=request.POST.get('is_default') == 'on'
        )
        
        # Create notification
        create_notification(
            request.user,
            'system',
            '📍 New Address Added',
            f'A new {address.get_address_type_display()} address has been added to your account.',
            '/accounts/addresses/'
        )
        
        messages.success(request, 'Address added successfully!')
        return redirect('accounts:addresses')
    
    return render(request, 'accounts/add_address.html')

@login_required
def set_default_address(request, pk):
    from .models import Address
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    # Set all addresses as not default
    Address.objects.filter(user=request.user).update(is_default=False)
    
    # Set this address as default
    address.is_default = True
    address.save()
    
    # Create notification
    create_notification(
        request.user,
        'system',
        '📍 Default Address Updated',
        f'Your {address.get_address_type_display()} address has been set as default.',
        '/accounts/addresses/'
    )
    
    messages.success(request, 'Default address updated successfully!')
    return redirect('accounts:addresses')

@login_required
def clear_browsing_history(request):
    """Clear all browsing history"""
    RecentlyViewed.objects.filter(user=request.user).delete()
    
    # Create notification
    create_notification(
        request.user,
        'system',
        '🗑️ History Cleared',
        'Your browsing history has been cleared.',
        '/accounts/browsing-history/'
    )
    
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

@login_required
def clear_wishlist(request):
    """Clear all wishlist items"""
    Wishlist.objects.filter(user=request.user).delete()
    
    # Create notification
    create_notification(
        request.user,
        'system',
        'Wishlist Cleared',
        'Your wishlist has been cleared.',
        '/accounts/wishlist/'
    )
    
    messages.success(request, 'Wishlist cleared successfully!')
    return redirect('accounts:wishlist')

@login_required
def addresses_view(request):
    """Display all user addresses"""
    from .models import Address
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'accounts/addresses.html', {'addresses': addresses})

@login_required
def delete_address(request, pk):
    """Delete an address"""
    from .models import Address
    address = get_object_or_404(Address, id=pk, user=request.user)
    
    # If deleting default address, set another as default
    was_default = address.is_default
    address.delete()
    
    if was_default:
        # Set the first remaining address as default if any
        first_address = Address.objects.filter(user=request.user).first()
        if first_address:
            first_address.is_default = True
            first_address.save()
    
    # Create notification
    create_notification(
        request.user,
        'system',
        '🗑️ Address Deleted',
        f'Your address has been deleted.',
        '/accounts/addresses/'
    )
    
    messages.success(request, 'Address deleted successfully!')
    return redirect('accounts:addresses')
