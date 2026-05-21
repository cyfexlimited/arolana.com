from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Q, Count
from .models import Notification, NotificationPreference, WebPushSubscription
from django.template.defaultfilters import timesince
import json


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return {}


def _push_supported_response(request):
    public_key = getattr(settings, 'WEB_PUSH_VAPID_PUBLIC_KEY', '')
    private_key = getattr(settings, 'WEB_PUSH_VAPID_PRIVATE_KEY', '')
    enabled = bool(getattr(settings, 'WEB_PUSH_ENABLED', True) and public_key and private_key)
    reason = ''

    if not request.user.is_authenticated:
        reason = 'Sign in to enable Arolana phone alerts.'
    elif not public_key or not private_key:
        reason = 'Arolana push notifications are not configured yet.'

    return {
        'enabled': enabled,
        'authenticated': request.user.is_authenticated,
        'public_key': public_key if enabled else '',
        'service_worker_url': '/service-worker.js',
        'subscribe_url': '/notifications/api/push/subscribe/',
        'unsubscribe_url': '/notifications/api/push/unsubscribe/',
        'test_url': '/notifications/api/push/test/',
        'reason': reason,
    }

@login_required
def notification_list(request):
    """List all notifications for the current user with filtering and pagination"""
    notifications = request.user.notifications.select_related('user').all()
    
    # Get filter parameter
    filter_type = request.GET.get('filter', 'all')
    notification_type = request.GET.get('type', '')
    
    # Apply filters
    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_type == 'read':
        notifications = notifications.filter(is_read=True)
    
    # Apply type filter
    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        notifications = notifications.filter(
            Q(title__icontains=search_query) | 
            Q(message__icontains=search_query)
        )
    
    # Get counts for stats
    total_count = request.user.notifications.count()
    unread_count = request.user.notifications.filter(is_read=False).count()
    read_count = total_count - unread_count
    
    # Get counts by type for sidebar
    type_counts = request.user.notifications.values('notification_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Pagination
    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'notifications': page_obj,
        'unread_count': unread_count,
        'total_count': total_count,
        'read_count': read_count,
        'filter_type': filter_type,
        'current_type': notification_type,
        'search_query': search_query,
        'type_counts': type_counts,
        'notification_types': Notification.NOTIFICATION_TYPES,
    }
    return render(request, 'notifications/list.html', context)

@login_required
@csrf_exempt
def mark_as_read(request, notification_id):
    """Mark a single notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'message': 'Notification marked as read',
            'unread_count': request.user.notifications.filter(is_read=False).count()
        })
    
    messages.success(request, 'Notification marked as read')
    return redirect('notifications:list')

@login_required
@require_POST
@csrf_exempt
def mark_all_read(request):
    """Mark all notifications as read"""
    count = request.user.notifications.filter(is_read=False).count()
    request.user.notifications.filter(is_read=False).update(
        is_read=True, 
        read_at=timezone.now()
    )
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'count': count, 
            'message': f'Marked {count} notifications as read',
            'unread_count': 0
        })
    
    messages.success(request, f'Marked {count} notifications as read')
    return redirect('notifications:list')

@login_required
@csrf_exempt
def delete_notification(request, notification_id):
    """Delete a single notification"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'message': 'Notification deleted',
            'unread_count': request.user.notifications.filter(is_read=False).count()
        })
    
    messages.success(request, 'Notification deleted')
    return redirect('notifications:list')

@login_required
@require_POST
@csrf_exempt
def delete_all_read(request):
    """Delete all read notifications"""
    count = request.user.notifications.filter(is_read=True).count()
    request.user.notifications.filter(is_read=True).delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'count': count, 
            'message': f'Deleted {count} notifications',
            'unread_count': request.user.notifications.filter(is_read=False).count()
        })
    
    messages.success(request, f'Deleted {count} read notifications')
    return redirect('notifications:list')

@login_required
@require_POST
@csrf_exempt
def delete_all(request):
    """Delete all notifications (both read and unread)"""
    count = request.user.notifications.count()
    request.user.notifications.all().delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True, 
            'count': count, 
            'message': f'Deleted all {count} notifications',
            'unread_count': 0
        })
    
    messages.success(request, f'Deleted all {count} notifications')
    return redirect('notifications:list')

@login_required
def preferences(request):
    """User notification preferences page"""
    settings, created = NotificationPreference.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        settings.email_notifications = request.POST.get('email_notifications') == 'on'
        settings.push_notifications = request.POST.get('push_notifications') == 'on'
        settings.sound_enabled = request.POST.get('sound_enabled') == 'on'
        settings.desktop_notifications = request.POST.get('desktop_notifications') == 'on'
        settings.cart_updates = request.POST.get('cart_updates') == 'on'
        settings.order_updates = request.POST.get('order_updates') == 'on'
        settings.promotions = request.POST.get('promotions') == 'on'
        settings.vendor_alerts = request.POST.get('vendor_alerts') == 'on'
        settings.security_alerts = request.POST.get('security_alerts') == 'on'
        settings.product_updates = request.POST.get('product_updates') == 'on'
        settings.review_alerts = request.POST.get('review_alerts') == 'on'
        settings.message_alerts = request.POST.get('message_alerts') == 'on'
        settings.quiet_hours_enabled = request.POST.get('quiet_hours_enabled') == 'on'
        settings.quiet_hours_start = request.POST.get('quiet_hours_start')
        settings.quiet_hours_end = request.POST.get('quiet_hours_end')
        settings.do_not_disturb = request.POST.get('do_not_disturb') == 'on'
        settings.save()
        
        messages.success(request, 'Notification preferences updated successfully!')
        return redirect('notifications:preferences')
    
    context = {
        'settings': settings,
        'notification_types': Notification.NOTIFICATION_TYPES,
    }
    return render(request, 'notifications/preferences.html', context)

@login_required
@csrf_exempt
def create_test_notification(request):
    """Create a test notification (for development)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body) if request.body else {}
            notification_type = data.get('type', 'info')
            title = data.get('title', 'Test Notification')
            message = data.get('message', 'This is a test notification to verify the system is working correctly.')
            
            Notification.objects.create(
                user=request.user,
                notification_type=notification_type,
                title=title,
                message=message,
                link='/notifications/'
            )
            return JsonResponse({'success': True, 'message': 'Test notification created'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    return render(request, 'notifications/test_notification.html')


@require_GET
def push_config(request):
    """Public push configuration used by the browser opt-in script."""
    data = _push_supported_response(request)
    if request.user.is_authenticated:
        data['active_subscriptions'] = WebPushSubscription.objects.filter(
            user=request.user,
            is_active=True,
        ).count()
    else:
        data['active_subscriptions'] = 0
    return JsonResponse(data)


@login_required
@require_POST
def push_subscribe(request):
    """Store or refresh a browser Push API subscription."""
    data = _json_body(request)
    subscription = data.get('subscription') or data
    endpoint = str(subscription.get('endpoint', '')).strip()
    keys = subscription.get('keys') or {}
    p256dh = str(keys.get('p256dh', '')).strip()
    auth = str(keys.get('auth', '')).strip()

    if not endpoint or not p256dh or not auth:
        return JsonResponse({
            'success': False,
            'message': 'Subscription endpoint and keys are required.',
        }, status=400)

    device_name = str(data.get('device_name') or '').strip()[:140]
    browser_name = str(data.get('browser_name') or '').strip()[:80]

    subscription_obj, created = WebPushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:1200],
            'device_name': device_name,
            'browser_name': browser_name,
            'is_active': True,
            'last_error': '',
        },
    )

    preferences, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if not preferences.push_notifications:
        preferences.push_notifications = True
        preferences.save(update_fields=['push_notifications', 'updated_at'])

    return JsonResponse({
        'success': True,
        'created': created,
        'subscription_id': subscription_obj.id,
        'active_subscriptions': WebPushSubscription.objects.filter(
            user=request.user,
            is_active=True,
        ).count(),
    })


@login_required
@require_POST
def push_unsubscribe(request):
    data = _json_body(request)
    endpoint = str(data.get('endpoint', '')).strip()

    queryset = WebPushSubscription.objects.filter(user=request.user)
    if endpoint:
        queryset = queryset.filter(endpoint=endpoint)

    updated = queryset.update(is_active=False)

    return JsonResponse({
        'success': True,
        'deactivated': updated,
    })


@login_required
@require_POST
def push_test(request):
    notification = Notification.objects.create(
        user=request.user,
        notification_type='info',
        title='Arolana phone alerts are enabled',
        message='You will now receive important Arolana alerts on this device.',
        link='/notifications/',
        priority=2,
    )

    return JsonResponse({
        'success': True,
        'notification_id': notification.id,
        'push_sent': notification.push_sent,
    })

@require_GET
def get_unread_count(request):
    """API endpoint to get unread notification count - FIXED: uses 'user' not 'recipient'"""
    if not request.user.is_authenticated:
        return JsonResponse({'unread_count': 0, 'authenticated': False})
    
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({
        'unread_count': count, 
        'authenticated': True,
        'has_notifications': count > 0
    })

@login_required
@require_GET
def get_notifications_api(request):
    """API endpoint to get notifications as JSON for AJAX"""
    limit = int(request.GET.get('limit', 10))
    offset = int(request.GET.get('offset', 0))
    
    notifications = request.user.notifications.all()[offset:offset+limit]
    
    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message[:100] + ('...' if len(n.message) > 100 else ''),
                'type': n.notification_type,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat(),
                'time_ago': timesince(n.created_at),
                'link': n.link or '#',
                'icon_class': n.get_icon(),
                'icon_color': n.get_color(),
            }
            for n in notifications
        ],
        'unread_count': request.user.notifications.filter(is_read=False).count(),
        'total_count': request.user.notifications.count(),
        'has_more': request.user.notifications.count() > offset + limit
    }
    return JsonResponse(data)

@login_required
@require_GET
def get_latest_notifications(request):
    """Get latest notifications for the bell dropdown"""
    limit = int(request.GET.get('limit', 5))
    notifications = request.user.notifications.all()[:limit]
    
    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message[:80] + ('...' if len(n.message) > 80 else ''),
                'type': n.notification_type,
                'is_read': n.is_read,
                'time_ago': timesince(n.created_at),
                'link': n.link or '#',
                'icon_class': n.get_icon(),
                'icon_color': n.get_color(),
            }
            for n in notifications
        ],
        'unread_count': request.user.notifications.filter(is_read=False).count(),
        'total_count': request.user.notifications.count(),
    }
    return JsonResponse(data)

@login_required
@require_POST
@csrf_exempt
def bulk_action(request):
    """Perform bulk actions on notifications"""
    try:
        data = json.loads(request.body)
        action = data.get('action')
        notification_ids = data.get('ids', [])
        
        if not notification_ids:
            return JsonResponse({'success': False, 'message': 'No notifications selected'})
        
        notifications = request.user.notifications.filter(id__in=notification_ids)
        
        if action == 'mark_read':
            count = notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
            message = f'Marked {count} notifications as read'
        elif action == 'delete':
            count = notifications.count()
            notifications.delete()
            message = f'Deleted {count} notifications'
        else:
            return JsonResponse({'success': False, 'message': 'Invalid action'})
        
        return JsonResponse({
            'success': True,
            'message': message,
            'unread_count': request.user.notifications.filter(is_read=False).count()
        })
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})

@login_required
def notification_detail(request, notification_id):
    """View a single notification detail"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    
    # Mark as read when viewed
    if not notification.is_read:
        notification.mark_as_read()
    
    context = {
        'notification': notification,
        'related_notifications': request.user.notifications.filter(
            notification_type=notification.notification_type
        ).exclude(id=notification.id)[:5]
    }
    return render(request, 'notifications/detail.html', context)

@login_required
def notification_settings(request):
    """Notification settings page (alias for preferences)"""
    return preferences(request)

# Export all views
__all__ = [
    'notification_list', 'mark_as_read', 'mark_all_read', 'delete_notification',
    'delete_all_read', 'delete_all', 'preferences', 'create_test_notification',
    'get_unread_count', 'get_notifications_api', 'get_latest_notifications',
    'bulk_action', 'notification_detail', 'notification_settings',
    'push_config', 'push_subscribe', 'push_unsubscribe', 'push_test'
]
