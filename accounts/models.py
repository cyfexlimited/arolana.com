from django.contrib.auth.models import AbstractUser
from django.db import models
from django_countries.fields import CountryField
from phonenumber_field.modelfields import PhoneNumberField
from core.models import BaseModel
from django.core.validators import RegexValidator
from .managers import CustomUserManager
import pyotp
from django.utils import timezone
from datetime import timedelta

class User(AbstractUser, BaseModel):
    USER_TYPES = (
        ('customer', 'Customer'),
        ('vendor', 'Vendor'),
        ('admin', 'Admin'),
        ('super_admin', 'Super Admin'),
    )
    
    # Authentication fields
    email = models.EmailField(unique=True)
    user_type = models.CharField(max_length=20, choices=USER_TYPES, default='customer')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    phone_number = PhoneNumberField(null=True, blank=True)
    country = CountryField(null=True, blank=True)
    
    # Verification fields
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)
    
    # OAuth fields
    google_id = models.CharField(max_length=255, blank=True, null=True)
    facebook_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Activity tracking
    last_seen = models.DateTimeField(null=True, blank=True)
    
    # Use email as username field for authentication
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']
    
    objects = CustomUserManager()
    
    class Meta:
        db_table = 'users'
        ordering = ['-date_joined']
        
    def __str__(self):
        return self.email
    
    @property
    def is_vendor(self):
        return self.user_type == 'vendor'
    
    @property
    def is_customer(self):
        return self.user_type == 'customer'
    
    @property
    def is_super_admin(self):
        return self.user_type == 'super_admin' or self.is_superuser
    
    @property
    def has_2fa(self):
        return self.two_factor_enabled
    
    def get_full_name(self):
        """Return the full name of the user"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
    
    def get_short_name(self):
        """Return the short name of the user"""
        return self.first_name or self.username

class UserProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True, default='avatars/default.png')
    bio = models.TextField(max_length=500, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    newsletter_subscription = models.BooleanField(default=True)
    promo_emails = models.BooleanField(default=True)
    order_updates = models.BooleanField(default=True)
    marketing_emails = models.BooleanField(default=False)
    
    # Additional fields for better profile management
    website = models.URLField(blank=True)
    location = models.CharField(max_length=100, blank=True)
    company = models.CharField(max_length=100, blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    
    def get_avatar_url(self):
        if self.avatar and self.avatar.url:
            return self.avatar.url
        return f'https://ui-avatars.com/api/?name={self.user.username}&background=0066b3&color=fff&size=32'
    
    def __str__(self):
        return f"{self.user.email}'s profile"

class Address(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=100)
    country = CountryField()
    is_default = models.BooleanField(default=False)
    is_billing = models.BooleanField(default=False)
    is_shipping = models.BooleanField(default=True)
    address_type = models.CharField(max_length=20, choices=[
        ('home', 'Home'),
        ('work', 'Work'),
        ('other', 'Other')
    ], default='home')
    phone_number = PhoneNumberField(null=True, blank=True)
    
    def save(self, *args, **kwargs):
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.address_line1}, {self.city}"

class NewsletterSubscriber(BaseModel):
    """Store newsletter subscribers"""
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=50, blank=True, help_text="Where they subscribed from")
    
    class Meta:
        ordering = ['-subscribed_at']
    
    def __str__(self):
        return self.email

class UserOTP(BaseModel):
    """OTP for email and phone verification"""
    OTP_TYPES = (
        ('email', 'Email Verification'),
        ('phone', 'Phone Verification'),
        ('login', 'Login OTP'),
        ('password_reset', 'Password Reset'),
        ('two_factor', '2FA Verification'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    otp_code = models.CharField(max_length=6)
    otp_type = models.CharField(max_length=20, choices=OTP_TYPES)
    destination = models.CharField(max_length=255, help_text="Email or phone number where OTP was sent")
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'otp_type', '-created_at']),
            models.Index(fields=['otp_code', 'is_used']),
        ]
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_used and self.expires_at > timezone.now() and self.attempts < 3
    
    def mark_used(self):
        """Mark OTP as used"""
        self.is_used = True
        self.save()
    
    def increment_attempts(self):
        """Increment failed attempts counter"""
        self.attempts += 1
        self.save()
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp_code} ({self.get_otp_type_display()})"

class UserActivityLog(models.Model):
    """Track user login activities for security"""
    ACTION_CHOICES = (
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('failed_login', 'Failed Login'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('email_verified', 'Email Verified'),
        ('phone_verified', 'Phone Verified'),
        ('2fa_enabled', '2FA Enabled'),
        ('2fa_disabled', '2FA Disabled'),
        ('account_locked', 'Account Locked'),
        ('profile_updated', 'Profile Updated'),
        ('address_added', 'Address Added'),
        ('address_updated', 'Address Updated'),
        ('address_deleted', 'Address Deleted'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities', null=True, blank=True)
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
    
    def __str__(self):
        if self.user:
            return f"{self.user.email} - {self.get_action_display()} at {self.timestamp}"
        return f"Anonymous - {self.get_action_display()} at {self.timestamp}"

class LoginAttempt(models.Model):
    """Track failed login attempts for security"""
    email = models.EmailField()
    ip_address = models.GenericIPAddressField()
    attempt_count = models.IntegerField(default=1)
    last_attempt = models.DateTimeField(auto_now=True)
    is_locked = models.BooleanField(default=False)
    locked_until = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ['email', 'ip_address']
        indexes = [
            models.Index(fields=['email', 'ip_address']),
            models.Index(fields=['is_locked', 'locked_until']),
        ]
    
    def __str__(self):
        return f"{self.email} - {self.attempt_count} attempts"
    
    def is_account_locked(self):
        """Check if account is currently locked"""
        if self.is_locked and self.locked_until:
            return self.locked_until > timezone.now()
        return False
    
    def increment_attempt(self):
        """Increment failed attempt counter"""
        self.attempt_count += 1
        if self.attempt_count >= 5:
            self.is_locked = True
            self.locked_until = timezone.now() + timedelta(minutes=15)
        self.save()
    
    def reset_attempts(self):
        """Reset failed attempts after successful login"""
        self.attempt_count = 0
        self.is_locked = False
        self.locked_until = None
        self.save()