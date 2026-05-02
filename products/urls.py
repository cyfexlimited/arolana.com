from django.urls import path, re_path
from . import views

app_name = 'products'

urlpatterns = [
    # Cart related URLs (must come before slug patterns)
    path('', views.product_list, name='list'),
    path('cart/', views.cart_view, name='cart'),
    path('cart/update/', views.update_cart, name='update_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/count/', views.cart_count, name='cart_count'),
    path('checkout/', views.checkout, name='checkout'),
    
    # API and debug URLs
    path('api/variant/<int:variant_id>/', views.get_variant_details, name='variant_details'),
    path('api/<int:product_id>/quick-view/', views.quick_view_api, name='quick_view_api'),
    path('debug-colors/<int:product_id>/', views.debug_colors, name='debug_colors'),
    
    # Category URL
    path('category/<slug:slug>/', views.category_view, name='category'),
    
    # Product Q&A URLs
    path('<slug:slug>/ask-question/', views.ask_question, name='ask_question'),
    path('answer-question/<int:qna_id>/', views.answer_question, name='answer_question'),
    
    # Product action URLs (must come before detail)
    path('<slug:slug>/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('<slug:slug>/add-review/', views.add_review, name='add_review'),
    path('<slug:slug>/toggle-wishlist/', views.toggle_wishlist, name='toggle_wishlist'),
    
    # Product detail (must be last to catch all other slugs)
    path('<slug:slug>/', views.product_detail, name='detail'),
]