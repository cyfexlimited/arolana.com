from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list, name='list'),
    path('mark-read/<int:notification_id>/', views.mark_as_read, name='mark_read'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('delete/<int:notification_id>/', views.delete_notification, name='delete'),
    path('delete-all-read/', views.delete_all_read, name='delete_all_read'),
    path('settings/', views.notification_settings, name='settings'),
    path('test/', views.create_test_notification, name='test'),
    path('api/', views.get_notifications_api, name='api'),
    path('unread-count/', views.get_unread_count, name='unread_count'),
]