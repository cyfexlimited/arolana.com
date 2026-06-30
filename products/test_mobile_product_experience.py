import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from ads.models import Advertisement
from blog.models import BlogPost
from mobile_customers.models import MobileCustomer
from orders.models import OrderItem
from products.models import (
    Accessory,
    AccessoryProduct,
    Category,
    Product,
    ProductArticleLink,
)


class MobileProductExperienceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.vendor = User.objects.create_user(
            email="mobile-product-vendor@example.com",
            username="mobile-product-vendor",
            password="test-password",
            user_type="vendor",
        )
        self.customer_user = User.objects.create_user(
            email="mobile-product-customer@example.com",
            username="mobile-product-customer",
            password="test-password",
        )
        self.customer = MobileCustomer.objects.create(
            user=self.customer_user,
            full_name="Mobile Customer",
            phone_number="+2348011112222",
            email=self.customer_user.email,
            api_token="mobile-product-token",
        )
        self.category = Category.objects.create(
            name="Video Conferencing",
            slug="video-conferencing-mobile-test",
            is_active=True,
        )
        self.product = Product.objects.create(
            sku="MOBILE-RALLY-TEST",
            name="Rally Plus Mobile Test",
            slug="rally-plus-mobile-test",
            description="<p>Full product description.</p>",
            specifications="<p>Resolution: 4K</p>",
            category=self.category,
            vendor=self.vendor,
            price=Decimal("1000.00"),
            stock_quantity=10,
            is_active=True,
            approval_status="approved",
        )

    def test_product_detail_returns_full_linked_article_and_accessories(self):
        article = BlogPost.objects.create(
            author=self.vendor,
            title="Complete Rally Plus Guide",
            slug="complete-rally-plus-guide",
            excerpt="A complete guide.",
            content="<h2>Full guide</h2><p>This content must not be truncated.</p>",
            meta_title="Rally Plus SEO",
            is_published=True,
        )
        ProductArticleLink.objects.create(
            product=self.product,
            article=article,
            placement="articles_tab",
            is_active=True,
        )
        accessory = Accessory.objects.create(
            name="Expansion Microphone",
            slug="expansion-microphone-mobile-test",
            price=Decimal("250.00"),
            stock_quantity=5,
            is_active=True,
        )
        AccessoryProduct.objects.create(
            product=self.product,
            accessory=accessory,
        )

        response = self.client.get(
            f"/api/mobile/products/{self.product.slug}/"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["product_article"]["article"]["title"],
            article.title,
        )
        self.assertIn(
            "must not be truncated",
            payload["product_article"]["article"]["content"],
        )
        self.assertEqual(
            payload["product_article"]["article"]["seo"]["title"],
            "Rally Plus SEO",
        )
        self.assertEqual(payload["accessories"][0]["id"], accessory.id)

    def test_invalid_product_ad_becomes_native_search_destination(self):
        Advertisement.objects.create(
            title="Summer Sale",
            url="https://arolana.com/products/summer-sale/",
            placement="homepage",
            is_active=True,
            show_to_guests=True,
        )

        response = self.client.get("/api/mobile/home/")

        self.assertEqual(response.status_code, 200)
        ad = next(
            item
            for item in response.json()["homepage_ads"]
            if item["title"] == "Summer Sale"
        )
        self.assertEqual(ad["destination_type"], "search")
        self.assertEqual(ad["search_query"], "Summer Sale")

    def test_mobile_checkout_creates_accessory_order_item(self):
        accessory = Accessory.objects.create(
            name="HDMI Cable",
            slug="hdmi-cable-mobile-test",
            price=Decimal("25.00"),
            stock_quantity=20,
            is_active=True,
        )
        payload = {
            "mobile_customer": {
                "phone_number": self.customer.phone_number,
                "api_token": self.customer.api_token,
            },
            "customer": {
                "full_name": self.customer.full_name,
                "phone_number": self.customer.phone_number,
                "email": self.customer.email,
                "delivery_address": "1 Arolana Street",
                "city_state": "Ikeja, Lagos",
            },
            "phone_number": self.customer.phone_number,
            "api_token": self.customer.api_token,
            "payment_method": "paystack",
            "items": [
                {
                    "accessory_id": accessory.id,
                    "quantity": 2,
                }
            ],
        }

        response = self.client.post(
            "/api/mobile/orders/create/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.customer.api_token}",
        )

        self.assertEqual(response.status_code, 201, response.content)
        order_item = OrderItem.objects.get()
        self.assertIsNone(order_item.product_id)
        self.assertEqual(order_item.accessory_id, accessory.id)
        self.assertEqual(order_item.quantity, 2)
