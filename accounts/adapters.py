from allauth.account.adapter import DefaultAccountAdapter
from allauth.account import app_settings as account_app_settings
from allauth.account.utils import perform_login
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount import signals as socialaccount_signals
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from .redirects import (
    clear_auth_handoff_session,
    remember_login_redirect,
    resolve_post_login_redirect,
    safe_login_redirect_url,
)
from .utils.email_subjects import format_arolana_subject

User = get_user_model()

class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom account adapter for Arolana"""
    
    def get_login_redirect_url(self, request):
        """Use the same safe destination resolver as the custom login flow."""
        return resolve_post_login_redirect(request)

    def post_login(
        self,
        request,
        user,
        *,
        email_verification,
        signal_kwargs,
        email,
        signup,
        redirect_url,
    ):
        """
        Route allauth/social logins through the shared one-time session state.

        allauth normally gives its OAuth state URL directly to ``post_login``.
        Promoting it into our safe session value lets the shared resolver clear
        that temporary state after the callback.
        """
        remember_login_redirect(request, redirect_url)
        destination = resolve_post_login_redirect(request, user)
        return super().post_login(
            request,
            user,
            email_verification=email_verification,
            signal_kwargs=signal_kwargs,
            email=email,
            signup=signup,
            redirect_url=destination,
        )

    def is_safe_url(self, url):
        """Restrict allauth return URLs to the current/approved internal host."""
        request = getattr(self, "request", None)
        return bool(request and safe_login_redirect_url(request, url))
    
    def get_logout_redirect_url(self, request):
        """Redirect after logout"""
        clear_auth_handoff_session(request)
        return reverse('home')
    
    def get_signup_redirect_url(self, request):
        """Redirect after signup"""
        return resolve_post_login_redirect(request)
    
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

    def format_email_subject(self, subject):
        """Ensure allauth never repeats the Arolana subject prefix."""
        return format_arolana_subject(subject)
    
    def clean_email(self, email):
        """Validate email"""
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('A user is already registered with this email address.')
        return email

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom social account adapter for Arolana"""

    def _verified_social_email(self, sociallogin):
        """Return the provider-verified email address, if one is available."""
        account = getattr(sociallogin, 'account', None)
        provider = getattr(account, 'provider', '')
        extra_data = getattr(account, 'extra_data', {}) or {}

        for address in getattr(sociallogin, 'email_addresses', []):
            email = getattr(address, 'email', '')
            if email and getattr(address, 'verified', False):
                return email

        email = (
            extra_data.get('email')
            or getattr(getattr(sociallogin, 'user', None), 'email', '')
        )
        email_verified = extra_data.get('email_verified')
        if provider == 'google' and email and email_verified is True:
            return email
        return ''

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
        """
        Retain the callback destination and safely attach verified Google
        logins to existing Arolana accounts with the same email.

        Without this hook, allauth sends an existing email through the social
        signup form where our unique-email validation rejects it as
        "already registered" even though the user has just authenticated with
        Google.
        """
        remember_login_redirect(request, sociallogin.get_redirect_url(request))

        if sociallogin.is_existing:
            return

        verified_email = self._verified_social_email(sociallogin)
        if not verified_email:
            return

        existing_user = (
            User.objects.filter(email__iexact=verified_email, is_active=True)
            .order_by('pk')
            .first()
        )
        if not existing_user:
            return

        sociallogin.user = existing_user
        sociallogin.save(request, connect=True)
        socialaccount_signals.social_account_added.send(
            sender=sociallogin.__class__,
            request=request,
            sociallogin=sociallogin,
        )

        provider = getattr(sociallogin.account, 'provider', '')
        if provider == 'google' and hasattr(existing_user, 'google_id'):
            existing_user.google_id = sociallogin.account.uid
            if hasattr(existing_user, 'email_verified'):
                existing_user.email_verified = True
            existing_user.save(
                update_fields=['google_id', 'email_verified', 'updated_at']
            )

        response = perform_login(
            request,
            existing_user,
            email_verification=account_app_settings.EmailVerificationMethod.NONE,
            signup=False,
            email=verified_email,
        )
        raise ImmediateHttpResponse(response)
    
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
        from .utils.messaging import (
            send_registration_messages_once,
            sync_newsletter_subscriber,
        )

        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'newsletter_subscription': False,
                'promo_emails': False,
                'marketing_emails': False,
            }
        )
        sync_newsletter_subscriber(user, subscribe=False, source=provider or 'social')
        send_registration_messages_once(user, request)
        return user
    
    def get_connect_redirect_url(self, request, socialaccount):
        """Redirect after connecting social account"""
        return reverse('accounts:profile')
