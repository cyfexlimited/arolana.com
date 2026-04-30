from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from .models import NewsletterSubscriber, NewsletterCampaign, NewsletterTracking
import json
import re

def validate_email(email):
    """Simple email validation"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def subscribe(request):
    """Handle newsletter subscription form submission"""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        name = request.POST.get('name', '').strip()
        source = request.POST.get('source', 'homepage')
        next_url = request.POST.get('next', '/')
        
        if not email:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Email is required'}, status=400)
            messages.error(request, 'Please enter a valid email address.')
            return redirect(next_url)
        
        if not validate_email(email):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Invalid email format'}, status=400)
            messages.error(request, 'Please enter a valid email address.')
            return redirect(next_url)
        
        # Check if already subscribed
        subscriber, created = NewsletterSubscriber.objects.get_or_create(
            email=email,
            defaults={
                'name': name,
                'source': source,
                'is_active': True
            }
        )
        
        if not created:
            if subscriber.is_active:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False, 
                        'error': 'This email is already subscribed.',
                        'already_subscribed': True
                    }, status=400)
                messages.info(request, f'{email} is already subscribed.')
            else:
                subscriber.is_active = True
                subscriber.unsubscribed_at = None
                subscriber.save()
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True, 
                        'message': 'Welcome back! You have been re-subscribed.'
                    })
                messages.success(request, f'Welcome back! {email} has been re-subscribed.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True, 
                    'message': f'Successfully subscribed with {email}! Thank you.',
                    'email': email
                })
            messages.success(request, f'Successfully subscribed with {email}! Thank you.')
        
        return redirect(next_url)
    
    return redirect('/')

@csrf_exempt
@require_http_methods(["POST"])
def api_subscribe(request):
    """AJAX endpoint for newsletter subscription"""
    try:
        # Try to parse JSON, if fails try form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            email = data.get('email', '').strip()
            name = data.get('name', '').strip()
            source = data.get('source', 'api')
        else:
            email = request.POST.get('email', '').strip()
            name = request.POST.get('name', '').strip()
            source = request.POST.get('source', 'api')
        
        if not email:
            return JsonResponse({'success': False, 'error': 'Email is required'}, status=400)
        
        if not validate_email(email):
            return JsonResponse({'success': False, 'error': 'Invalid email format'}, status=400)
        
        # Create or get subscriber
        subscriber, created = NewsletterSubscriber.objects.get_or_create(
            email=email,
            defaults={
                'name': name,
                'source': source,
                'is_active': True
            }
        )
        
        if not created:
            if subscriber.is_active:
                return JsonResponse({
                    'success': False, 
                    'error': 'This email is already subscribed.',
                    'already_subscribed': True
                }, status=400)
            else:
                subscriber.is_active = True
                subscriber.unsubscribed_at = None
                subscriber.save()
                return JsonResponse({
                    'success': True, 
                    'message': 'Welcome back! You have been re-subscribed.',
                    'already_subscribed': True
                })
        
        return JsonResponse({
            'success': True, 
            'message': 'Successfully subscribed to our newsletter!',
            'email': email
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

def unsubscribe(request, email):
    """Unsubscribe from newsletter"""
    try:
        subscriber = NewsletterSubscriber.objects.get(email=email, is_active=True)
        subscriber.is_active = False
        from django.utils import timezone
        subscriber.unsubscribed_at = timezone.now()
        subscriber.save()
        messages.success(request, f'Successfully unsubscribed {email} from our newsletter.')
    except NewsletterSubscriber.DoesNotExist:
        messages.info(request, f'{email} was not found in our subscriber list.')
    
    return redirect('/')

def unsubscribe_token(request, token):
    """Unsubscribe using token"""
    return redirect('/')

def track_open(request, tracking_id):
    """Track email opens"""
    from django.http import HttpResponse
    try:
        tracking = NewsletterTracking.objects.get(id=tracking_id)
        if not tracking.opened_at:
            tracking.opened_at = timezone.now()
            tracking.save()
    except:
        pass
    pixel = b'GIF89a\x01\x00\x01\x00\x00\xff\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
    return HttpResponse(pixel, content_type='image/gif')

def track_click(request, tracking_id):
    """Track email clicks"""
    try:
        tracking = NewsletterTracking.objects.get(id=tracking_id)
        if not tracking.clicked_at:
            tracking.clicked_at = timezone.now()
            tracking.save()
    except:
        pass
    return redirect('/')

# Admin views
@staff_member_required
def campaign_list(request):
    campaigns = NewsletterCampaign.objects.all().order_by('-created_at')
    return render(request, 'newsletter/campaign_list.html', {'campaigns': campaigns})

@staff_member_required
def campaign_create(request):
    if request.method == 'POST':
        campaign = NewsletterCampaign.objects.create(
            name=request.POST.get('name'),
            subject=request.POST.get('subject'),
            content=request.POST.get('content'),
            html_content=request.POST.get('html_content', ''),
            status='draft'
        )
        messages.success(request, f'Campaign "{campaign.name}" created!')
        return redirect('newsletter:campaign_detail', campaign_id=campaign.id)
    return render(request, 'newsletter/campaign_form.html')

@staff_member_required
def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(NewsletterCampaign, id=campaign_id)
    return render(request, 'newsletter/campaign_detail.html', {'campaign': campaign})

@staff_member_required
def campaign_send(request, campaign_id):
    campaign = get_object_or_404(NewsletterCampaign, id=campaign_id)
    if request.method == 'POST':
        campaign.status = 'sent'
        campaign.sent_at = timezone.now()
        campaign.save()
        messages.success(request, f'Campaign "{campaign.name}" sent!')
        return redirect('newsletter:campaign_detail', campaign_id=campaign.id)
    return render(request, 'newsletter/campaign_send.html', {'campaign': campaign})

@staff_member_required
def subscriber_list(request):
    subscribers = NewsletterSubscriber.objects.all().order_by('-subscribed_at')
    return render(request, 'newsletter/subscriber_list.html', {'subscribers': subscribers})

@staff_member_required
def subscriber_detail(request, subscriber_id):
    subscriber = get_object_or_404(NewsletterSubscriber, id=subscriber_id)
    return render(request, 'newsletter/subscriber_detail.html', {'subscriber': subscriber})

@staff_member_required
def subscriber_export(request):
    import csv
    from django.http import HttpResponse
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="subscribers.csv"'
    writer = csv.writer(response)
    writer.writerow(['Email', 'Name', 'Source', 'Subscribed At', 'Status'])
    for sub in NewsletterSubscriber.objects.all():
        writer.writerow([sub.email, sub.name, sub.source, sub.subscribed_at, 'Active' if sub.is_active else 'Inactive'])
    return response
