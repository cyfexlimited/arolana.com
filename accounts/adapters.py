from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.shortcuts import redirect

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
    
    def get_connect_redirect_url(self, request, socialaccount):
        """Redirect after connecting social account"""
        return reverse('accounts:profile')