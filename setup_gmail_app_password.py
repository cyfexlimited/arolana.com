#!/usr/bin/env python3
print("""
🔐 GMAIL APP PASSWORD SETUP
============================

Since 2-Step Verification is enabled on cyfexlimited8@gmail.com,
you need to generate an App Password for Arolana.

STEPS:
-------
1. Go to: https://myaccount.google.com/apppasswords

2. Select:
   - App: "Mail"
   - Device: "Other (Custom name)"
   - Name: "Arolana.com"

3. Click "Generate"

4. Copy the 16-character password (it will look like: xxxx xxxx xxxx xxxx)

5. Run this command with YOUR actual password:
   export EMAIL_HOST_PASSWORD="your-16-char-password"

OR add to your .env file:
   EMAIL_HOST_PASSWORD=your-16-char-password

IMPORTANT: 
- The App Password will only show ONCE
- Save it securely
- Spaces in the password don't matter
- Regular Gmail password won't work
""")

# Test if credentials work
try:
    import django
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
    django.setup()
    
    from django.core.mail import send_mail
    from django.conf import settings
    
    print("\n🧪 Testing current configuration...")
    print(f"Email Backend: {settings.EMAIL_BACKEND}")
    
    if 'smtp' in settings.EMAIL_BACKEND:
        print(f"Host: {settings.EMAIL_HOST}")
        print(f"User: {settings.EMAIL_HOST_USER}")
        if settings.EMAIL_HOST_PASSWORD:
            print(f"Password: {'*' * len(settings.EMAIL_HOST_PASSWORD)}")
        else:
            print("⚠️ No password set. Please configure EMAIL_HOST_PASSWORD")
except Exception as e:
    print(f"Error: {e}")
