import random
import string
import logging
from django.utils import timezone
from django.conf import settings
from accounts.models import UserOTP, User, UserActivityLog
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from accounts.tokens import account_activation_token
from datetime import timedelta

logger = logging.getLogger(__name__)

def mask_destination(value, visible=4):
    value = str(value or '')
    if len(value) <= visible:
        return '*' * len(value)
    return f"{'*' * (len(value) - visible)}{value[-visible:]}"

def generate_otp(length=6):
    """Generate a random OTP code"""
    return ''.join(random.choices(string.digits, k=length))

def create_otp(user, destination, otp_type='email'):
    """
    Create an OTP for a user
    
    Args:
        user: User object
        destination: Where to send the OTP (email address or phone number)
        otp_type: 'email', 'phone', 'login', 'password_reset', 'two_factor'
    """
    # Generate OTP code
    otp_code = generate_otp()
    
    # Calculate expiry time (10 minutes from now)
    expiry_time = timezone.now() + timedelta(minutes=10)
    
    # Create OTP record
    otp = UserOTP.objects.create(
        user=user,
        otp_code=otp_code,
        otp_type=otp_type,
        destination=destination,
        expires_at=expiry_time,
        is_used=False,
        attempts=0
    )
    
    # Send OTP based on type. If delivery fails, delete the code so the UI
    # does not claim that an unusable OTP was sent.
    if otp_type in ['email', 'login', 'password_reset', 'two_factor'] and destination:
        if not send_otp_email(destination, otp_code, otp_type, user=user):
            otp.delete()
            return None
    elif otp_type == 'phone' and destination:
        if not send_otp_sms(destination, otp_code):
            otp.delete()
            return None
    
    # Log activity
    try:
        UserActivityLog.objects.create(
            user=user,
            action='login' if otp_type == 'login' else 'password_reset',
            ip_address=None,
            details={'otp_sent_to': destination, 'otp_type': otp_type}
        )
    except:
        pass  # Activity logging is optional
    
    return otp

def verify_otp(identifier, otp_code, otp_type='login'):
    """Verify an OTP code for a user"""
    try:
        # Get user by email or id
        if isinstance(identifier, User):
            user = identifier
        elif isinstance(identifier, int):
            user = User.objects.get(id=identifier)
        else:
            user = User.objects.get(email=identifier)
        
        # Find valid OTP
        otp = UserOTP.objects.filter(
            user=user,
            otp_code=otp_code,
            otp_type=otp_type,
            is_used=False,
            expires_at__gt=timezone.now()
        ).latest('created_at')
        
        # Check attempts limit
        if otp.attempts >= 3:
            return False, "Too many failed attempts. Please request a new OTP."
        
        # Mark as used
        otp.is_used = True
        otp.save()
        
        # Log successful verification
        try:
            UserActivityLog.objects.create(
                user=user,
                action='email_verified' if otp_type == 'email' else 'login',
                details={'otp_type': otp_type, 'verified': True}
            )
        except:
            pass
        
        return True, "OTP verified successfully"
        
    except User.DoesNotExist:
        return False, "User not found"
    except UserOTP.DoesNotExist:
        return False, "Invalid or expired OTP"

def send_otp_email(email, otp_code, otp_type='email', user=None):
    """Send OTP via email"""
    try:
        validate_email(email)
    except ValidationError:
        logger.warning('OTP email rejected because the destination is invalid: %s', email)
        return False

    if not getattr(settings, 'EMAIL_CONFIGURED', True):
        logger.error(
            'OTP email cannot be sent because production email is not configured. '
            'Set SENDGRID_API_KEY or RESEND_API_KEY for HTTPS email delivery, '
            'or enable SMTP only on a Railway plan that supports it.'
        )
        return False

    subject_map = {
        'email': "Email Verification - Arolana",
        'login': "Login Verification Code - Arolana",
        'password_reset': "Password Reset Code - Arolana",
        'two_factor': "Two-Factor Authentication - Arolana",
    }
    
    subject = subject_map.get(otp_type, "Verification Code - Arolana")
    
    verification_url = ''
    if user and otp_type == 'email':
        try:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = account_activation_token.make_token(user)
            verification_url = f"{settings.SITE_URL.rstrip('/')}{reverse('accounts:verify_email_token', kwargs={'uidb64': uid, 'token': token})}"
        except Exception as e:
            logger.warning('Could not build email verification link for %s: %s', email, e)

    context = {
        'user': user,
        'otp_code': otp_code,
        'otp_type': otp_type.replace('_', ' ').title(),
        'validity_minutes': 10,
        'verification_url': verification_url,
    }
    html_message = render_to_string('accounts/email/otp_email.html', context)
    message = strip_tags(html_message)
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
            html_message=html_message,
        )
        return True
    except Exception as e:
        logger.exception('Failed to send OTP email to %s: %s', email, e)
        return False

def send_otp_sms(phone_number, otp_code):
    """Send OTP via SMS using Twilio."""
    if not getattr(settings, 'SMS_CONFIGURED', False):
        logger.error(
            'OTP SMS cannot be sent because SMS is not configured. '
            'Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and either '
            'TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID.'
        )
        return False

    try:
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client
    except ImportError as e:
        logger.exception('Twilio package is not available: %s', e)
        return False

    destination = str(phone_number).strip()
    body = settings.SMS_OTP_MESSAGE.format(code=otp_code)
    message_kwargs = {
        'body': body,
        'to': destination,
    }
    if settings.TWILIO_MESSAGING_SERVICE_SID:
        message_kwargs['messaging_service_sid'] = settings.TWILIO_MESSAGING_SERVICE_SID
    else:
        message_kwargs['from_'] = settings.TWILIO_FROM_NUMBER

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(**message_kwargs)
        logger.info('OTP SMS sent to %s via Twilio message %s', mask_destination(destination), message.sid)
        return True
    except TwilioRestException as e:
        logger.exception('Twilio rejected OTP SMS to %s: %s', mask_destination(destination), e)
        return False
    except Exception as e:
        logger.exception('Failed to send OTP SMS to %s: %s', mask_destination(destination), e)
        return False

def cleanup_expired_otps():
    """Delete expired OTPs"""
    expired_count = UserOTP.objects.filter(
        expires_at__lt=timezone.now()
    ).count()
    
    UserOTP.objects.filter(expires_at__lt=timezone.now()).delete()
    return expired_count

def is_rate_limited(user, otp_type='login', max_attempts=5, time_window_minutes=15):
    """Check if user is rate limited for OTP requests"""
    time_threshold = timezone.now() - timedelta(minutes=time_window_minutes)
    
    recent_attempts = UserOTP.objects.filter(
        user=user,
        otp_type=otp_type,
        created_at__gt=time_threshold
    ).count()
    
    return recent_attempts >= max_attempts
