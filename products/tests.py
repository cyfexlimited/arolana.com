from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse, resolve

from currency.models import Currency
from orders.models import Cart, CartItem
from products import views
from products.models import Brand, Category, Product, ProductVideo
from products.video_commerce import _product_card

User = get_user_model()


class MarketplaceCatalogDiagnosticCommandTests(TestCase):
    def test_empty_catalog_exits_one_without_secret_output(self):
        output = StringIO()
        with self.assertRaises(SystemExit) as exc:
            call_command("diagnose_marketplace_catalog", stdout=output)
        self.assertEqual(exc.exception.code, 1)
        text = output.getvalue()
        self.assertIn("Product=0", text)
        self.assertIn("catalog_status=empty_or_no_active_approved_products", text)
        self.assertNotIn("PASSWORD", text.upper())
        self.assertNotIn("DATABASE_URL", text)
        self.assertNotIn("SECRET_KEY", text)

    def test_usable_catalog_exits_zero(self):
        vendor = User.objects.create_user(
            username="diag-vendor",
            email="diag-vendor@example.com",
            password="password123",
        )
        category = Category.objects.create(name="Diagnostic Products", slug="diagnostic-products")
        Product.objects.create(
            vendor=vendor,
            category=category,
            sku="DIAG-001",
            name="Diagnostic Product",
            slug="diagnostic-product",
            description="Approved diagnostic product.",
            price="1000.00",
            stock_quantity=1,
            approval_status="approved",
            is_active=True,
        )
        output = StringIO()
        with self.assertRaises(SystemExit) as exc:
            call_command("diagnose_marketplace_catalog", stdout=output)
        self.assertEqual(exc.exception.code, 0)
        self.assertIn("catalog_status=usable", output.getvalue())


class TestUrls(SimpleTestCase):
    """Test URL patterns are working correctly"""
    
    def test_product_list_url(self):
        url = reverse('products:list')
        self.assertEqual(resolve(url).func, views.product_list)
    
    def test_product_detail_url(self):
        url = reverse('products:detail', args=['test-product'])
        self.assertEqual(resolve(url).func, views.product_detail)
    
    def test_category_url(self):
        url = reverse('products:category', args=['electronics'])
        self.assertEqual(resolve(url).func, views.category_view)
    
    def test_cart_url(self):
        url = reverse('products:cart')
        self.assertEqual(resolve(url).func, views.cart_view)
    
    def test_add_to_cart_url(self):
        url = reverse('products:add_to_cart', args=['test-product'])
        self.assertEqual(resolve(url).func, views.add_to_cart)
    
    def test_add_review_url(self):
        url = reverse('products:add_review', args=['test-product'])
        self.assertEqual(resolve(url).func, views.add_review)
    
    def test_ask_question_url(self):
        url = reverse('products:ask_question', args=['test-product'])
        self.assertEqual(resolve(url).func, views.ask_question)
    
    def test_answer_question_url(self):
        url = reverse('products:answer_question', args=[1])
        self.assertEqual(resolve(url).func, views.answer_question)
    
    def test_toggle_wishlist_url(self):
        url = reverse('products:toggle_wishlist', args=['test-product'])
        self.assertEqual(resolve(url).func, views.toggle_wishlist)
    
    def test_variant_details_api_url(self):
        url = reverse('products:variant_details', args=[1])
        self.assertEqual(resolve(url).func, views.get_variant_details)
    
    def test_quick_view_api_url(self):
        url = reverse('products:quick_view_api', args=[1])
        self.assertEqual(resolve(url).func, views.quick_view_api)
    
    def test_questions_api_url(self):
        url = reverse('products:question_api', args=[1])
        self.assertEqual(resolve(url).func, views.get_question_api)
    
    def test_edit_question_url(self):
        url = reverse('products:edit_question', args=[1])
        self.assertEqual(resolve(url).func, views.edit_question)
    
    def test_delete_question_url(self):
        url = reverse('products:delete_question', args=[1])
        self.assertEqual(resolve(url).func, views.delete_question)
    
    def test_helpful_question_url(self):
        url = reverse('products:helpful_question', args=[1])
        self.assertEqual(resolve(url).func, views.helpful_question)
    
    def test_edit_answer_url(self):
        url = reverse('products:edit_answer', args=[1])
        self.assertEqual(resolve(url).func, views.edit_answer)
    
    def test_add_accessory_url(self):
        url = reverse('products:add_accessory_api', args=[1])
        self.assertEqual(resolve(url).func, views.add_accessory_to_cart)
    
    def test_cart_count_url(self):
        url = reverse('products:cart_count')
        self.assertEqual(resolve(url).func, views.cart_count)
    
    def test_checkout_url(self):
        url = reverse('products:checkout')
        self.assertEqual(resolve(url).func, views.checkout)
    
    def test_debug_colors_url(self):
        url = reverse('products:debug_colors', args=[1])
        self.assertEqual(resolve(url).func, views.debug_colors)


class ProductDescriptionSanitizationTests(SimpleTestCase):
    def test_placeholder_description_images_are_removed(self):
        html = (
            '<p>Before</p>'
            '<figure class="image"><img src="UPLOAD_PRODUCT_IMAGE_URL_HERE"></figure>'
            '<p>After</p>'
        )

        cleaned = Product._strip_placeholder_images(html)

        self.assertNotIn('UPLOAD_PRODUCT_IMAGE_URL_HERE', cleaned)
        self.assertNotIn('<figure', cleaned)
        self.assertIn('<p>Before</p>', cleaned)
        self.assertIn('<p>After</p>', cleaned)


class ProductVideoEmbedTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username="video-product-vendor",
            email="video-product-vendor@example.com",
            password="password123",
            user_type="vendor",
        )
        self.category = Category.objects.create(
            name="Video Product Tests",
            slug="video-product-tests",
            is_active=True,
        )
        self.product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            sku="VIDEO-PRODUCT-001",
            name="Video Product",
            slug="video-product",
            description="Approved product with video.",
            price="1000.00",
            stock_quantity=1,
            approval_status="approved",
            is_active=True,
        )

    def test_youtube_watch_url_returns_embed_url_without_attribute_error(self):
        video = ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            moderation_status="approved",
            is_active=True,
        )

        self.assertEqual(
            video.get_embed_url(),
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
            "?rel=0&modestbranding=1&playsinline=1&enablejsapi=1",
        )

    def test_youtu_be_url_returns_embed_url(self):
        video = ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="https://youtu.be/dQw4w9WgXcQ?si=test",
            moderation_status="approved",
            is_active=True,
        )

        self.assertEqual(
            video.get_embed_url(),
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
            "?rel=0&modestbranding=1&playsinline=1&enablejsapi=1",
        )

    def test_video_commerce_gallery_uses_product_video_canonical_embed(self):
        video = ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            moderation_status="approved",
            is_active=True,
        )
        canonical_url = (
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
            "?rel=0&modestbranding=1&playsinline=1&enablejsapi=1"
        )

        with patch.object(video, "get_embed_url", return_value=canonical_url) as builder:
            card = _product_card(None, video)

        builder.assert_called_once_with()
        self.assertEqual(card["embed_url"], canonical_url)

    def test_blank_or_invalid_youtube_url_fails_safely(self):
        blank_video = ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="",
            moderation_status="approved",
            is_active=True,
        )
        invalid_video = ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="https://example.com/not-youtube",
            moderation_status="approved",
            is_active=True,
        )

        self.assertIsNone(blank_video.get_embed_url())
        self.assertIsNone(invalid_video.get_embed_url())

    def test_product_detail_with_youtube_product_video_renders(self):
        ProductVideo.objects.create(
            product=self.product,
            source="youtube",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            moderation_status="approved",
            is_active=True,
        )

        response = Client().get(
            reverse(
                "products:detail",
                args=[self.product.slug],
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_real_description_images_are_preserved(self):
        html = '<figure class="image"><img src="/media/products/real.webp"></figure>'

        self.assertEqual(Product._strip_placeholder_images(html), html)


class ProductListCategoryBrandFilterTests(TestCase):
    def setUp(self):
        Currency.objects.create(
            code='NGN',
            symbol='N',
            name='Nigerian Naira',
            exchange_rate=Decimal('1500.000000'),
            is_base=True,
            is_active=True,
        )
        self.vendor = get_user_model().objects.create_user(
            email='filter-vendor@example.com',
            username='filtervendor',
            password='test-pass-123',
            user_type='vendor',
        )
        self.parent_category = Category.objects.create(
            name='Audio Visual',
            slug='audio-visual',
            is_active=True,
        )
        self.child_category = Category.objects.create(
            name='Video Conferencing',
            slug='video-conferencing',
            parent=self.parent_category,
            is_active=True,
        )
        self.brand = Brand.objects.create(
            name='Logitech',
            slug='logitech',
            is_active=True,
        )
        Product.objects.create(
            sku='LOGI-DESC-001',
            name='Logitech Descendant Camera',
            slug='logitech-descendant-camera',
            description='Approved Logitech product in an Audio Visual child category.',
            category=self.child_category,
            brand=self.brand,
            vendor=self.vendor,
            price=Decimal('100.00'),
            stock_quantity=5,
            is_active=True,
            approval_status='approved',
        )

    def test_product_list_category_brand_filter_includes_descendant_products(self):
        response = self.client.get(
            reverse('products:list'),
            {
                'categories': self.parent_category.slug,
                'brands': self.brand.slug,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context['paginator'].count, 0)
        self.assertContains(response, 'Logitech Descendant Camera')


class CartCurrencyTests(TestCase):
    def setUp(self):
        self.ngn = Currency.objects.create(
            code='NGN',
            symbol='N',
            name='Nigerian Naira',
            exchange_rate=Decimal('1500.000000'),
            is_base=True,
            is_active=True,
        )
        self.usd = Currency.objects.create(
            code='USD',
            symbol='$',
            name='US Dollar',
            exchange_rate=Decimal('1.000000'),
            is_active=True,
        )
        self.user = get_user_model().objects.create_user(
            email='cart@example.com',
            username='cartuser',
            password='test-pass-123',
        )
        self.vendor = get_user_model().objects.create_user(
            email='vendor@example.com',
            username='vendoruser',
            password='test-pass-123',
            user_type='vendor',
        )
        self.category = Category.objects.create(
            name='Guest Cart Category',
            slug='guest-cart-category',
            is_active=True,
        )

    def create_product(self, slug='guest-product', stock=10):
        return Product.objects.create(
            sku=f'SKU-{slug}',
            name='Guest Product',
            slug=slug,
            description='Guest product description',
            category=self.category,
            vendor=self.vendor,
            price=Decimal('100.00'),
            stock_quantity=stock,
            is_active=True,
            approval_status='approved',
        )

    def test_convert_price_returns_decimal(self):
        converted = views.convert_price(Decimal('598500.00'), self.ngn, self.usd)

        self.assertIsInstance(converted, Decimal)
        self.assertEqual(converted, Decimal('399.000000'))

    def test_cart_view_handles_converted_decimal_totals(self):
        cart = Cart.objects.create(user=self.user, is_active=True)
        CartItem.objects.create(
            cart=cart,
            quantity=2,
            price_at_add=Decimal('598500.00'),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('products:cart'),
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['subtotal_converted'], Decimal('798.000000'))

    def test_guest_can_add_to_cart_and_view_cart(self):
        product = self.create_product()

        response = self.client.post(
            reverse('products:add_to_cart', args=[product.slug]),
            {'quantity': '2'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cart_count'], 2)
        self.assertEqual(self.client.get(reverse('products:cart_count')).json()['count'], 2)

        cart_response = self.client.get(reverse('products:cart'))
        self.assertEqual(cart_response.status_code, 200)
        self.assertEqual(cart_response.context['cart'].total_items, 2)

    def test_guest_checkout_redirects_to_login_after_cart_add(self):
        product = self.create_product(slug='checkout-product')
        self.client.post(reverse('products:add_to_cart', args=[product.slug]), {'quantity': '1'})

        response = self.client.get(reverse('products:checkout'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('account_login'), response.url)
        self.assertIn('next=/products/checkout/', response.url)

    def test_guest_can_toggle_wishlist(self):
        product = self.create_product(slug='wishlist-product')

        response = self.client.post(
            reverse('products:toggle_wishlist', args=[product.slug]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['in_wishlist'])
        self.assertEqual(response.json()['wishlist_count'], 1)
        self.assertEqual(self.client.get(reverse('accounts:wishlist_count')).json()['count'], 1)

    def test_product_filters_convert_display_currency_to_catalog_currency(self):
        product = self.create_product(slug='usd-filter-product')
        product.price = Decimal('150000.00')
        product.save(update_fields=['price', 'updated_at'])
        request = RequestFactory().get(
            reverse('products:list'),
            {'min_price': '90', 'max_price': '110'},
        )
        request.user_currency = self.usd
        request.session = {'user_currency': 'USD'}

        filtered = views.apply_filters(Product.objects.all(), request)

        self.assertEqual(list(filtered), [product])

    def test_product_filters_support_all_condition_values(self):
        open_box = self.create_product(slug='open-box-product')
        open_box.condition = Product.CONDITION_OPEN_BOX
        open_box.save(update_fields=['condition', 'updated_at'])
        refurbished = self.create_product(slug='refurbished-product')
        refurbished.condition = Product.CONDITION_REFURBISHED
        refurbished.save(update_fields=['condition', 'updated_at'])
        self.create_product(slug='brand-new-product')
        request = RequestFactory().get(
            reverse('products:list'),
            {'conditions': 'open_box,refurbished'},
        )
        request.user_currency = self.ngn
        request.session = {'user_currency': 'NGN'}

        filtered = views.apply_filters(Product.objects.all(), request)

        self.assertCountEqual(list(filtered), [open_box, refurbished])

    def test_product_collection_filters_only_matching_products(self):
        featured = self.create_product(slug='featured-collection-product')
        featured.is_featured = True
        featured.save(update_fields=['is_featured', 'updated_at'])
        self.create_product(slug='regular-collection-product')
        request = RequestFactory().get(
            reverse('products:list'),
            {'collection': 'featured'},
        )
        request.user_currency = self.ngn
        request.session = {'user_currency': 'NGN'}

        filtered = views.apply_filters(Product.objects.all(), request)

        self.assertEqual(list(filtered), [featured])

    def test_duplicate_product_names_get_vendor_aware_slugs(self):
        first = Product.objects.create(
            sku='SLUG-001',
            name='Shared Marketplace Camera',
            slug='shared-marketplace-camera',
            description='First vendor listing',
            category=self.category,
            vendor=self.vendor,
            price=Decimal('100.00'),
            stock_quantity=5,
            is_active=True,
            approval_status='approved',
        )
        second_vendor = get_user_model().objects.create_user(
            email='vendor-two@example.com',
            username='vendor-two',
            password='test-pass-123',
            user_type='vendor',
        )
        second = Product.objects.create(
            sku='SLUG-002',
            name='Shared Marketplace Camera',
            slug='shared-marketplace-camera',
            description='Second vendor listing',
            category=self.category,
            vendor=second_vendor,
            price=Decimal('100.00'),
            stock_quantity=5,
            is_active=True,
            approval_status='approved',
        )

        self.assertEqual(first.slug, 'shared-marketplace-camera')
        self.assertNotEqual(second.slug, first.slug)
        self.assertTrue(second.slug.startswith('shared-marketplace-camera-'))
