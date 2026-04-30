from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

class CustomAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        return '/'
    
    def send_mail(self, template_prefix, email, context):
        # For development, just print the email
        print(f"Sending email to {email}")
        print(f"Template: {template_prefix}")
        print(f"Context: {context}")
        return super().send_mail(template_prefix, email, context)

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # This is called just before a social login is done
        pass
    
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        user.user_type = 'customer'
        return user
