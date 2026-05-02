#!/usr/bin/env python3
print("""
🔐 GMAIL APP PASSWORD SETUP
============================

1. Go to your Google Account:
   https://myaccount.google.com/

2. Click on "Security" in the left sidebar

3. Enable "2-Step Verification" if not already enabled

4. After enabling 2FA, click on "App passwords"

5. Select:
   - App: "Mail"
   - Device: "Other (Custom name)"
   - Name: "Arolana.com"

6. Click "Generate"

7. Copy the 16-character password (spaces don't matter)

8. Update your .env file:
   EMAIL_HOST_PASSWORD=your-16-char-password

NOTE: The app password will only show once, so save it securely!
""")

# Test if credentials work
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')

try:
    import django
    django.setup()
    
    from django.core.mail import send_mail
    from django.conf import settings
    
    print("\n📧 Testing Gmail SMTP connection...")
    print(f"Username: {settings.EMAIL_HOST_USER}")
    print(f"Host: {settings.EMAIL_HOST}")
    print(f"Port: {settings.EMAIL_PORT}")
    
    try:
        send_mail(
            subject='[Test] Arolana Gmail Configuration',
            message='If you received this email, your Gmail SMTP is working!',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=['test@example.com'],
            fail_silently=False,
        )
        print("\n✅ Gmail SMTP is working! Email sent successfully.")
    except Exception as e:
        print(f"\n❌ Gmail SMTP failed: {e}")
        print("\nPossible issues:")
        print("1. App password is incorrect")
        print("2. 2-Step Verification not enabled")
        print("3. Less secure app access is disabled")
        print("4. Email address is not verified")
        
except Exception as e:
    print(f"Error: {e}")
