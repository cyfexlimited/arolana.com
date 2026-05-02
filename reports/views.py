from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.db.models import Count, Q
from django.utils import timezone
from datetime import datetime, timedelta
from accounts.models import UserActivityLog, LoginAttempt, User
from .models import LoginReport, LoginAlert
import csv
import json

@staff_member_required
def login_report_dashboard(request):
    """Dashboard for login reports and analytics"""
    context = {
        'title': 'Login Reports Dashboard',
    }
    return render(request, 'reports/dashboard.html', context)

@staff_member_required
def generate_login_report(request):
    """Generate login report for a specific period"""
    if request.method == 'POST':
        report_type = request.POST.get('report_type')
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        
        # Parse dates
        if report_type == 'daily':
            end_date = timezone.now()
            start_date = end_date - timedelta(days=1)
        elif report_type == 'weekly':
            end_date = timezone.now()
            start_date = end_date - timedelta(days=7)
        elif report_type == 'monthly':
            end_date = timezone.now()
            start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        
        # Get login logs
        logs = UserActivityLog.objects.filter(
            timestamp__range=[start_date, end_date]
        )
        
        successful_logins = logs.filter(action='login').count()
        failed_logins = logs.filter(action='failed_login').count()
        total_logins = successful_logins + failed_logins
        
        unique_users = logs.filter(action='login').values('user').distinct().count()
        unique_ips = logs.values('ip_address').distinct().count()
        
        # Get hourly breakdown
        hourly_data = []
        for hour in range(24):
            hour_start = start_date.replace(hour=hour, minute=0, second=0)
            hour_end = hour_start + timedelta(hours=1)
            hour_logs = logs.filter(timestamp__range=[hour_start, hour_end])
            hourly_data.append({
                'hour': hour,
                'successful': hour_logs.filter(action='login').count(),
                'failed': hour_logs.filter(action='failed_login').count(),
            })
        
        # Find suspicious IPs
        suspicious_ips = logs.filter(action='failed_login').values('ip_address').annotate(
            count=Count('id')
        ).filter(count__gte=5).order_by('-count')
        
        report = LoginReport.objects.create(
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            total_logins=total_logins,
            successful_logins=successful_logins,
            failed_logins=failed_logins,
            unique_users=unique_users,
            unique_ips=unique_ips,
            report_data={
                'hourly_breakdown': hourly_data,
                'suspicious_ips': list(suspicious_ips),
            }
        )
        
        return JsonResponse({
            'success': True,
            'report_id': report.id,
            'stats': {
                'total_logins': total_logins,
                'successful': successful_logins,
                'failed': failed_logins,
                'success_rate': round((successful_logins / total_logins * 100) if total_logins > 0 else 0, 2),
                'unique_users': unique_users,
                'unique_ips': unique_ips,
            }
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@staff_member_required
def view_report(request, report_id):
    """View a specific report"""
    report = get_object_or_404(LoginReport, id=report_id)
    return render(request, 'reports/view_report.html', {'report': report})

@staff_member_required
def export_report_csv(request, report_id):
    """Export report as CSV"""
    report = get_object_or_404(LoginReport, id=report_id)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="login_report_{report.id}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Login Report Summary'])
    writer.writerow(['Period:', f'{report.start_date} to {report.end_date}'])
    writer.writerow(['Total Logins:', report.total_logins])
    writer.writerow(['Successful Logins:', report.successful_logins])
    writer.writerow(['Failed Logins:', report.failed_logins])
    writer.writerow(['Unique Users:', report.unique_users])
    writer.writerow(['Unique IPs:', report.unique_ips])
    writer.writerow([])
    writer.writerow(['Hourly Breakdown'])
    writer.writerow(['Hour', 'Successful', 'Failed'])
    
    hourly_data = report.report_data.get('hourly_breakdown', [])
    for data in hourly_data:
        writer.writerow([data['hour'], data['successful'], data['failed']])
    
    return response

@staff_member_required
def login_attempts_list(request):
    """List all login attempts with filters"""
    attempts = LoginAttempt.objects.all().order_by('-last_attempt')
    
    # Apply filters
    email = request.GET.get('email')
    if email:
        attempts = attempts.filter(email__icontains=email)
    
    ip = request.GET.get('ip')
    if ip:
        attempts = attempts.filter(ip_address=ip)
    
    status = request.GET.get('status')
    if status == 'locked':
        attempts = attempts.filter(is_locked=True)
    
    context = {
        'attempts': attempts,
        'total_attempts': attempts.count(),
        'locked_accounts': attempts.filter(is_locked=True).count(),
    }
    return render(request, 'reports/login_attempts.html', context)

@staff_member_required
def unlock_account(request, attempt_id):
    """Unlock a locked account"""
    attempt = get_object_or_404(LoginAttempt, id=attempt_id)
    attempt.is_locked = False
    attempt.locked_until = None
    attempt.save()
    
    return JsonResponse({'success': True, 'message': 'Account unlocked successfully'})

@staff_member_required
def user_activity_report(request, user_id=None):
    """Generate activity report for specific user"""
    if user_id:
        user = get_object_or_404(User, id=user_id)
        activities = UserActivityLog.objects.filter(user=user).order_by('-timestamp')[:100]
    else:
        activities = UserActivityLog.objects.all().order_by('-timestamp')[:100]
    
    context = {
        'activities': activities,
        'total_activities': activities.count(),
    }
    return render(request, 'reports/user_activity.html', context)

@staff_member_required
def realtime_monitoring(request):
    """Real-time login monitoring dashboard"""
    # Get recent activities (last 30 minutes)
    time_threshold = timezone.now() - timedelta(minutes=30)
    recent_activities = UserActivityLog.objects.filter(timestamp__gte=time_threshold).order_by('-timestamp')[:50]
    
    # Check for suspicious patterns
    suspicious_ips = UserActivityLog.objects.filter(
        timestamp__gte=time_threshold,
        action='failed_login'
    ).values('ip_address').annotate(
        count=Count('id')
    ).filter(count__gte=3)
    
    # Create alerts for suspicious IPs
    for ip_data in suspicious_ips:
        LoginAlert.objects.get_or_create(
            ip_address=ip_data['ip_address'],
            alert_type='multiple_failures',
            defaults={
                'severity': 'medium',
                'attempt_count': ip_data['count'],
                'is_resolved': False
            }
        )
    
    alerts = LoginAlert.objects.filter(is_resolved=False)[:20]
    
    context = {
        'recent_activities': recent_activities,
        'alerts': alerts,
        'suspicious_ips': list(suspicious_ips),
    }
    return render(request, 'reports/realtime_monitoring.html', context)

@staff_member_required
def resolve_alert(request, alert_id):
    """Resolve an alert"""
    alert = get_object_or_404(LoginAlert, id=alert_id)
    alert.is_resolved = True
    alert.resolved_at = timezone.now()
    alert.resolved_by = request.user
    alert.save()
    
    return JsonResponse({'success': True, 'message': 'Alert resolved'})

@staff_member_required
def block_ip(request, ip_address):
    """Block a suspicious IP address"""
    LoginAlert.objects.create(
        alert_type='suspicious_ip',
        severity='high',
        ip_address=ip_address,
        notes=f'Blocked by {request.user.email}',
        is_resolved=False
    )
    
    return JsonResponse({'success': True, 'message': f'IP {ip_address} has been blocked'})
