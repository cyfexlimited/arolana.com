import random
import string
from django.utils import timezone
from django.conf import settings
from accounts.models import UserOTP, User, UserActivityLog
from django.core.mail import send_mail
from datetime import timedelta

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
    
    # Send OTP based on type
    if otp_type in ['email', 'login', 'password_reset', 'two_factor'] and destination:
        send_otp_email(destination, otp_code, otp_type)
    elif otp_type == 'phone' and destination:
        send_otp_sms(destination, otp_code)
    
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
        if isinstance(identifier, int):
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

def send_otp_email(email, otp_code, otp_type='email'):
    """Send OTP via email"""
    subject_map = {
        'email': "Email Verification - Arolana",
        'login': "Login Verification Code - Arolana",
        'password_reset': "Password Reset Code - Arolana",
        'two_factor': "Two-Factor Authentication - Arolana",
    }
    
    subject = subject_map.get(otp_type, "Verification Code - Arolana")
    
    message = f"""
Hello,

Your verification code is: {otp_code}

This code will expire in 10 minutes.
Type: {otp_type.replace('_', ' ').title()}

If you didn't request this, please ignore this email.

Best regards,
Arolana Security Team
"""
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send OTP email: {e}")
        return False

def send_otp_sms(phone_number, otp_code):
    """Send OTP via SMS (placeholder - implement with SMS service)"""
    print(f"SMS to {phone_number}: Your OTP is {otp_code}")
    # TODO: Integrate with Twilio or other SMS service
    return True

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
