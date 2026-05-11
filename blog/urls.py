from django.urls import path
from . import views

app_name = 'blog'

urlpatterns = [
    path('', views.blog_list, name='list'),
    path('subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    path('like/<int:post_id>/', views.like_post, name='like_post'),
    path('category/<slug:slug>/', views.blog_category, name='category'),
    path('tag/<slug:slug>/', views.blog_tag, name='tag'),
    # This must come LAST to avoid matching 'subscribe' as a slug
    path('<slug:slug>/', views.blog_detail, name='detail'),
    path('<slug:slug>/comment/', views.add_comment, name='add_comment'),
    path('newsletter/admin/', views.newsletter_admin, name='newsletter_admin'),
    path('newsletter/send/', views.send_newsletter, name='send_newsletter'),
    path('article/<slug:slug>/', views.blog_detail, name='detail'),
]

