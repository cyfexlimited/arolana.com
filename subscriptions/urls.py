from django.urls import path
from . import views

app_name = 'subscriptions'

urlpatterns = [
    path('plans/', views.subscription_plans, name='plans'),
    path('subscribe/<int:plan_id>/', views.subscribe, name='subscribe'),
    path('cancel/<int:subscription_id>/', views.cancel_subscription, name='cancel'),
    path('history/', views.subscription_history, name='history'),
]
