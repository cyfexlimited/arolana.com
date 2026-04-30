from django.urls import path
from . import views

app_name = 'footer_menu'

urlpatterns = [
    path('', views.footer_menu_list, name='list'),
    path('manage/', views.manage_footer_menu, name='manage'),
]
