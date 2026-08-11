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


    path(
        "brands/",
        views.brand_directory,
        name="brand_directory",
    ),

    path(
        "brands/<slug:slug>/",
        views.brand_detail,
        name="brand_detail",
    ),
    # ================================
    # Cart Management (static paths, before slug patterns)
    # ================================
    path('cart/', views.cart_view, name='cart'),
    path('cart/update/', views.update_cart, name='update_cart'),
    path('cart/remove/<str:item_id>/', views.remove_from_cart, name='remove_from_cart'),
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
    path("mobile/home/", views.mobile_home_api, name="mobile_home_api"),
    path("mobile/articles/", views.mobile_articles_api, name="mobile_articles_api"),
    path("mobile/articles/categories/", views.mobile_article_categories_api, name="mobile_article_categories_api"),
    path("mobile/articles/tags/", views.mobile_article_tags_api, name="mobile_article_tags_api"),
    path("mobile/articles/<slug:slug>/comments/", views.mobile_article_comments_api, name="mobile_article_comments_api"),
    path("mobile/articles/<slug:slug>/", views.mobile_article_detail_api, name="mobile_article_detail_api"),
    path("mobile/product-config/", views.mobile_product_config_api, name="mobile_product_config_api"),
    path("mobile/products/", views.mobile_products_api, name="mobile_products_api"),
    path("mobile/categories/<slug:slug>/", views.mobile_category_detail_api, name="mobile_category_detail_api"),
    path("mobile/products/<slug:slug>/review/", views.mobile_product_review_api, name="mobile_product_review_api"),
    path("mobile/products/<slug:slug>/question/", views.mobile_product_question_api, name="mobile_product_question_api"),
    path("mobile/products/<slug:slug>/", views.mobile_product_detail_api, name="mobile_product_detail_api"),
    path("mobile/vendors/", views.mobile_vendors_api, name="mobile_vendors_api"),
    path("mobile/vendors/<int:vendor_id>/", views.mobile_vendor_detail_api, name="mobile_vendor_detail_api"),
    path("mobile/vendors/<int:vendor_id>/products/", views.mobile_vendor_products_api, name="mobile_vendor_products_api"),
    path("mobile/vendors/<int:vendor_id>/follow/", views.mobile_vendor_follow_api, name="mobile_vendor_follow_api"),
    path("mobile/vendors/<int:vendor_id>/unfollow/", views.mobile_vendor_unfollow_api, name="mobile_vendor_unfollow_api"),
    path("mobile/vendors/request-callback/", views.mobile_vendor_request_callback_api, name="mobile_vendor_request_callback_api"),
    path("mobile/vendors/reveal-phone/", views.mobile_vendor_reveal_phone_api, name="mobile_vendor_reveal_phone_api"),
    path("mobile/vendors/track-contact/", views.mobile_vendor_track_contact_api, name="mobile_vendor_track_contact_api"),
    path("mobile/vendors/chat/context/", views.mobile_vendor_chat_context_api, name="mobile_vendor_chat_context_api"),
    path("mobile/vendors/chat/<int:room_id>/send/", views.mobile_vendor_chat_send_api, name="mobile_vendor_chat_send_api"),
    path(
        "api/mobile/brands/",
        views.mobile_brand_directory_api,
        name="mobile_brand_directory_api",
    ),

    path(
        "api/mobile/brands/<slug:slug>/",
        views.mobile_brand_detail_api,
        name="mobile_brand_detail_api",
    ),
    path("mobile/rfqs/", views.mobile_rfqs_api, name="mobile_rfqs_api"),
    path("mobile/rfqs/create/", views.mobile_rfq_create_api, name="mobile_rfq_create_api"),
    path("mobile/rfqs/<int:rfq_id>/", views.mobile_rfq_detail_api, name="mobile_rfq_detail_api"),
    path("mobile/rfqs/<int:rfq_id>/<str:action>/", views.mobile_rfq_status_api, name="mobile_rfq_status_api"),
    path("mobile/product-videos/", views.mobile_product_video_feed_api, name="mobile_product_video_feed_api"),
    path("mobile/product-videos/<int:video_id>/rate/", views.mobile_product_video_rate_api, name="mobile_product_video_rate_api"),
    path("mobile/product-videos/<int:video_id>/comments/", views.mobile_product_video_comments_api, name="mobile_product_video_comments_api"),
    path("mobile/product-video-comments/<int:comment_id>/", views.mobile_product_video_comment_detail_api, name="mobile_product_video_comment_detail_api"),
    path("mobile/admin/product-video-comments/<int:comment_id>/<str:action>/", views.admin_product_video_comment_action_api, name="admin_product_video_comment_action_api"),
    path("mobile/product-videos/<int:video_id>/<str:event>/", views.mobile_product_video_event_api, name="mobile_product_video_event_api"),
    path("mobile/vendor/product-videos/", views.vendor_product_videos_api, name="vendor_product_videos_api"),
    path("mobile/admin/product-videos/", views.admin_product_videos_api, name="admin_product_videos_api"),
    path("mobile/admin/product-videos/<int:video_id>/<str:action>/", views.admin_product_video_action_api, name="admin_product_video_action_api"),
    path('secure-payments/', views.secure_payments, name='secure_payments'),
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
