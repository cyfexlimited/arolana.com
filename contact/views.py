from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings

def contact_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        
        # Send email
        try:
            send_mail(
                f'Contact Form: {subject}',
                f'From: {name} ({email})\n\n{message}',
                email,
                [settings.DEFAULT_FROM_EMAIL],
                fail_silently=False,
            )
            messages.success(request, 'Your message has been sent. We\'ll get back to you soon!')
        except:
            messages.error(request, 'There was an error sending your message. Please try again.')
        
        return redirect('contact')
    
    return render(request, 'support/contact.html')
