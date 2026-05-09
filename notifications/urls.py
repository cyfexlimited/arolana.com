from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Main views
    path('', views.notification_list, name='list'),
    path('<int:notification_id>/', views.notification_detail, name='detail'),
    path('settings/', views.preferences, name='settings'),
    path('preferences/', views.preferences, name='preferences'),
    
    # Actions
    path('mark/<int:notification_id>/', views.mark_as_read, name='mark_read'),
    path('mark-all/', views.mark_all_read, name='mark_all'),
    path('delete/<int:notification_id>/', views.delete_notification, name='delete'),
    path('delete-all-read/', views.delete_all_read, name='delete_all_read'),
    path('delete-all/', views.delete_all, name='delete_all'),
    path('bulk-action/', views.bulk_action, name='bulk_action'),
    
    # API endpoints - Adding both old and new endpoints for compatibility
    path('unread-count/', views.get_unread_count, name='unread_count'),
    path('api/unread-count/', views.get_unread_count, name='api_unread_count'),
    path('api/get/', views.get_notifications_api, name='api_get'),
    path('api/latest/', views.get_latest_notifications, name='api_latest'),
    
    # Test
    path('test/', views.create_test_notification, name='test'),
]