from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.utils import timezone
from django.db.models import Q
from .models import Notification, UserNotificationSettings

@login_required
def notification_list(request):
    """List all notifications for the current user with filtering and pagination"""
    notifications = request.user.notifications.all()
    
    # Get filter parameter
    filter_type = request.GET.get('filter', 'all')
    
    # Apply filters
    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_type == 'read':
        notifications = notifications.filter(is_read=True)
    elif filter_type == 'orders':
        notifications = notifications.filter(notification_type='order')
    elif filter_type == 'messages':
        notifications = notifications.filter(notification_type='message')
    elif filter_type == 'system':
        notifications = notifications.filter(notification_type='system')
    elif filter_type == 'login':
        notifications = notifications.filter(notification_type='login')
    elif filter_type == 'vendor':
        notifications = notifications.filter(notification_type='vendor')
    
    # Get counts for stats
    total_count = request.user.notifications.count()
    unread_count = request.user.notifications.filter(is_read=False).count()
    read_count = total_count - unread_count
    
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
    }
    return render(request, 'notifications/list.html', context)

@login_required
@csrf_exempt
def mark_as_read(request, notification_id):
    """Mark a single notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Notification marked as read'})
    
    messages.success(request, 'Notification marked as read')
    return redirect('notifications:list')

@login_required
@require_POST
@csrf_exempt
def mark_all_read(request):
    """Mark all notifications as read"""
    count = request.user.notifications.filter(is_read=False).count()
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'count': count, 'message': f'Marked {count} notifications as read'})
    
    messages.success(request, f'Marked {count} notifications as read')
    return redirect('notifications:list')

@login_required
@csrf_exempt
def delete_notification(request, notification_id):
    """Delete a single notification"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Notification deleted'})
    
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
        return JsonResponse({'success': True, 'count': count, 'message': f'Deleted {count} notifications'})
    
    messages.success(request, f'Deleted {count} read notifications')
    return redirect('notifications:list')

@login_required
def notification_settings(request):
    """User notification settings"""
    settings, created = UserNotificationSettings.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        settings.email_notifications = request.POST.get('email_notifications') == 'on'
        settings.push_notifications = request.POST.get('push_notifications') == 'on'
        settings.login_alerts = request.POST.get('login_alerts') == 'on'
        settings.order_updates = request.POST.get('order_updates') == 'on'
        settings.marketing_emails = request.POST.get('marketing_emails') == 'on'
        settings.vendor_alerts = request.POST.get('vendor_alerts') == 'on'
        settings.save()
        
        messages.success(request, 'Notification settings updated successfully!')
        return redirect('notifications:settings')
    
    context = {'settings': settings}
    return render(request, 'notifications/settings.html', context)

@login_required
@csrf_exempt
def create_test_notification(request):
    """Create a test notification (for development)"""
    if request.method == 'POST':
        Notification.objects.create(
            user=request.user,
            notification_type='system',
            title='Test Notification',
            message='This is a test notification to verify the system is working correctly.',
            link='/notifications/'
        )
        return JsonResponse({'success': True, 'message': 'Test notification created'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

def get_unread_count(request):
    """API endpoint to get unread notification count"""
    if not request.user.is_authenticated:
        return JsonResponse({'unread_count': 0})
    
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'unread_count': count})

@login_required
def get_notifications_api(request):
    """API endpoint to get notifications as JSON"""
    limit = int(request.GET.get('limit', 10))
    notifications = request.user.notifications.all()[:limit]
    
    data = {
        'notifications': [
            {
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'type': n.notification_type,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat(),
                'time_ago': n.created_at|timesince,
                'link': n.link
            }
            for n in notifications
        ],
        'unread_count': request.user.notifications.filter(is_read=False).count(),
        'total_count': request.user.notifications.count()
    }
    return JsonResponse(data)
