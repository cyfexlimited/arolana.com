from django.test import TestCase

from accounts.models import User
from blog.models import BlogCategory, BlogComment, BlogPost, BlogTag
from mobile_customers.models import MobileCustomer
from core.models import ContentTranslation
from hero_banners.models import HeroBanner
from products.models import Category


class MobileHomePayloadTests(TestCase):
    def test_home_payload_serializes_categories_without_images(self):
        Category.objects.create(
            name="Investor Demo Category",
            slug="investor-demo-category",
            is_active=True,
        )

        response = self.client.get("/api/mobile/home/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        categories = payload.get("mega_categories") or payload.get("categories") or []
        category = next(
            item for item in categories if item.get("slug") == "investor-demo-category"
        )
        self.assertIn("thumbnail_url", category)
        self.assertIn("image_url", category)
        self.assertIn("original_url", category)
        self.assertIn("category_image_url", category)
        self.assertIn("category_banner_url", category)
        self.assertIn("category_icon", category)

    def test_home_payload_honors_accept_language_with_english_fallback(self):
        category = Category.objects.create(
            name="Networking",
            slug="networking-language-test",
            description="Network products",
            is_active=True,
        )
        ContentTranslation.objects.create(
            content_object=category,
            language_code="ig",
            field_name="name",
            translated_text="Netwọkụ",
        )

        translated_response = self.client.get(
            "/api/mobile/home/",
            HTTP_ACCEPT_LANGUAGE="ig",
        )
        translated_category = next(
            item for item in translated_response.json()["mega_categories"]
            if item["slug"] == category.slug
        )
        self.assertEqual(translated_category["name"], "Netwọkụ")
        self.assertEqual(translated_category["description"], "Network products")

        fallback_response = self.client.get(
            "/api/mobile/home/",
            HTTP_ACCEPT_LANGUAGE="es",
        )
        fallback_category = next(
            item for item in fallback_response.json()["mega_categories"]
            if item["slug"] == category.slug
        )
        self.assertEqual(fallback_category["name"], "Networking")

    def test_linked_article_overrides_stale_manual_hero_link(self):
        author = User.objects.create_user(
            username="hero-article-author",
            email="hero-article@example.com",
            password="test-password",
        )
        article = BlogPost.objects.create(
            author=author,
            title="Google Pixel Fold Guide",
            slug="google-pixel-fold-guide",
            excerpt="A complete buying guide.",
            content="<p>Article content.</p>",
            is_published=True,
        )
        banner = HeroBanner.objects.create(
            title="Read the guide",
            linked_article=article,
            enable_slide_link=True,
            slide_link_url="/products/google-pixel-fold/",
            is_active=True,
        )

        self.assertEqual(banner.effective_slide_link_url, article.get_absolute_url())

        response = self.client.get("/api/mobile/home/")
        self.assertEqual(response.status_code, 200)
        hero = next(
            item
            for item in response.json()["hero_banners"]
            if item["id"] == banner.id
        )
        self.assertEqual(hero["linked_article_slug"], article.slug)
        self.assertEqual(hero["effective_slide_link_url"], article.get_absolute_url())
        self.assertTrue(hero["linked_article_url"].endswith(article.get_absolute_url()))

    def test_mobile_article_detail_returns_native_article_payload(self):
        author = User.objects.create_user(
            username="mobile-article-author",
            email="mobile-article@example.com",
            password="test-password",
        )
        article = BlogPost.objects.create(
            author=author,
            title="Investor Article",
            slug="investor-article",
            excerpt="Useful article summary.",
            content="<h2>What to know</h2><p>Native article content.</p>",
            is_published=True,
        )
        category = BlogCategory.objects.create(
            name="Buying Guides",
            slug="buying-guides",
        )
        article.category = category
        article.save(update_fields=["category", "updated_at"])
        tag = BlogTag.objects.create(name="Investor", slug="investor")
        article.tags.add(tag)
        customer = MobileCustomer.objects.create(
            user=author,
            full_name=author.get_full_name(),
            phone_number="+2348011122233",
            email=author.email,
            api_token="article-comment-token",
        )
        BlogComment.objects.create(
            post=article,
            user=author,
            comment="Existing native comment.",
            is_approved=True,
        )

        response = self.client.get(f"/api/mobile/articles/{article.slug}/")

        self.assertEqual(response.status_code, 200)
        response_payload = response.json()
        payload = response_payload["article"]
        self.assertEqual(payload["slug"], article.slug)
        self.assertEqual(payload["title"], article.title)
        self.assertIn("Native article content", payload["content"])
        self.assertEqual(payload["tags"][0]["slug"], tag.slug)
        self.assertEqual(response_payload["comments"][0]["comment"], "Existing native comment.")
        self.assertEqual(response_payload["categories"][0]["slug"], category.slug)
        self.assertIn("popular_posts", response_payload)
        self.assertEqual(response_payload["share_url"], payload["url"])

        comment_response = self.client.post(
            f"/api/mobile/articles/{article.slug}/comments/",
            data='{"comment": "Commented inside Arolana mobile."}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {customer.api_token}",
        )
        self.assertEqual(comment_response.status_code, 201)
        self.assertTrue(comment_response.json()["success"])
        self.assertTrue(
            BlogComment.objects.filter(
                post=article,
                comment="Commented inside Arolana mobile.",
            ).exists()
        )
