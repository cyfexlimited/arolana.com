from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, HttpResponse
from django.db.models import Count, Q
from django.db.models.functions import ExtractHour
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
from accounts.models import UserActivityLog, LoginAttempt, User
from .models import LoginReport, LoginAlert
import csv


SUCCESS_ACTIONS = ('login', 'login_2fa')
FAILED_ACTIONS = ('failed_login',)
REPORT_PERIODS = {
    'daily': timedelta(days=1),
    'weekly': timedelta(days=7),
    'monthly': timedelta(days=30),
}


def _day_start(value):
    """Return an aware datetime at the start of the given local date."""
    return timezone.make_aware(
        datetime.combine(value, datetime.min.time()),
        timezone.get_current_timezone()
    )


def _report_bounds(report_type, start_date_str=None, end_date_str=None):
    if report_type in REPORT_PERIODS:
        end_date = timezone.now()
        return end_date - REPORT_PERIODS[report_type], end_date

    if report_type != 'custom':
        raise ValueError('Choose daily, weekly, monthly, or custom report type.')

    start_day = parse_date(start_date_str or '')
    end_day = parse_date(end_date_str or '')
    if not start_day or not end_day:
        raise ValueError('Choose a valid start date and end date.')
    if end_day < start_day:
        raise ValueError('End date must be after the start date.')

    start_date = _day_start(start_day)
    end_date = _day_start(end_day + timedelta(days=1))
    return start_date, end_date


def _login_stats(logs):
    successful_logins = logs.filter(action__in=SUCCESS_ACTIONS).count()
    failed_logins = logs.filter(action__in=FAILED_ACTIONS).count()
    total_logins = successful_logins + failed_logins
    return {
        'total_logins': total_logins,
        'successful_logins': successful_logins,
        'failed_logins': failed_logins,
        'success_rate': round((successful_logins / total_logins * 100) if total_logins else 0, 2),
        'unique_users': logs.filter(action__in=SUCCESS_ACTIONS, user__isnull=False).values('user').distinct().count(),
        'unique_ips': logs.exclude(ip_address__isnull=True).exclude(ip_address='').values('ip_address').distinct().count(),
    }


def _hourly_breakdown(logs):
    rows = logs.annotate(hour=ExtractHour('timestamp')).values('hour').annotate(
        successful=Count('id', filter=Q(action__in=SUCCESS_ACTIONS)),
        failed=Count('id', filter=Q(action__in=FAILED_ACTIONS)),
    )
    by_hour = {row['hour']: row for row in rows if row['hour'] is not None}
    return [
        {
            'hour': hour,
            'successful': by_hour.get(hour, {}).get('successful', 0),
            'failed': by_hour.get(hour, {}).get('failed', 0),
        }
        for hour in range(24)
    ]

@staff_member_required
def login_report_dashboard(request):
    """Dashboard for login reports and analytics"""
    period_start = timezone.now() - timedelta(days=30)
    period_logs = UserActivityLog.objects.filter(timestamp__gte=period_start)
    stats = _login_stats(period_logs)

    context = {
        'title': 'Login Reports Dashboard',
        'stats': stats,
        'recent_activities': UserActivityLog.objects.select_related('user').order_by('-timestamp')[:25],
        'recent_reports': LoginReport.objects.order_by('-generated_at')[:8],
        'active_alerts': LoginAlert.objects.filter(is_resolved=False).order_by('-created_at')[:8],
    }
    return render(request, 'reports/dashboard.html', context)

@staff_member_required
@require_POST
def generate_login_report(request):
    """Generate login report for a specific period"""
    report_type = request.POST.get('report_type', 'daily')

    try:
        start_date, end_date = _report_bounds(
            report_type,
            request.POST.get('start_date'),
            request.POST.get('end_date')
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    logs = UserActivityLog.objects.filter(timestamp__gte=start_date, timestamp__lt=end_date)
    stats = _login_stats(logs)

    suspicious_ips = (
        logs.filter(action__in=FAILED_ACTIONS)
        .exclude(ip_address__isnull=True)
        .exclude(ip_address='')
        .values('ip_address')
        .annotate(count=Count('id'))
        .filter(count__gte=5)
        .order_by('-count')
    )

    report = LoginReport.objects.create(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        total_logins=stats['total_logins'],
        successful_logins=stats['successful_logins'],
        failed_logins=stats['failed_logins'],
        unique_users=stats['unique_users'],
        unique_ips=stats['unique_ips'],
        report_data={
            'hourly_breakdown': _hourly_breakdown(logs),
            'suspicious_ips': list(suspicious_ips),
        }
    )

    return JsonResponse({
        'success': True,
        'report_id': report.id,
        'report_url': reverse('reports:view_report', args=[report.id]),
        'export_url': reverse('reports:export_csv', args=[report.id]),
        'stats': {
            'total_logins': stats['total_logins'],
            'successful': stats['successful_logins'],
            'failed': stats['failed_logins'],
            'success_rate': stats['success_rate'],
            'unique_users': stats['unique_users'],
            'unique_ips': stats['unique_ips'],
        }
    })

@staff_member_required
def view_report(request, report_id):
    """View a specific report"""
    report = get_object_or_404(LoginReport, id=report_id)
    success_rate = round((report.successful_logins / report.total_logins * 100) if report.total_logins else 0, 2)
    return render(request, 'reports/view_report.html', {'report': report, 'success_rate': success_rate})

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
@require_POST
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
        action__in=FAILED_ACTIONS
    ).exclude(
        ip_address__isnull=True
    ).exclude(
        ip_address=''
    ).values('ip_address').annotate(
        count=Count('id')
    ).filter(count__gte=3)
    
    # Create alerts for suspicious IPs
    for ip_data in suspicious_ips:
        alert, created = LoginAlert.objects.get_or_create(
            ip_address=ip_data['ip_address'],
            alert_type='multiple_failures',
            is_resolved=False,
            defaults={
                'severity': 'medium',
                'attempt_count': ip_data['count'],
            }
        )
        if not created and alert.attempt_count != ip_data['count']:
            alert.attempt_count = ip_data['count']
            alert.save(update_fields=['attempt_count'])
    
    alerts = LoginAlert.objects.filter(is_resolved=False)[:20]
    
    context = {
        'recent_activities': recent_activities,
        'alerts': alerts,
        'suspicious_ips': list(suspicious_ips),
    }
    return render(request, 'reports/realtime_monitoring.html', context)

@staff_member_required
@require_POST
def resolve_alert(request, alert_id):
    """Resolve an alert"""
    alert = get_object_or_404(LoginAlert, id=alert_id)
    alert.is_resolved = True
    alert.resolved_at = timezone.now()
    alert.resolved_by = request.user
    alert.save()
    
    return JsonResponse({'success': True, 'message': 'Alert resolved'})

@staff_member_required
@require_POST
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
