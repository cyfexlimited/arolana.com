from django.urls import path
from . import views

app_name = 'currency'

urlpatterns = [
    path('switch/', views.switch_currency, name='switch'),
    path('detect/', views.detect_currency, name='detect'),
    path('settings/', views.currency_settings, name='settings'),
    path('info/', views.currency_info, name='info'),
    path('current/', views.get_current_currency, name='current'),
    path('set-ajax/', views.set_currency_ajax, name='set_ajax'),
    path('debug/', views.debug_currency, name='debug'),
    path('verify/', views.verify_currency, name='verify'),
    path('check-session/', views.check_session, name='check_session'),
    path('force-test/', views.force_test, name='force_test'),
    path('update-rates/', views.update_exchange_rates, name='update_rates'),
    path('rate/<str:from_currency>/<str:to_currency>/', views.get_exchange_rate, name='rate'),
    path('convert/', views.convert_amount, name='convert'),
    path('test-currency/', views.test_currency, name='test_currency'),
]

