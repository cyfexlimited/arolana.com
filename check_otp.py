#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from accounts.models import UserOTP
from django.utils import timezone

# Get recent OTPs
otps = UserOTP.objects.filter(created_at__gte=timezone.now() - timezone.timedelta(hours=1)).order_by('-created_at')[:10]

print("\n" + "="*60)
print("🔑 Recent OTP Codes")
print("="*60)

if otps:
    for otp in otps:
        print(f"\nUser: {otp.user.email}")
        print(f"Purpose: {otp.purpose}")
        print(f"OTP: {otp.otp}")
        print(f"Created: {otp.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Expires: {otp.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Used: {'Yes' if otp.is_used else 'No'}")
        print("-" * 40)
    
    print(f"\n📊 Total OTPs in last hour: {otps.count()}")
else:
    print("\nNo OTPs found in the last hour.")
    print("\nTo generate an OTP, try:")
    print("1. Register a new account")
    print("2. Request password reset")
    print("3. Enable 2FA")
