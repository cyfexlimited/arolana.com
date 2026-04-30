from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('dashboard/', views.login_report_dashboard, name='dashboard'),
    path('generate/', views.generate_login_report, name='generate_report'),
    path('view/<int:report_id>/', views.view_report, name='view_report'),
    path('export/<int:report_id>/csv/', views.export_report_csv, name='export_csv'),
    path('login-attempts/', views.login_attempts_list, name='login_attempts'),
    path('unlock/<int:attempt_id>/', views.unlock_account, name='unlock_account'),
    path('user-activity/<int:user_id>/', views.user_activity_report, name='user_activity'),
    path('realtime/', views.realtime_monitoring, name='realtime'),
    path('resolve-alert/<int:alert_id>/', views.resolve_alert, name='resolve_alert'),
    path('block-ip/<str:ip_address>/', views.block_ip, name='block_ip'),
]
