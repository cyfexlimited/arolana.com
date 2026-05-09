from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags

class Command(BaseCommand):
    help = 'Test email configuration'
    
    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Recipient email address')
    
    def handle(self, *args, **options):
        email = options['email']
        
        self.stdout.write("=" * 60)
        self.stdout.write("📧 Testing Email Configuration")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Recipient: {email}")
        self.stdout.write(f"Backend: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"From: {settings.DEFAULT_FROM_EMAIL}")
        
        # Test HTML email
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: #3b82f6; color: white; padding: 20px; text-align: center; }
                .content { padding: 20px; }
                .code { font-size: 32px; font-weight: bold; text-align: center; padding: 20px; background: #f0f0f0; }
                .footer { text-align: center; padding: 20px; color: #666; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Arolana.com</h1>
                </div>
                <div class="content">
                    <h2>Test Email</h2>
                    <p>If you're seeing this, your email configuration is working!</p>
                    <div class="code">
                        <strong>Test Code: 123456</strong>
                    </div>
                    <p>This is a test email from Arolana.com</p>
                </div>
                <div class="footer">
                    <p>&copy; 2024 Arolana.com</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = strip_tags(html_content)
        
        try:
            send_mail(
                subject='[Test] Arolana Email Configuration',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_content,
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS("\n✅ Email sent successfully!"))
            self.stdout.write(f"\n📧 Check {email} inbox (or spam folder)")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n❌ Failed to send email: {e}"))
            
            self.stdout.write("\n🔧 Troubleshooting:")
            self.stdout.write("1. For Gmail: Enable 2FA and generate App Password")
            self.stdout.write("2. Update .env with correct credentials")
            self.stdout.write("3. Run: python manage.py test_gmail " + email)
