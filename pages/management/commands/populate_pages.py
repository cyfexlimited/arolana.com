from django.core.management.base import BaseCommand
from pages.models import Page, SupportTopic, SupportArticle, FAQ

class Command(BaseCommand):
    help = 'Populate all pages with production-ready content'
    
    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('📝 Populating pages with content...'))
        
        # Create Pages
        pages_list = [
            {
                'slug': 'home',
                'title': 'Welcome to Arolana - Premium Marketplace',
                'content': '<h1>Welcome to Arolana</h1><p>Your premier destination for premium products from verified vendors worldwide.</p>',
                'meta_description': 'Shop premium products from verified vendors worldwide. Fast shipping, secure payments.',
                'is_active': True
            },
            {
                'slug': 'about',
                'title': 'About Arolana',
                'content': '<h1>About Us</h1><p>Arolana is a leading multi-vendor marketplace connecting quality sellers with discerning buyers.</p>',
                'meta_description': 'Learn about Arolana marketplace and our mission.',
                'is_active': True
            },
            {
                'slug': 'contact',
                'title': 'Contact Us',
                'content': '<h1>Contact Us</h1><p>Email: support@arolana.com<br>Phone: +1-800-AROLANA</p>',
                'meta_description': 'Contact our support team via email or phone.',
                'is_active': True
            },
            {
                'slug': 'privacy',
                'title': 'Privacy Policy',
                'content': '<h1>Privacy Policy</h1><p>Last updated: 2026. We value your privacy and protect your data.</p>',
                'meta_description': 'Read our privacy policy to understand how we protect your data.',
                'is_active': True
            },
            {
                'slug': 'terms',
                'title': 'Terms & Conditions',
                'content': '<h1>Terms & Conditions</h1><p>Please read our terms of service carefully before using our platform.</p>',
                'meta_description': 'Terms and conditions for using Arolana marketplace.',
                'is_active': True
            },
            {
                'slug': 'returns',
                'title': 'Returns Policy',
                'content': '<h1>Returns & Refunds Policy</h1><p>30-day return policy for most items. Contact support to initiate returns.</p>',
                'meta_description': 'Our 30-day return policy and refund process.',
                'is_active': True
            },
            {
                'slug': 'faq',
                'title': 'Frequently Asked Questions',
                'content': '<h1>FAQ</h1><p>Find answers to common questions about ordering, shipping, and returns.</p>',
                'meta_description': 'Frequently asked questions about Arolana marketplace.',
                'is_active': True
            },
        ]
        
        for page_data in pages_list:
            page, created = Page.objects.get_or_create(
                slug=page_data['slug'],
                defaults=page_data
            )
            status = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f'  ✓ {status}: {page.title}'))
        
        # Create Support Topics
        topics_list = [
            {'title': 'Orders & Shipping', 'slug': 'orders-shipping', 'icon': 'fas fa-box', 'order': 1, 'is_active': True},
            {'title': 'Returns & Refunds', 'slug': 'returns-refunds', 'icon': 'fas fa-undo', 'order': 2, 'is_active': True},
            {'title': 'Account & Security', 'slug': 'account-security', 'icon': 'fas fa-lock', 'order': 3, 'is_active': True},
            {'title': 'Payments', 'slug': 'payments', 'icon': 'fas fa-credit-card', 'order': 4, 'is_active': True},
            {'title': 'Vendor Help', 'slug': 'vendor-help', 'icon': 'fas fa-store', 'order': 5, 'is_active': True},
        ]
        
        for topic_data in topics_list:
            topic, created = SupportTopic.objects.get_or_create(
                slug=topic_data['slug'],
                defaults=topic_data
            )
            status = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f'  ✓ {status}: {topic.title}'))
        
        # Create Support Articles
        articles_list = [
            {
                'title': 'How to Track Your Order',
                'slug': 'how-to-track-order',
                'category_slug': 'orders-shipping',
                'content': '<p>Once your order ships, you will receive a tracking number via email. You can track your shipment in real-time through your account dashboard under "My Orders".</p>',
                'is_active': True
            },
            {
                'title': 'How to Initiate a Return',
                'slug': 'how-to-initiate-return',
                'category_slug': 'returns-refunds',
                'content': '<p>To start a return, visit your order history, select the item you want to return, and click "Return Item". Follow the instructions provided.</p>',
                'is_active': True
            },
            {
                'title': 'How to Reset Your Password',
                'slug': 'how-to-reset-password',
                'category_slug': 'account-security',
                'content': '<p>Click "Forgot Password" on the login page, enter your email, and follow the instructions sent to your inbox.</p>',
                'is_active': True
            },
        ]
        
        for article_data in articles_list:
            category_slug = article_data.pop('category_slug')
            try:
                category = SupportTopic.objects.get(slug=category_slug)
                article, created = SupportArticle.objects.get_or_create(
                    slug=article_data['slug'],
                    defaults={**article_data, 'category': category}
                )
                status = "Created" if created else "Updated"
                self.stdout.write(self.style.SUCCESS(f'  ✓ {status}: {article.title}'))
            except SupportTopic.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'  ⚠ Skipping article: category "{category_slug}" not found'))
        
        # Create FAQs
        faqs_list = [
            {
                'question': 'How do I place an order?',
                'answer': 'Simply browse our products, add items to your cart, and proceed to checkout.',
                'category': 'general',
                'order': 1,
                'is_active': True
            },
            {
                'question': 'What payment methods do you accept?',
                'answer': 'We accept credit cards (Visa, MasterCard, American Express), PayPal, Apple Pay, and Google Pay.',
                'category': 'payments',
                'order': 1,
                'is_active': True
            },
            {
                'question': 'How long does shipping take?',
                'answer': 'Standard shipping takes 3-7 business days. Express shipping takes 1-3 business days.',
                'category': 'orders',
                'order': 1,
                'is_active': True
            },
            {
                'question': 'What is your return policy?',
                'answer': 'We offer a 30-day return policy for most items. Items must be unused and in original condition.',
                'category': 'returns',
                'order': 1,
                'is_active': True
            },
            {
                'question': 'How do I become a vendor?',
                'answer': 'Click "Sell" in the navigation, complete the vendor application, and upload required documents.',
                'category': 'vendors',
                'order': 1,
                'is_active': True
            },
            {
                'question': 'Is my payment information secure?',
                'answer': 'Yes, we use industry-standard SSL encryption to protect all payment data.',
                'category': 'payments',
                'order': 2,
                'is_active': True
            },
        ]
        
        for faq_data in faqs_list:
            faq, created = FAQ.objects.get_or_create(
                question=faq_data['question'],
                defaults=faq_data
            )
            status = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f'  ✓ {status}: {faq.question[:40]}...'))
        
        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('✅ All pages and content populated successfully!'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write('\n📋 Summary:')
        self.stdout.write(f'   • {Page.objects.filter(is_active=True).count()} Pages')
        self.stdout.write(f'   • {SupportTopic.objects.filter(is_active=True).count()} Support Topics')
        self.stdout.write(f'   • {SupportArticle.objects.filter(is_active=True).count()} Support Articles')
        self.stdout.write(f'   • {FAQ.objects.filter(is_active=True).count()} FAQs')
        self.stdout.write('\n🎯 Visit: http://localhost:8000/')
        self.stdout.write('   http://localhost:8000/about/')
        self.stdout.write('   http://localhost:8000/contact/')
        self.stdout.write('   http://localhost:8000/privacy/')
        self.stdout.write('   http://localhost:8000/terms/')
        self.stdout.write('   http://localhost:8000/returns/')
        self.stdout.write('   http://localhost:8000/faq/')