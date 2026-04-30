from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.debug_home, name='debug_home'),
]
