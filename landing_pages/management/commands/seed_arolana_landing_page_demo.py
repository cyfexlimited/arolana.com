from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from landing_pages.models import (
    LandingPage,
    LandingPageBenefit,
    LandingPageCTA,
    LandingPageCategoryCard,
    LandingPageComparisonItem,
    LandingPageContactOption,
    LandingPageFAQ,
    LandingPageOffer,
    LandingPageSection,
    LandingPageStep,
    LandingPageTestimonial,
    LandingPageVideoGuide,
)


DEMO_SLUG = "arolana-flexible-payment"
DEMO_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class Command(BaseCommand):
    help = "Seed a complete demo Arolana Landing Page Builder page with rich test content."

    def handle(self, *args, **options):
        with transaction.atomic():
            page = self.create_page()
            sections = self.create_sections(page)
            self.create_benefits(page, sections)
            self.create_offers(page, sections)
            self.create_steps(page, sections)
            self.create_category_cards(page, sections)
            self.create_comparison(page, sections)
            self.create_testimonials(page, sections)
            self.create_faqs(page, sections)
            self.create_contacts(page)
            self.create_ctas(page, sections)
            self.create_video_guides(page, sections)

        site_url = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
        public_path = page.get_absolute_url()
        admin_path = reverse("admin:landing_pages_landingpage_change", args=[page.pk])

        self.stdout.write(self.style.SUCCESS("Arolana landing page demo seeded successfully."))
        self.stdout.write(f"Live URL: http://localhost:8000{public_path}")
        self.stdout.write(f"Configured SITE_URL: {site_url}{public_path}")
        self.stdout.write(f"Admin edit URL: http://localhost:8000{admin_path}")

    def create_page(self):
        page, created = LandingPage.objects.update_or_create(
            slug=DEMO_SLUG,
            defaults={
                "title": "Arolana Flexible Payment & Business Equipment Financing",
                "subtitle": "Flexible purchase support for selected products and business equipment.",
                "page_type": LandingPage.PAGE_FLEXIBLE_PAYMENT,
                "status": LandingPage.STATUS_PUBLISHED,
                "is_active": True,
                "is_featured": True,
                "show_on_homepage": True,
                "show_in_nav": True,
                "navigation_label": "Flexible Payment",
                "hero_badge_text": "Business Purchase Support",
                "hero_headline": "Buy What Your Business Needs Today. Pay Smarter Over Time.",
                "hero_subheadline": (
                    "Arolana Flexible Payment helps businesses, installers, schools, offices, "
                    "churches, and individuals access essential equipment without delaying important projects."
                ),
                "hero_overlay_opacity": "0.58",
                "primary_cta_text": "Apply Now",
                "primary_cta_url": "#contact",
                "secondary_cta_text": "Shop Eligible Products",
                "secondary_cta_url": "#eligible-products",
                "trust_badges": [
                    "Fast Review",
                    "Secure Application",
                    "Business Friendly",
                    "Selected Products Only",
                ],
                "primary_color": "#2563EB",
                "accent_color": "#F97316",
                "dark_color": "#0F172A",
                "background_color": "#F8FAFC",
                "text_color": "#0F172A",
                "meta_title": "Arolana Flexible Payment & Business Equipment Financing",
                "meta_description": (
                    "Apply for Arolana flexible payment support for solar, CCTV, audio visual, "
                    "smart home, gaming, office, and electrical equipment."
                ),
                "meta_keywords": (
                    "Arolana flexible payment, business equipment financing, solar financing, "
                    "CCTV installation support, bulk buying, vendor credit, pay later, "
                    "equipment financing Nigeria, Arolana"
                ),
                "og_title": "Arolana Flexible Payment & Business Equipment Financing",
                "og_description": (
                    "Request flexible support for selected Arolana business, installation, "
                    "office, solar, CCTV, and technology purchases."
                ),
                "canonical_url": "https://arolana.com/arolana-flexible-payment/",
                "schema_markup": {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": "Arolana Flexible Payment & Business Equipment Financing",
                    "description": "Flexible payment support for selected Arolana products and business equipment.",
                    "url": "https://arolana.com/arolana-flexible-payment/",
                },
                "published_at": timezone.now(),
            },
        )
        self.assign_image_if_exists(page, "hero_background_image", "landing_pages/demo/hero-financing.jpg")
        self.assign_image_if_exists(page, "og_image", "landing_pages/demo/business-equipment.jpg")
        if created:
            self.stdout.write("Created demo landing page.")
        else:
            self.stdout.write("Updated demo landing page.")
        return page

    def create_sections(self, page):
        section_data = [
            (LandingPageSection.SECTION_BENEFITS, "Benefits Built for Better Buying", "Practical support for larger purchases and project planning.", 10),
            (LandingPageSection.SECTION_OFFERS, "Current Flexible Purchase Offers", "Selected deals and business support opportunities.", 20),
            (LandingPageSection.SECTION_HOW_IT_WORKS, "How Arolana Flexible Payment Works", "A simple request, review, and purchase support process.", 30),
            (LandingPageSection.SECTION_ELIGIBLE_CATEGORIES, "Eligible Product Categories", "Useful categories for business, installation, school, office, and home projects.", 40),
            (LandingPageSection.SECTION_VIDEO_GUIDES, "Other How-To Guides", "Short guides to help customers understand the flexible payment process.", 50),
            (LandingPageSection.SECTION_COMPARISON, "A Better Way to Plan Important Purchases", "Move from delay and compromise to clearer purchase support.", 60),
            (LandingPageSection.SECTION_TESTIMONIALS, "What Customers Say", "Realistic feedback from the types of customers this page supports.", 70),
            (LandingPageSection.SECTION_FAQ, "Frequently Asked Questions", "Clear answers before customers apply.", 80),
            (LandingPageSection.SECTION_CONTACT, "Start Your Request", "Speak with Arolana for product and purchase support.", 90),
            (
                LandingPageSection.SECTION_TERMS,
                "Important Terms",
                "",
                100,
            ),
        ]
        sections = {}
        for section_type, title, subtitle, sort_order in section_data:
            defaults = {
                "title": title,
                "subtitle": subtitle,
                "sort_order": sort_order,
                "is_active": True,
            }
            if section_type == LandingPageSection.SECTION_ELIGIBLE_CATEGORIES:
                defaults["extra_data"] = {"anchor": "eligible-products"}
            if section_type == LandingPageSection.SECTION_TERMS:
                defaults["content"] = (
                    "Flexible payment, financing, and business support requests are subject to review, "
                    "product availability, eligibility, vendor approval, payment terms, delivery location, "
                    "and Arolana's internal policies. Offers may change without prior notice. Arolana "
                    "reserves the right to approve, decline, or modify requests."
                )
            section, _ = LandingPageSection.objects.update_or_create(
                landing_page=page,
                section_type=section_type,
                defaults=defaults,
            )
            sections[section_type] = section
        return sections

    def create_benefits(self, page, sections):
        benefits = [
            ("fa-solid fa-wallet", "Pay Smarter for Big Purchases", "Spread selected product purchases with a more flexible buying process."),
            ("fa-solid fa-briefcase", "Access Business Equipment Faster", "Move important projects forward without waiting too long."),
            ("fa-solid fa-screwdriver-wrench", "Perfect for Installers and Contractors", "Useful for CCTV, solar, electrical, smart home, and audio visual installers."),
            ("fa-solid fa-building", "Support for Schools, Churches, and Offices", "Get equipment for classrooms, halls, offices, and business environments."),
            ("fa-solid fa-layer-group", "Works with Selected Product Categories", "Eligible categories include Solar, Surveillance, Audio Visual, Smart Home, Gaming, and Electricals."),
            ("fa-solid fa-circle-check", "Transparent Request Process", "Submit your request, get reviewed, and receive clear next steps."),
        ]
        for sort_order, (icon, title, description) in enumerate(benefits, start=1):
            LandingPageBenefit.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_BENEFITS],
                    "icon": icon,
                    "description": description,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_offers(self, page, sections):
        offers = [
            ("fa-solid fa-percent", "0% Service Fee on Selected Bulk Orders", "Limited Time", "Available on selected categories and approved bulk purchase requests.", "landing_pages/demo/business-equipment.jpg"),
            ("fa-solid fa-solar-panel", "Solar & Inverter Project Support", "Project Support", "Get guided purchase support for homes, offices, shops, and small businesses.", "landing_pages/demo/solar-support.jpg"),
            ("fa-solid fa-video", "CCTV & Security Installation Deals", "Security Bundle", "Bundle cameras, storage, cables, power supplies, and accessories with flexible purchase support.", "landing_pages/demo/cctv-support.jpg"),
        ]
        for sort_order, (icon, title, label, description, image_path) in enumerate(offers, start=1):
            offer, _ = LandingPageOffer.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_OFFERS],
                    "icon": icon,
                    "offer_label": label,
                    "description": description,
                    "button_text": "View Offer",
                    "button_url": "#contact",
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            self.assign_image_if_exists(offer, "image", image_path)

    def create_steps(self, page, sections):
        steps = [
            (1, "fa-solid fa-cart-shopping", "Choose Eligible Products", "Select products from approved categories such as Solar & Inverters, Surveillance, Audio Visual, Smart Home, Electricals, Gaming, and Office Technology."),
            (2, "fa-solid fa-file-signature", "Submit Your Request", "Send your details, preferred products, quantity, delivery location, and payment plan request."),
            (3, "fa-solid fa-magnifying-glass-chart", "Get Reviewed", "Our team reviews the request and confirms availability, pricing, delivery, and approval status."),
            (4, "fa-solid fa-truck-fast", "Complete Your Purchase", "Once approved, complete the required payment and receive your products with proper tracking and support."),
        ]
        for sort_order, (number, icon, title, description) in enumerate(steps, start=1):
            LandingPageStep.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_HOW_IT_WORKS],
                    "step_number": number,
                    "icon": icon,
                    "description": description,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_category_cards(self, page, sections):
        cards = [
            ("fa-solid fa-solar-panel", "Solar & Inverters", "Power solutions for homes, offices, shops, and businesses.", "landing_pages/demo/solar-support.jpg"),
            ("fa-solid fa-video", "Surveillance & CCTV", "Cameras, DVRs, NVRs, cables, storage, and security bundles.", "landing_pages/demo/cctv-support.jpg"),
            ("fa-solid fa-tv", "Audio Visual Equipment", "Video conferencing, speakers, projectors, displays, and AV tools.", "landing_pages/demo/business-equipment.jpg"),
            ("fa-solid fa-microchip", "Smart Home Devices", "Smart locks, smart cameras, plugs, switches, and automation devices.", ""),
            ("fa-solid fa-tools", "Electrical Tools", "Professional tools for electricians, installers, and technicians.", ""),
            ("fa-solid fa-industry", "Industrial Electricals", "Electrical products for factories, workshops, and heavy-duty projects.", ""),
            ("fa-solid fa-gamepad", "Gaming Laptops & Consoles", "Gaming systems, laptops, monitors, accessories, and storage.", ""),
            ("fa-solid fa-building", "Office Technology", "Devices and equipment for offices, schools, and business spaces.", "landing_pages/demo/business-equipment.jpg"),
            ("fa-solid fa-bolt", "Power Protection", "UPS systems, stabilizers, surge protectors, and voltage protection.", ""),
            ("fa-solid fa-plug", "Cables & Wires", "Electrical, networking, CCTV, HDMI, USB, and installation cables.", ""),
            ("fa-solid fa-lightbulb", "Lighting Solutions", "LED lights, smart lighting, outdoor lighting, and commercial lighting.", ""),
            ("fa-solid fa-network-wired", "Networking & Routers", "Routers, switches, access points, and networking accessories.", ""),
        ]
        for sort_order, (icon, title, description, image_path) in enumerate(cards, start=1):
            card, _ = LandingPageCategoryCard.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_ELIGIBLE_CATEGORIES],
                    "icon": icon,
                    "description": description,
                    "button_text": "Explore",
                    "button_url": "#contact",
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            if image_path:
                self.assign_image_if_exists(card, "image", image_path)

    def create_comparison(self, page, sections):
        negative_items = [
            "Projects get delayed",
            "Cash flow becomes tight",
            "Customers postpone important upgrades",
            "Businesses settle for lower quality products",
        ]
        positive_items = [
            "Start important projects faster",
            "Spread purchase planning more easily",
            "Buy complete product bundles",
            "Access verified products from trusted vendors",
        ]
        for sort_order, title in enumerate(negative_items, start=1):
            LandingPageComparisonItem.objects.update_or_create(
                landing_page=page,
                side=LandingPageComparisonItem.SIDE_NEGATIVE,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_COMPARISON],
                    "icon": "fa-solid fa-xmark",
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
        for sort_order, title in enumerate(positive_items, start=1):
            LandingPageComparisonItem.objects.update_or_create(
                landing_page=page,
                side=LandingPageComparisonItem.SIDE_POSITIVE,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_COMPARISON],
                    "icon": "fa-solid fa-check",
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_testimonials(self, page, sections):
        testimonials = [
            ("Arolana makes it easier to plan equipment purchases without stopping business operations.", "Small Business Buyer", "Business Owner"),
            ("For CCTV, solar, and office equipment, having flexible purchase support can help projects move faster.", "Installation Contractor", "CCTV & Solar Installer"),
            ("The process is clear, product-focused, and useful for customers buying more than one item.", "Corporate Customer", "Office Procurement Manager"),
        ]
        for sort_order, (quote, name, title) in enumerate(testimonials, start=1):
            testimonial, _ = LandingPageTestimonial.objects.update_or_create(
                landing_page=page,
                customer_name=name,
                defaults={
                    "section": sections[LandingPageSection.SECTION_TESTIMONIALS],
                    "quote": quote,
                    "customer_title": title,
                    "rating": 5,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            self.assign_image_if_exists(testimonial, "image", "landing_pages/demo/business-equipment.jpg")

    def create_faqs(self, page, sections):
        faqs = [
            ("What is Arolana Flexible Payment?", "It is a purchase support page that helps eligible customers request flexible payment or business equipment financing for selected products and categories."),
            ("Is approval automatic?", "No. Every request must be reviewed based on product availability, customer details, payment plan, location, and Arolana's approval process."),
            ("What products are eligible?", "Eligible products may include Solar & Inverters, Surveillance, Audio Visual, Smart Home, Electricals, Gaming, Office Technology, Power Protection, and selected business equipment."),
            ("Can businesses and installers apply?", "Yes. The page is designed for individuals, businesses, installers, schools, offices, churches, contractors, and organizations that need equipment support."),
            ("Do all products qualify?", "No. Only selected products, vendors, and categories may qualify."),
            ("How do I apply?", "Click Apply Now, fill the request form, select your products, and wait for review."),
        ]
        for sort_order, (question, answer) in enumerate(faqs, start=1):
            LandingPageFAQ.objects.update_or_create(
                landing_page=page,
                question=question,
                defaults={
                    "section": sections[LandingPageSection.SECTION_FAQ],
                    "answer": answer,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_contacts(self, page):
        contacts = [
            ("fa-solid fa-phone", "Phone", "+2349132924620", "tel:+2349132924620"),
            ("fa-solid fa-phone", "Phone", "+2349033713922", "tel:+2349033713922"),
            ("fa-solid fa-envelope", "Email", "Cyfexlimited8@gmail.com", "mailto:Cyfexlimited8@gmail.com"),
            ("fa-brands fa-whatsapp", "WhatsApp", "Chat on WhatsApp", "https://wa.me/2349132924620"),
        ]
        for sort_order, (icon, label, value, url) in enumerate(contacts, start=1):
            LandingPageContactOption.objects.update_or_create(
                landing_page=page,
                label=label,
                value=value,
                defaults={
                    "icon": icon,
                    "url": url,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_ctas(self, page, sections):
        ctas = [
            (sections[LandingPageSection.SECTION_CONTACT], "Call Arolana", "tel:+2349132924620", LandingPageCTA.STYLE_PRIMARY, "fa-solid fa-phone", 1),
            (sections[LandingPageSection.SECTION_CONTACT], "Chat on WhatsApp", "https://wa.me/2349132924620", LandingPageCTA.STYLE_SECONDARY, "fa-brands fa-whatsapp", 2),
        ]
        for section, label, url, style, icon, sort_order in ctas:
            LandingPageCTA.objects.update_or_create(
                landing_page=page,
                label=label,
                defaults={
                    "section": section,
                    "url": url,
                    "style": style,
                    "open_behavior": LandingPageCTA.OPEN_SAME_PAGE,
                    "icon": icon,
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )

    def create_video_guides(self, page, sections):
        videos = [
            (
                "How to Apply for Arolana Flexible Payment",
                "Application Guide",
                "1:15",
                "Learn how to submit your request and choose eligible products.",
                "landing_pages/demo/video-apply.jpg",
            ),
            (
                "How to Choose Eligible Equipment",
                "Product Selection Guide",
                "1:55",
                "See how to select products from approved categories.",
                "landing_pages/demo/video-equipment.jpg",
            ),
            (
                "How Business Purchase Support Works",
                "Business Support Guide",
                "2:05",
                "Understand review, approval, payment, and delivery steps.",
                "landing_pages/demo/video-business.jpg",
            ),
        ]
        for sort_order, (title, subtitle, duration, description, thumbnail_path) in enumerate(videos, start=1):
            guide, _ = LandingPageVideoGuide.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": sections[LandingPageSection.SECTION_VIDEO_GUIDES],
                    "subtitle": subtitle,
                    "description": description,
                    "video_url": DEMO_VIDEO_URL,
                    "platform": LandingPageVideoGuide.PLATFORM_YOUTUBE,
                    "duration": duration,
                    "button_text": "Watch Video",
                    "sort_order": sort_order,
                    "is_active": True,
                },
            )
            self.assign_image_if_exists(guide, "thumbnail", thumbnail_path)

    def assign_image_if_exists(self, obj, field_name, relative_path):
        source = self.find_demo_image(relative_path)
        if not source:
            return False

        current_file = getattr(obj, field_name)
        if current_file and Path(current_file.name).name == source.name:
            return True

        with source.open("rb") as handle:
            getattr(obj, field_name).save(source.name, File(handle), save=True)
        return True

    def find_demo_image(self, relative_path):
        candidates = []
        media_root = getattr(settings, "MEDIA_ROOT", None)
        if media_root:
            candidates.append(Path(media_root) / relative_path)
        for static_dir in getattr(settings, "STATICFILES_DIRS", []):
            candidates.append(Path(static_dir) / relative_path)
        candidates.append(Path(settings.BASE_DIR) / "landing_pages" / "static" / relative_path)
        candidates.append(Path(settings.BASE_DIR) / "static" / relative_path)

        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None
