from django.core.management.base import BaseCommand
from django.utils import timezone

from landing_pages.models import (
    LandingPage,
    LandingPageBenefit,
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


class Command(BaseCommand):
    help = "Create the sample Arolana Flexible Payment landing page."

    def handle(self, *args, **options):
        page, _created = LandingPage.objects.update_or_create(
            slug="arolana-flexible-payment",
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
                "hero_subheadline": "Arolana Flexible Payment helps businesses, installers, schools, offices, churches, and individuals access essential equipment without delaying important projects.",
                "primary_cta_text": "Apply Now",
                "primary_cta_url": "#contact",
                "secondary_cta_text": "Shop Eligible Products",
                "secondary_cta_url": "#categories",
                "trust_badges": ["Fast Review", "Secure Application", "Business Friendly", "Selected Products Only"],
                "meta_title": "Arolana Flexible Payment & Business Equipment Financing",
                "meta_description": "Request flexible payment or business equipment financing support for selected Arolana products and categories.",
                "published_at": timezone.now(),
            },
        )

        sections = {
            "benefits": ("Benefits built for better buying", "Practical support for larger purchases and project planning."),
            "offers": ("Current flexible purchase offers", "Selected deals and business support opportunities."),
            "how_it_works": ("How Arolana Flexible Payment works", "A simple request, review, and purchase support process."),
            "eligible_categories": ("Eligible product categories", "Useful categories for business, installation, school, office, and home projects."),
            "video_guides": ("Other How-To Guides", "Short guides to help customers understand the flexible payment process."),
            "comparison": ("A better way to plan important purchases", "Move from delay and compromise to clearer purchase support."),
            "testimonials": ("What customers say", ""),
            "faq": ("Frequently asked questions", ""),
            "contact": ("Start your request", "Speak with Arolana for product and purchase support."),
            "terms": ("Important terms", "Flexible payment, financing, and business support requests are subject to review, product availability, eligibility, vendor approval, payment terms, delivery location, and Arolana’s internal policies. Offers may change without prior notice. Arolana reserves the right to approve, decline, or modify requests."),
        }
        section_objects = {}
        for index, (section_type, (title, subtitle)) in enumerate(sections.items(), start=1):
            section_objects[section_type], _ = LandingPageSection.objects.update_or_create(
                landing_page=page,
                section_type=section_type,
                defaults={"title": title, "subtitle": subtitle, "sort_order": index * 10, "is_active": True},
            )

        benefits = [
            ("fas fa-wallet", "Pay smarter for big purchases", "Spread selected product purchases with a more flexible buying process."),
            ("fas fa-briefcase", "Access business equipment faster", "Move important projects forward without waiting too long."),
            ("fas fa-screwdriver-wrench", "Perfect for installers and contractors", "Useful for CCTV, solar, electrical, smart home, and audio visual installers."),
            ("fas fa-school", "Support for schools, churches, and offices", "Get equipment for classrooms, halls, offices, and business environments."),
            ("fas fa-layer-group", "Works with selected product categories", "Eligible categories include Solar, Surveillance, Audio Visual, Smart Home, Gaming, and Electricals."),
            ("fas fa-file-signature", "Transparent request process", "Submit your request, get reviewed, and receive clear next steps."),
        ]
        for order, (icon, title, description) in enumerate(benefits, start=1):
            LandingPageBenefit.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={"section": section_objects["benefits"], "icon": icon, "description": description, "sort_order": order, "is_active": True},
            )

        offers = [
            ("0% Service Fee on Selected Bulk Orders", "Available on selected categories and approved bulk purchase requests.", "View Offer"),
            ("Solar & Inverter Project Support", "Get guided purchase support for homes, offices, shops, and small businesses.", "View Offer"),
            ("CCTV & Security Installation Deals", "Bundle cameras, storage, cables, power supplies, and accessories with flexible purchase support.", "View Offer"),
        ]
        for order, (title, description, button) in enumerate(offers, start=1):
            LandingPageOffer.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={"section": section_objects["offers"], "description": description, "button_text": button, "button_url": "#contact", "offer_label": "Selected request", "sort_order": order, "is_active": True},
            )

        steps = [
            (1, "fas fa-cart-shopping", "Choose eligible products", "Select products from approved categories such as Solar & Inverters, Surveillance, Audio Visual, Smart Home, Electricals, Gaming, and Office Technology."),
            (2, "fas fa-paper-plane", "Submit your request", "Send your details, preferred products, quantity, delivery location, and payment plan request."),
            (3, "fas fa-clipboard-check", "Get reviewed", "Our team reviews the request and confirms availability, pricing, delivery, and approval status."),
            (4, "fas fa-box-open", "Complete your purchase", "Once approved, complete the required payment and receive your products with proper tracking and support."),
        ]
        for order, (number, icon, title, description) in enumerate(steps, start=1):
            LandingPageStep.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={"section": section_objects["how_it_works"], "step_number": number, "icon": icon, "description": description, "sort_order": order, "is_active": True},
            )

        categories = [
            "Solar & Inverters", "Surveillance & CCTV", "Audio Visual Equipment", "Smart Home Devices",
            "Electrical Tools", "Industrial Electricals", "Gaming Laptops & Consoles", "Office Technology",
            "Power Protection", "Networking & Routers", "Cables & Wires", "Lighting Solutions",
        ]
        for order, title in enumerate(categories, start=1):
            LandingPageCategoryCard.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={"section": section_objects["eligible_categories"], "description": "Explore selected products and request purchase support.", "button_text": "Explore", "button_url": "/products/", "sort_order": order, "is_active": True},
            )

        negative_items = ["Projects get delayed", "Cash flow becomes tight", "Customers postpone important upgrades", "Businesses settle for lower quality products"]
        positive_items = ["Start important projects faster", "Spread purchase planning more easily", "Buy complete product bundles", "Access verified products from trusted vendors"]
        for order, title in enumerate(negative_items, start=1):
            LandingPageComparisonItem.objects.update_or_create(
                landing_page=page,
                side=LandingPageComparisonItem.SIDE_NEGATIVE,
                title=title,
                defaults={"section": section_objects["comparison"], "sort_order": order, "is_active": True},
            )
        for order, title in enumerate(positive_items, start=1):
            LandingPageComparisonItem.objects.update_or_create(
                landing_page=page,
                side=LandingPageComparisonItem.SIDE_POSITIVE,
                title=title,
                defaults={"section": section_objects["comparison"], "sort_order": order, "is_active": True},
            )

        testimonials = [
            ("Arolana makes it easier to plan equipment purchases without stopping business operations.", "Small Business Buyer"),
            ("For CCTV, solar, and office equipment, having flexible purchase support can help projects move faster.", "Installation Contractor"),
            ("The process is clear, product-focused, and useful for customers buying more than one item.", "Corporate Customer"),
        ]
        for order, (quote, name) in enumerate(testimonials, start=1):
            LandingPageTestimonial.objects.update_or_create(
                landing_page=page,
                customer_name=name,
                defaults={"section": section_objects["testimonials"], "quote": quote, "rating": 5, "sort_order": order, "is_active": True},
            )

        faqs = [
            ("What is Arolana Flexible Payment?", "It is a purchase support page that helps eligible customers request flexible payment or business equipment financing for selected products and categories."),
            ("Is approval automatic?", "No. Every request must be reviewed based on product availability, customer details, payment plan, location, and Arolana’s approval process."),
            ("What products are eligible?", "Eligible products may include Solar & Inverters, Surveillance, Audio Visual, Smart Home, Electricals, Gaming, Office Technology, Power Protection, and selected business equipment."),
            ("Can businesses and installers apply?", "Yes. The page is designed for individuals, businesses, installers, schools, offices, churches, contractors, and organizations that need equipment support."),
            ("Do all products qualify?", "No. Only selected products, vendors, and categories may qualify."),
            ("How do I apply?", "Click Apply Now, fill the request form, select your products, and wait for review."),
        ]
        for order, (question, answer) in enumerate(faqs, start=1):
            LandingPageFAQ.objects.update_or_create(
                landing_page=page,
                question=question,
                defaults={"section": section_objects["faq"], "answer": answer, "sort_order": order, "is_active": True},
            )

        contacts = [
            ("fas fa-phone", "Phone", "+2349132924620", "tel:+2349132924620"),
            ("fas fa-phone", "Phone", "+2349033713922", "tel:+2349033713922"),
            ("fas fa-envelope", "Email", "Cyfexlimited8@gmail.com", "mailto:Cyfexlimited8@gmail.com"),
            ("fab fa-whatsapp", "WhatsApp", "Chat on WhatsApp", "https://wa.me/2349132924620"),
        ]
        for order, (icon, label, value, url) in enumerate(contacts, start=1):
            LandingPageContactOption.objects.update_or_create(
                landing_page=page,
                label=label,
                value=value,
                defaults={"icon": icon, "url": url, "sort_order": order, "is_active": True},
            )

        videos = [
            ("How to Apply for Arolana Flexible Payment", "1:15", "Learn how to submit your request and choose eligible products."),
            ("How to Choose Eligible Equipment", "1:55", "See how to select products from approved categories."),
            ("How Business Purchase Support Works", "2:05", "Understand review, approval, payment, and delivery steps."),
        ]
        for order, (title, duration, description) in enumerate(videos, start=1):
            LandingPageVideoGuide.objects.update_or_create(
                landing_page=page,
                title=title,
                defaults={
                    "section": section_objects["video_guides"],
                    "description": description,
                    "duration": duration,
                    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "platform": LandingPageVideoGuide.PLATFORM_YOUTUBE,
                    "sort_order": order,
                    "is_active": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(f"Sample landing page ready: {page.get_absolute_url()}"))
