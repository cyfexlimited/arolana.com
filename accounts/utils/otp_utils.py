import random
import string
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
from accounts.models import UserOTP
import logging

logger = logging.getLogger(__name__)

def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def create_otp(user, identifier, purpose):
    """Create and send OTP to user"""
    otp_code = generate_otp()
    expires_at = timezone.now() + timezone.timedelta(minutes=10)
    
    # Save OTP to database
    UserOTP.objects.create(
        user=user,
        otp=otp_code,
        purpose=purpose,
        identifier=identifier,
        expires_at=expires_at
    )
    
    # Prepare email based on purpose
    if purpose == 'email':
        subject = 'Verify Your Email Address - Arolana'
        template = 'emails/verification_email.html'
        verification_url = f"{settings.SITE_URL}/accounts/verify-email/"
    elif purpose == 'password_reset':
        subject = 'Password Reset Code - Arolana'
        template = 'emails/password_reset.html'
        verification_url = f"{settings.SITE_URL}/accounts/reset-password/"
    else:
        subject = 'Your Verification Code - Arolana'
        template = 'emails/verification_email.html'
        verification_url = f"{settings.SITE_URL}/accounts/verify/"
    
    # Prepare context for template
    context = {
        'user': user,
        'otp_code': otp_code,
        'verification_url': verification_url,
        'expires_minutes': 10,
    }
    
    # Render HTML email
    html_message = render_to_string(template, context)
    plain_message = strip_tags(html_message)
    
    # Send email
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[identifier],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"\n{'='*50}")
        print(f"📧 Email sent to: {identifier}")
        print(f"🔑 OTP Code: {otp_code}")
        print(f"📝 Purpose: {purpose}")
        print(f"⏰ Expires: {expires_at}")
        print(f"{'='*50}\n")
        
        return otp_code
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print(f"\n⚠️ Email failed. Your OTP is: {otp_code}\n")
        return otp_code

def verify_otp(user, otp_code, purpose):
    """Verify OTP code for user"""
    try:
        otp_record = UserOTP.objects.filter(
            user=user,
            otp=otp_code,
            purpose=purpose,
            is_used=False,
            expires_at__gt=timezone.now()
        ).latest('created_at')
        
        otp_record.is_used = True
        otp_record.used_at = timezone.now()
        otp_record.save()
        
        return True, "OTP verified successfully"
    except UserOTP.DoesNotExist:
        return False, "Invalid or expired OTP. Please request a new one."

def resend_otp(user, identifier, purpose):
    """Resend OTP to user"""
    UserOTP.objects.filter(
        user=user,
        purpose=purpose,
        is_used=False
    ).update(is_used=True)
    
    return create_otp(user, identifier, purpose)
