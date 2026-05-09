from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    # ================================
    # API Endpoints (must be before slug patterns)
    # ================================
    path('api/variant/<int:variant_id>/', views.get_variant_details, name='variant_details'),
    path('api/quick-view/<int:product_id>/', views.quick_view_api, name='quick_view_api'),
    path('api/questions/<int:product_id>/', views.get_question_api, name='question_api'),
    path('api/accessory/<int:accessory_id>/add/', views.add_accessory_to_cart, name='add_accessory_api'),
    
    # ================================
    # Cart Management (static paths, before slug patterns)
    # ================================
    path('cart/', views.cart_view, name='cart'),
    path('cart/update/', views.update_cart, name='update_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/count/', views.cart_count, name='cart_count'),
    path('checkout/', views.checkout, name='checkout'),
    
    # ================================
    # Q&A Management (integer-based, before slug patterns)
    # ================================
    path('question/<int:qna_id>/helpful/', views.helpful_question, name='helpful_question'),
    path('question/<int:qna_id>/edit/', views.edit_question, name='edit_question'),
    path('question/<int:qna_id>/delete/', views.delete_question, name='delete_question'),
    path('answer/<int:qna_id>/edit/', views.edit_answer, name='edit_answer'),
    path('answer-question/<int:qna_id>/', views.answer_question, name='answer_question'),
    
    # ================================
    # Debug (integer-based, before slug patterns)
    # ================================
    path('debug-colors/<int:product_id>/', views.debug_colors, name='debug_colors'),
    
    # ================================
    # Main Listing (empty slug)
    # ================================
    path('', views.product_list, name='list'),
    
    # ================================
    # SLUG-BASED PATTERNS (most specific first)
    # ================================
    # Category view
    path('category/<slug:slug>/', views.category_view, name='category'),
    
    # Product interactions (slug + action)
    path('<slug:slug>/add-review/', views.add_review, name='add_review'),
    path('<slug:slug>/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('<slug:slug>/toggle-wishlist/', views.toggle_wishlist, name='toggle_wishlist'),
    path('<slug:slug>/ask-question/', views.ask_question, name='ask_question'),
    path('<slug:slug>/quick-view/', views.quick_view, name='quick_view'),
    
    # ================================
    # ⚠️ MUST BE LAST - Generic Product Detail View
    # ================================
    path('<slug:slug>/', views.product_detail, name='detail'),
]
