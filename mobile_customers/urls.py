from django.urls import path

from . import views

app_name = "mobile_customers"

urlpatterns = [
    path("api/mobile/auth/login/", views.mobile_customer_account_login_api, name="mobile_auth_login_api"),
    path("api/mobile/auth/register/", views.mobile_customer_account_register_api, name="mobile_auth_register_api"),
    path("api/mobile/auth/verify-otp/", views.mobile_customer_account_verify_otp_api, name="mobile_auth_verify_otp_api"),
    path("api/mobile/auth/resend-otp/", views.mobile_customer_account_resend_otp_api, name="mobile_auth_resend_otp_api"),
    path("api/mobile/auth/me/", views.mobile_customer_profile_api, name="mobile_auth_me_api"),
    path("api/mobile/auth/logout/", views.mobile_customer_account_logout_api, name="mobile_auth_logout_api"),
    path("api/mobile/customer/account-login/", views.mobile_customer_account_login_api, name="mobile_customer_account_login_api"),
    path("api/mobile/customer/account-register/", views.mobile_customer_account_register_api, name="mobile_customer_account_register_api"),
    path("api/mobile/customer/account-login/verify-otp/", views.mobile_customer_account_verify_otp_api, name="mobile_customer_account_verify_otp_api"),
    path("api/mobile/customer/account-login/resend-otp/", views.mobile_customer_account_resend_otp_api, name="mobile_customer_account_resend_otp_api"),
    path("api/mobile/customer/login/", views.mobile_customer_login_api, name="mobile_customer_login_api"),
    path("api/mobile/customer/register/", views.mobile_customer_login_api, name="mobile_customer_register_api"),
    path("api/mobile/customer/profile/", views.mobile_customer_profile_api, name="mobile_customer_profile_api"),
    path("api/mobile/settings/", views.mobile_customer_settings_api, name="mobile_customer_settings_api"),

    path("api/mobile/customer/update/", views.mobile_customer_update_api, name="mobile_customer_update_api"),
    path("api/mobile/customer/change-pin/", views.mobile_customer_change_pin_api, name="mobile_customer_change_pin_api"),
    path("api/mobile/customer/delete/", views.mobile_customer_delete_api, name="mobile_customer_delete_api"),

    path("api/mobile/wishlist/", views.mobile_wishlist_list_api, name="mobile_wishlist_list_api"),
    path("api/mobile/wishlist/sync/", views.mobile_wishlist_sync_api, name="mobile_wishlist_sync_api"),
    path("api/mobile/wishlist/toggle/", views.mobile_wishlist_toggle_api, name="mobile_wishlist_toggle_api"),
    path("api/mobile/customer/profile-photo/", views.mobile_customer_profile_photo_api, name="mobile_customer_profile_photo_api"),
]
