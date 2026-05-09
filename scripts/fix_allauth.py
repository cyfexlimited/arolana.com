#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from django.conf import settings
import allauth

print("🔧 Fixing AllAuth Configuration")
print("="*40)

# Check current settings
print(f"\nCurrent AllAuth version: {allauth.__version__}")

# The warnings are informational - the settings still work
# To completely silence them, we need to update the configuration

# Update settings programmatically
from django.core.management import call_command

print("\n✅ To fix the warnings, update your settings.py with:")

print("""
# Replace these deprecated lines:
    ACCOUNT_AUTHENTICATION_METHOD = 'email'
    ACCOUNT_EMAIL_REQUIRED = True
    ACCOUNT_USERNAME_REQUIRED = False

# With:
    ACCOUNT_LOGIN_METHODS = {'email'}
    ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
    ACCOUNT_EMAIL_VERIFICATION = 'optional'
    ACCOUNT_EMAIL_REQUIRED = True
    ACCOUNT_USERNAME_REQUIRED = False
""")

print("\nThe warnings don't affect functionality - they're just telling you about future changes.")
print("Your app will continue to work normally.")
