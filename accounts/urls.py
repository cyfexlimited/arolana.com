from django.urls import path, include
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication URLs
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('verify-email/', views.verify_email, name='verify_email'),
    
    # 2FA URLs
    path('verify-2fa/', views.verify_2fa, name='verify_2fa'),
    path('enable-2fa/', views.enable_2fa, name='enable_2fa'),
    path('disable-2fa/', views.disable_2fa, name='disable_2fa'),
    path('recover-2fa/', views.recover_2fa, name='recover_2fa'),
    
    # Password Management
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password/', views.reset_password_verify, name='reset_password_verify'),
    path('change-password/', views.change_password, name='change_password'),
    
    # User Profile
    path('profile/', views.profile_view, name='profile'),
    path('edit-profile/', views.edit_profile, name='edit_profile'),
    path('security/', views.security_settings, name='security_settings'),
    
    # Wishlist & History
    path('wishlist/', views.wishlist_view, name='wishlist'),
    path('clear-wishlist/', views.clear_wishlist, name='clear_wishlist'),
    path('browsing-history/', views.browsing_history, name='browsing_history'),
    path('clear-history/', views.clear_browsing_history, name='clear_history'),
    path('history/remove/<int:item_id>/', views.remove_history_item, name='remove_history_item'),
    
    # Address Management
    path('addresses/', views.addresses_view, name='addresses'),
    path('add-address/', views.add_address, name='add_address'),
    path('address/edit/<int:pk>/', views.edit_address, name='edit_address'),
    path('address/delete/<int:pk>/', views.delete_address, name='delete_address'),
    path('address/set-default/<int:pk>/', views.set_default_address, name='set_default_address'),
    
    # Email Subscriptions
    path('subscriptions/', views.subscriptions_view, name='subscriptions'),
    
    # Newsletter (public)
    path('newsletter/subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    
    # OTP and Verification Endpoints
    path('forgot-password/resend-otp/', views.resend_password_otp, name='resend_password_otp'),
    path('resend-2fa-otp/', views.resend_2fa_otp, name='resend_2fa_otp'),
    path('resend-2fa-setup-otp/', views.resend_2fa_setup_otp, name='resend_2fa_setup_otp'),
    path('resend-verification-email/', views.resend_verification_email, name='resend_verification_email'),
    
    # Verification Endpoints
    path('send-verification-email/', views.send_verification_email, name='send_verification_email'),
    path('send-phone-verification/', views.send_phone_verification, name='send_phone_verification'),
    
    # Session Management
    path('logout-all-devices/', views.logout_all_devices, name='logout_all_devices'),
    path('recent-activity/', views.recent_activity_api, name='recent_activity_api'),
    
    # Google OAuth
    path('google/', include('allauth.socialaccount.providers.google.urls')),

    ]