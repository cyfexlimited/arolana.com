from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom account adapter for Arolana"""
    
    def get_login_redirect_url(self, request):
        """Redirect after login"""
        next_url = request.GET.get('next')
        if next_url:
            return next_url
        return reverse('home')
    
    def get_logout_redirect_url(self, request):
        """Redirect after logout"""
        return reverse('home')
    
    def get_signup_redirect_url(self, request):
        """Redirect after signup"""
        return reverse('home')
    
    def is_open_for_signup(self, request):
        """Allow signups"""
        return True
    
    def get_email_confirmation_url(self, request, emailconfirmation):
        """Custom email confirmation URL"""
        return reverse('account_confirm_email', args=[emailconfirmation.key])
    
    def send_mail(self, template_prefix, email, context):
        """Custom email sending"""
        msg = self.render_mail(template_prefix, email, context)
        msg.send()
    
    def clean_email(self, email):
        """Validate email"""
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user is already registered with this email address.')
        return email

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter for Arolana"""

    def list_apps(self, request, provider=None, client_id=None):
        """Prefer Railway/env Google credentials over stale database SocialApps."""
        apps = super().list_apps(request, provider=provider, client_id=client_id)
        google_client_id = getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '')
        google_secret = getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '')
        if not google_client_id or not google_secret:
            return apps

        filtered_apps = []
        google_app_added = False
        for app in apps:
            if app.provider != 'google':
                filtered_apps.append(app)
                continue
            if app.client_id == google_client_id and not google_app_added:
                filtered_apps.append(app)
                google_app_added = True
        return filtered_apps
    
    def pre_social_login(self, request, sociallogin):
        """Handle pre-social login"""
        pass
    
    def is_open_for_signup(self, request, sociallogin):
        """Allow social signups"""
        return True
    
    def populate_user(self, request, sociallogin, data):
        """Populate user from social data"""
        user = super().populate_user(request, sociallogin, data)
        
        # Set email from social provider
        if 'email' in data:
            user.email = data['email']
        
        return user

    def save_user(self, request, sociallogin, form=None):
        """Create a complete Arolana customer account from Google signup."""
        user = super().save_user(request, sociallogin, form)
        provider = getattr(sociallogin.account, 'provider', '')

        if provider == 'google':
            user.google_id = sociallogin.account.uid

        if not user.user_type:
            user.user_type = 'customer'

        verified_social_email = any(
            address.email.lower() == user.email.lower() and address.verified
            for address in getattr(sociallogin, 'email_addresses', [])
            if address.email and user.email
        )
        if provider == 'google' or verified_social_email:
            user.email_verified = True

        user.save(update_fields=['google_id', 'user_type', 'email_verified', 'updated_at'])

        from .models import UserProfile
        from .utils.messaging import send_registration_messages, sync_newsletter_subscriber

        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'newsletter_subscription': True,
                'promo_emails': True,
                'marketing_emails': True,
            }
        )
        sync_newsletter_subscriber(user, subscribe=True, source=provider or 'social')
        send_registration_messages(user, request)
        return user
    
    def get_connect_redirect_url(self, request, socialaccount):
        """Redirect after connecting social account"""
        return reverse('accounts:profile')
