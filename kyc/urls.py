from django.urls import path
from . import views

app_name = 'kyc'

urlpatterns = [
    path('', views.kyc_dashboard, name='dashboard'),
    path('submit/', views.submit_kyc, name='submit'),
    path('upload/', views.upload_document, name='upload_document'),
    path('status/', views.kyc_status, name='status'),
]
