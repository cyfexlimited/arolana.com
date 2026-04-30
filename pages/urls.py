from django.urls import path
from . import views

app_name = 'pages'

urlpatterns = [
    # Help Center URLs
    path('', views.help_center, name='help_center'),
    path('help/', views.help_center, name='help_center'),
    path('faq/', views.faq_page, name='faq'),
    
    # Page URLs
    path('page/<slug:slug>/', views.page_detail, name='detail'),
    
    # Article URLs
    path('article/<slug:slug>/', views.article_detail, name='article_detail'),
    path('article/helpful/<int:article_id>/', views.article_helpful, name='article_helpful'),
    
    # Career URLs
    path('careers/', views.careers_page, name='careers'),
    path('job/<slug:slug>/', views.job_detail, name='job_detail'),
    path('apply/<int:position_id>/', views.apply_for_job, name='apply_job'),
]
