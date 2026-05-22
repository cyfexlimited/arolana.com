from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse, resolve

from currency.models import Currency
from orders.models import Cart, CartItem
from products import views
from products.models import Category, Product

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
