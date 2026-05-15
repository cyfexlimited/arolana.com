from django.urls import path, include
from django.views.generic import RedirectView
from . import views
from allauth.account import views as allauth_views

app_name = 'accounts'

urlpatterns = [
    # Custom views (these will override allauth defaults when accessed directly)
    path('signup/', RedirectView.as_view(url='/accounts/register/', permanent=False)),
path('password/reset/', RedirectView.as_view(url='/accounts/forgot-password/', permanent=False)),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('', include('allauth.account.urls')),
    # Profile
    path('profile/', views.profile_view, name='profile'),
    path('edit-profile/', views.edit_profile, name='edit_profile'),
    
    # Password
    path('change-password/', views.change_password, name='change_password'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password-verify/', views.reset_password_verify, name='reset_password_verify'),
    
    # 2FA & Security
    path('security/', views.security_settings, name='security_settings'),
    path('enable-2fa/', views.enable_2fa, name='enable_2fa'),
    path('disable-2fa/', views.disable_2fa, name='disable_2fa'),
    path('verify-2fa/', views.verify_2fa, name='verify_2fa'),
    path('verify-email/', views.verify_email, name='verify_email'),
    path('verify-phone/', views.verify_phone, name='verify_phone'),
    path('resend-verification/', views.resend_verification_email, name='resend_verification'),
    path('logout-all-devices/', views.logout_all_devices, name='logout_all_devices'),
    path('session-activity/', views.session_activity, name='session_activity'),
    path('terminate-session/<str:session_key>/', views.terminate_session, name='terminate_session'),
    
    # Addresses
    path('addresses/', views.addresses_view, name='addresses'),
    path('add-address/', views.add_address, name='add_address'),
    path('edit-address/<int:pk>/', views.edit_address, name='edit_address'),
    path('delete-address/<int:pk>/', views.delete_address, name='delete_address'),
    path('set-default-address/<int:pk>/', views.set_default_address, name='set_default_address'),
    
    # Wishlist & History
    path('wishlist/', views.wishlist_view, name='wishlist'),
    path('clear-wishlist/', views.clear_wishlist, name='clear_wishlist'),
    path('browsing-history/', views.browsing_history, name='browsing_history'),
    path('clear-history/', views.clear_browsing_history, name='clear_history'),
    path('remove-history-item/<int:item_id>/', views.remove_history_item, name='remove_history_item'),
    
    # Subscriptions & Notifications
    path('subscriptions/', views.subscriptions_view, name='subscriptions'),
    path('notification-preferences/', views.notification_preferences, name='notification_preferences'),
    
    # Newsletter
    path('newsletter-subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    
    # Account management
    path('delete-account/', views.delete_account, name='delete_account'),
    
    # Popup/Modal URLs (for AJAX)
    path('resend-password-otp/', views.resend_password_otp, name='resend_password_otp'),
    path('resend-2fa-otp/', views.resend_2fa_otp, name='resend_2fa_otp'),
    path('resend-2fa-setup-otp/', views.resend_2fa_setup_otp, name='resend_2fa_setup_otp'),
    path('send-phone-verification/', views.send_phone_verification, name='send_phone_verification'),
    path('send-verification-email/', views.send_verification_email, name='send_verification_email'),
    
    # APIs
    path('wishlist-count/', views.wishlist_count, name='wishlist_count'),
    path('recent-activity-api/', views.recent_activity_api, name='recent_activity_api'),
    path('social-apps-status/', views.social_apps_status, name='social_apps_status'),
    path('check-username/', views.check_username, name='check_username'),
    path('check-email/', views.check_email, name='check_email'),
]
