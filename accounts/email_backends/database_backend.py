from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail import EmailMultiAlternatives
from accounts.models import UserOTP

class DatabaseEmailBackend(BaseEmailBackend):
    """Email backend that saves OTPs to database for development testing"""
    
    def send_messages(self, email_messages):
        for message in email_messages:
            # Extract OTP from email body
            body = message.body
            import re
            otp_match = re.search(r'\b\d{6}\b', body)
            otp_code = otp_match.group(0) if otp_match else None
            
            if otp_code:
                print(f"📧 Email would be sent to: {message.to}")
                print(f"🔑 OTP Code: {otp_code}")
                print(f"📝 Subject: {message.subject}")
                print("-" * 50)
            
            # In development, we can also save to a file
            with open('email_log.txt', 'a') as f:
                f.write(f"To: {message.to}\n")
                f.write(f"Subject: {message.subject}\n")
                f.write(f"Body: {body}\n")
                f.write("-" * 50 + "\n")
        
        return len(email_messages)
