from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings

class Command(BaseCommand):
    help = 'Test Gmail SMTP configuration'
    
    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Recipient email address')
    
    def handle(self, *args, **options):
        email = options['email']
        
        self.stdout.write("=" * 60)
        self.stdout.write("📧 Testing Gmail SMTP Configuration")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Recipient: {email}")
        self.stdout.write(f"Host: {settings.EMAIL_HOST}")
        self.stdout.write(f"Port: {settings.EMAIL_PORT}")
        self.stdout.write(f"Username: {settings.EMAIL_HOST_USER}")
        self.stdout.write("-" * 60)
        
        try:
            send_mail(
                subject='[Test] Arolana Gmail Configuration',
                message=f"""
Hello,

This is a test email from Arolana.com.

Your Gmail SMTP configuration is working!

Configuration:
- SMTP Server: {settings.EMAIL_HOST}
- Port: {settings.EMAIL_PORT}
- TLS: {settings.EMAIL_USE_TLS}
- From: {settings.DEFAULT_FROM_EMAIL}

Best regards,
Arolana Team
                """,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS("\n✅ Test email sent successfully!"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Failed: {e}"))
