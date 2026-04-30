from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Notification, UserNotificationSettings

@login_required
def notification_list(request):
    """List all notifications for the current user"""
    notifications = request.user.notifications.all()
    unread_count = notifications.filter(is_read=False).count()
    
    context = {
        'notifications': notifications,
        'unread_count': unread_count,
    }
    return render(request, 'notifications/list.html', context)

@login_required
def mark_as_read(request, notification_id):
    """Mark a single notification as read"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.mark_as_read()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect('notifications:list')

@login_required
@require_POST
def mark_all_read(request):
    """Mark all notifications as read"""
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'count': 0})
    
    return redirect('notifications:list')

@login_required
def delete_notification(request, notification_id):
    """Delete a notification"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
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
        settings.save()
        
        messages.success(request, 'Notification settings updated!')
        return redirect('notifications:settings')
    
    context = {'settings': settings}
    return render(request, 'notifications/settings.html', context)

def get_unread_count(request):
    """API endpoint to get unread notification count"""
    if not request.user.is_authenticated:
        return JsonResponse({'unread_count': 0})
    
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'unread_count': count})
