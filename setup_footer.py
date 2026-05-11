import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'arolana_config.settings')
django.setup()

from footer_menu.models import FooterMenuCategory, FooterMenuItem

print("=" * 50)
print("Setting up footer menus...")
print("=" * 50)

# Clear existing
FooterMenuItem.objects.all().delete()
FooterMenuCategory.objects.all().delete()
print("✓ Cleared existing menus")

# Create Shop menu
shop = FooterMenuCategory.objects.create(
    name='Shop',
    slug='shop',
    display_order=1,
    is_active=True
)

shop_items = [
    {'title': 'All Products', 'url': '/products/', 'order': 1},
    {'title': 'New Arrivals', 'url': '/products/?sort=newest', 'order': 2},
    {'title': 'Bestsellers', 'url': '/products/?sort=bestsellers', 'order': 3},
    {'title': 'Deals', 'url': '/products/?deals=true', 'order': 4},
    {'title': 'Manufacturers', 'url': '/manufacturers/', 'order': 5},
    {'title': 'Vendors', 'url': '/vendors/', 'order': 6},
]

for item in shop_items:
    FooterMenuItem.objects.create(
        category=shop,
        title=item['title'],
        url=item['url'],
        display_order=item['order'],
        is_active=True
    )
print("✓ Created Shop menu with 6 items")

# Create Support menu
support = FooterMenuCategory.objects.create(
    name='Support',
    slug='support',
    display_order=2,
    is_active=True
)

support_items = [
    {'title': 'Help Center', 'url': '/help/', 'order': 1},
    {'title': 'Track Order', 'url': '/orders/track/', 'order': 2},
    {'title': 'Returns Policy', 'url': '/returns/', 'order': 3},
    {'title': 'Shipping Info', 'url': '/shipping/', 'order': 4},
    {'title': 'FAQ', 'url': '/faq/', 'order': 5},
    {'title': 'Contact Us', 'url': '/contact/', 'order': 6},
]

for item in support_items:
    FooterMenuItem.objects.create(
        category=support,
        title=item['title'],
        url=item['url'],
        display_order=item['order'],
        is_active=True
    )
print("✓ Created Support menu with 6 items")

# Create Company menu
company = FooterMenuCategory.objects.create(
    name='Company',
    slug='company',
    display_order=3,
    is_active=True
)

company_items = [
    {'title': 'About Us', 'url': '/about/', 'order': 1},
    {'title': 'Privacy Policy', 'url': '/privacy/', 'order': 2},
    {'title': 'Terms of Service', 'url': '/terms/', 'order': 3},
    {'title': 'Careers', 'url': '/careers/', 'order': 4},
    {'title': 'Blog', 'url': '/blog/', 'order': 5},
    {'title': 'Sitemap', 'url': '/sitemap/', 'order': 6},
]

for item in company_items:
    FooterMenuItem.objects.create(
        category=company,
        title=item['title'],
        url=item['url'],
        display_order=item['order'],
        is_active=True
    )
print("✓ Created Company menu with 6 items")

print("\n" + "=" * 50)
print("✅ FOOTER SETUP COMPLETE!")
print("=" * 50)
print(f"Total categories: {FooterMenuCategory.objects.count()}")
print(f"Total menu items: {FooterMenuItem.objects.count()}")
print("\n📍 Admin URLs:")
print("   Categories: /admin/footer_menu/footermenucategory/")
print("   Menu Items: /admin/footer_menu/footermenuitem/")
