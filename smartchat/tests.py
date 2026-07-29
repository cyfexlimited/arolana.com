import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from notifications.models import Notification
from products.models import Brand, Category, Product, ProductQuestion, ProductReview
from ai_core.commerce_tools import search_products
from .ai_manager import create_managed_ai_message
from .context_state import extract_facts, prepare_context
from .intent_guards import (
    CONVERSATIONAL_GOODBYE,
    CONVERSATIONAL_GRATITUDE,
    CONVERSATIONAL_GREETING,
    CONVERSATIONAL_IDENTITY,
    CONVERSATIONAL_WELLBEING,
    ORDER_INTENT,
    REQUIREMENTS_INTENT,
    SUPPORT_INTENT,
    clean_product_search_query,
    resolve_customer_intent,
)
from .models import (
    AICategoryRouterLog,
    AICustomerMemory,
    AIIntentLog,
    AIKnowledgeBase,
    AILearnedKnowledge,
    HumanTakeoverRequest,
    SmartChatConversation,
    SmartChatMessage,
)


User = get_user_model()


class SmartChatIntentGuardTests(SimpleTestCase):
    def test_conversational_messages_are_not_product_searches(self):
        cases = {
            "hello": CONVERSATIONAL_GREETING,
            "Hi!": CONVERSATIONAL_GREETING,
            "good morning": CONVERSATIONAL_GREETING,
            "how are you today?": CONVERSATIONAL_WELLBEING,
            "who are you?": CONVERSATIONAL_IDENTITY,
            "what can you do?": CONVERSATIONAL_IDENTITY,
            "thank you": CONVERSATIONAL_GRATITUDE,
            "bye": CONVERSATIONAL_GOODBYE,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(resolve_customer_intent(message), expected)

    def test_shopping_and_operational_intents_are_distinct(self):
        cases = {
            "do you have Logitech Group?": "catalog.search_products",
            "Logitech Rally Bar price": "catalog.search_products",
            "show me projectors": "catalog.search_products",
            "I need a projector for a church": REQUIREMENTS_INTENT,
            "track my order": ORDER_INTENT,
            "I need an installer": "services.match_providers",
            "contact support": SUPPORT_INTENT,
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(resolve_customer_intent(message), expected)

    def test_short_substrings_do_not_trigger_greetings(self):
        for message in (
            "shipping price",
            "white projector",
            "this product",
            "high-quality speaker",
        ):
            with self.subTest(message=message):
                self.assertNotEqual(resolve_customer_intent(message), CONVERSATIONAL_GREETING)

    def test_product_query_cleaning_preserves_model_terms(self):
        self.assertEqual(clean_product_search_query("Do you have Logitech Group?"), "Logitech Group")
        self.assertEqual(clean_product_search_query("How much is Logitech C920?"), "Logitech C920")
        self.assertEqual(clean_product_search_query("Epson EB-L630U"), "Epson EB-L630U")
        self.assertEqual(clean_product_search_query("Jabra Speak 810 MS"), "Jabra Speak 810 MS")
        self.assertEqual(clean_product_search_query("120-inch motorised screen"), "120-inch motorised screen")


@override_settings(SECURE_SSL_REDIRECT=False)
class SmartChatAdminNotificationTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password123",
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="password123",
        )

    def post_json(self, url_name, payload):
        return self.client.post(
            reverse(url_name),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_guest_contact_creates_staff_notification(self):
        response = self.post_json(
            "smartchat:api_guest_contact",
            {
                "first_name": "Ada",
                "last_name": "Guest",
                "email": "ada@example.com",
                "message": "I need help before buying.",
                "page_url": "https://arolana.com/products/test/",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

        notification = Notification.objects.get(user=self.staff_user)
        self.assertEqual(notification.title, "New Arolana guest chat")
        self.assertEqual(notification.notification_type, "message")
        self.assertEqual(notification.metadata["smartchat_conversation_id"], data["conversation_id"])
        self.assertEqual(notification.metadata["customer_email"], "ada@example.com")

    def test_customer_message_after_handoff_notifies_assigned_admin_only(self):
        other_staff = User.objects.create_user(
            username="otheradmin",
            email="otheradmin@example.com",
            password="password123",
            is_staff=True,
        )
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            assigned_admin=self.staff_user,
            status=SmartChatConversation.STATUS_ADMIN_ACTIVE,
            customer_name="Customer One",
            customer_email=self.customer.email,
            title="Product support",
        )
        self.client.force_login(self.customer)

        response = self.post_json(
            "smartchat:api_message",
            {
                "conversation_id": conversation.id,
                "message": "Can an admin confirm delivery today?",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["admin_only"])

        notification = Notification.objects.get(user=self.staff_user)
        self.assertEqual(notification.title, "New Arolana Chat message")
        self.assertEqual(notification.metadata["smartchat_conversation_id"], conversation.id)
        self.assertEqual(notification.metadata["event"], "customer_message")
        self.assertFalse(Notification.objects.filter(user=other_staff).exists())


@override_settings(
    AI_CORE_ENABLED=True,
    AI_TOOL_EXECUTION_ENABLED=True,
    AI_SMART_SHOPPING_ENABLED=True,
    AI_EXTERNAL_PROVIDER_ENABLED=False,
    OPENAI_API_KEY="",
    SECURE_SSL_REDIRECT=False,
)
class SmartChatEndToEndRoutingTests(TestCase):
    def send(self, conversation, text, user=None):
        message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_USER,
            user=user,
            message=text,
        )
        return create_managed_ai_message(conversation, message, user)

    def test_greeting_is_deterministic_for_guest_and_does_not_search(self):
        conversation = SmartChatConversation.objects.create()

        reply = self.send(conversation, "Hello")

        self.assertEqual(
            reply.message,
            "Hello! Welcome to Arolana. I can help you find and compare products, "
            "track an order, locate an installer or connect you with Arolana support. "
            "What are you looking for today?",
        )
        self.assertEqual(reply.source_type, "deterministic_conversation")
        self.assertEqual(reply.metadata["intent"], CONVERSATIONAL_GREETING)
        self.assertNotIn("product_cards", reply.metadata)
        conversation.refresh_from_db()
        state = conversation.context.get("state", {})
        self.assertNotIn(state.get("active_subject"), {"hello", "general_marketplace"})

    def test_empty_catalog_response_and_duplicate_repeat_stay_honest(self):
        conversation = SmartChatConversation.objects.create()

        first = self.send(conversation, "Do you have Logitech Group?")
        second = self.send(conversation, "Do you have Logitech Group?")

        for reply in (first, second):
            self.assertEqual(reply.source_type, "catalog_empty_result")
            self.assertEqual(reply.metadata["result_count"], 0)
            self.assertEqual(reply.metadata["search_query"], "Logitech Group")
            self.assertIn("Logitech Group", reply.message)
            self.assertNotIn("general_marketplace", reply.message)
            self.assertNotIn("I’ve kept your requirements", reply.message)
        self.assertEqual(second.metadata["duplicate_check"], "skipped")
        self.assertEqual(second.metadata["duplicate_skip_reason"], "source_type:catalog_empty_result")

    def test_non_catalog_marketplace_domains_do_not_fall_back_to_random_products(self):
        vendor = User.objects.create_user(
            username="route-av-vendor",
            email="route-av-vendor@example.com",
            password="password123",
        )
        category = Category.objects.create(name="Projectors", slug="route-projectors")
        Product.objects.create(
            vendor=vendor,
            category=category,
            sku="ROUTE-PROJECTOR",
            name="Bright Room Projector",
            slug="bright-room-projector-route",
            description="A projector for meeting rooms.",
            price="410000.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=True,
        )

        cases = (
            ("I need a two-bedroom apartment in Ikeja under ₦4 million yearly.", "property"),
            ("I want to rent a bus for twenty people next Saturday.", "rental"),
            ("I need accounting software for fifteen staff members.", "software"),
        )
        for message, expected_word in cases:
            with self.subTest(message=message):
                conversation = SmartChatConversation.objects.create()
                reply = self.send(conversation, message)

                self.assertNotIn("Matching approved Arolana products", reply.message)
                self.assertNotIn("Bright Room Projector", reply.message)
                self.assertNotIn("Projectors", reply.message)
                self.assertIn(expected_word, reply.message.lower())
                self.assertEqual(reply.metadata.get("tool_name"), "none")
                self.assertEqual(
                    reply.metadata.get("fallback_reason"),
                    "catalog_search_not_allowed_for_active_workflow",
                )

    def test_installer_request_and_help_followup_stay_in_service_workflow(self):
        conversation = SmartChatConversation.objects.create()

        installer = self.send(conversation, "i need an installer")

        self.assertNotIn("active approved an installer match", installer.message)
        self.assertNotIn("live Arolana catalogue", installer.message)
        self.assertIn("service provider", installer.message.lower())
        self.assertIn("what you need installed", installer.message.lower())

        help_reply = self.send(conversation, "please do help me")

        self.assertNotIn("What would you like help with", help_reply.message)
        self.assertNotIn("live Arolana catalogue", help_reply.message)
        self.assertIn("service", help_reply.message.lower())

    def test_asset_specific_installer_request_stays_in_provider_workflow(self):
        conversation = SmartChatConversation.objects.create()

        reply = self.send(conversation, "Find a CCTV installer in Abuja.")
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}

        self.assertEqual(reply.metadata.get("intent"), "services.match_providers")
        self.assertNotEqual(reply.metadata.get("source_type"), "conversation_router")
        self.assertNotIn("small room", reply.message.lower())
        self.assertNotIn("boardroom", reply.message.lower())
        self.assertNotIn("what is your budget", reply.message.lower())
        self.assertIn("provider", reply.message.lower())
        self.assertEqual(state.get("intent_family"), "service")
        self.assertEqual(state.get("transaction_type"), "find_provider")
        self.assertIn("cctv", state.get("active_subject", "").lower())
        self.assertEqual(
            (state.get("requirements") or {}).get("service_location"),
            "Abuja",
        )

    def test_installer_conference_room_followups_never_switch_to_products(self):
        conversation = SmartChatConversation.objects.create()

        reply_1 = self.send(conversation, "I'm looking for an installer in Lagos")
        reply_2 = self.send(
            conversation,
            "I want to do a setup for a conference room of 20 sitters",
        )
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(state.get("intent_family"), "service")
        self.assertEqual(requirements.get("service_location"), "Lagos")
        self.assertEqual(requirements.get("capacity"), 20)
        self.assertFalse((reply_2.metadata or {}).get("product_cards"))
        self.assertNotIn("Approved Arolana products found", reply_2.message)

        reply_3 = self.send(
            conversation,
            "I mean I need an installer that would install it for me",
        )
        reply_4 = self.send(
            conversation,
            "conferencing and location is in Lekki",
        )
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(state.get("intent_family"), "service")
        self.assertIn("conference", str(requirements.get("service_type", "")))
        self.assertEqual(requirements.get("service_location"), "Lekki")
        self.assertFalse((reply_3.metadata or {}).get("product_cards"))
        self.assertFalse((reply_4.metadata or {}).get("product_cards"))

        reply_5 = self.send(conversation, "but I need it urgently")
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(requirements.get("urgency"), "urgent")
        self.assertFalse((reply_5.metadata or {}).get("product_cards"))
        self.assertNotIn("Approved Arolana products found", reply_5.message)

    def test_installer_equipment_date_and_casual_followups_do_not_switch_to_products(self):
        conversation = SmartChatConversation.objects.create()

        self.send(conversation, "I'm looking for an installer in Lagos")

        casual = self.send(conversation, "how are you today?")
        self.assertEqual(casual.source_type, "deterministic_conversation")
        self.assertEqual(casual.metadata.get("intent"), CONVERSATIONAL_WELLBEING)
        self.assertNotIn("installer", casual.message.lower())
        self.assertNotIn("conference room", casual.message.lower())

        self.send(conversation, "ikeja")
        install_request = self.send(
            conversation,
            "tomorrow, and i need to install logitech rally bar",
        )
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(state.get("intent_family"), "service")
        self.assertEqual(requirements.get("service_location"), "Ikeja")
        self.assertEqual(requirements.get("preferred_date"), "tomorrow")
        self.assertIn("logitech rally bar", str(requirements.get("equipment_to_install", "")).lower())
        self.assertFalse((install_request.metadata or {}).get("product_cards"))
        self.assertNotIn("Approved Arolana products found", install_request.message)

        bare_equipment = self.send(conversation, "logitech rally bar")
        room_size = self.send(conversation, "for a 20 sitters conference room")
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(requirements.get("capacity"), 20)
        self.assertIn("conference", str(requirements.get("service_type", "")))
        self.assertIn("logitech rally bar", str(requirements.get("equipment_to_install", "")).lower())
        self.assertFalse((bare_equipment.metadata or {}).get("product_cards"))
        self.assertFalse((room_size.metadata or {}).get("product_cards"))
        self.assertNotIn("Approved Arolana products found", bare_equipment.message)
        self.assertNotIn("Approved Arolana products found", room_size.message)

    def test_product_query_returns_only_active_approved_product(self):
        vendor = User.objects.create_user(
            username="route-vendor",
            email="route-vendor@example.com",
            password="password123",
        )
        category = Category.objects.create(name="Conference Cameras", slug="conference-cameras")
        brand = Brand.objects.create(name="Logitech", slug="logitech-route")
        product = Product.objects.create(
            vendor=vendor,
            category=category,
            brand=brand,
            sku="LOGI-GROUP-ROUTE",
            name="Logitech Group",
            slug="logitech-group-route",
            description="Video conferencing camera and speakerphone.",
            price="980000.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=True,
        )
        Product.objects.create(
            vendor=vendor,
            category=category,
            brand=brand,
            sku="LOGI-GROUP-PENDING",
            name="Logitech Group Pending",
            slug="logitech-group-pending",
            description="Pending product.",
            price="1.00",
            stock_quantity=3,
            approval_status="pending",
            is_active=True,
        )
        Product.objects.create(
            vendor=vendor,
            category=category,
            brand=brand,
            sku="LOGI-GROUP-INACTIVE",
            name="Logitech Group Inactive",
            slug="logitech-group-inactive",
            description="Inactive product.",
            price="1.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=False,
        )
        conversation = SmartChatConversation.objects.create()

        reply = self.send(conversation, "Do you have Logitech Group?")

        self.assertEqual(reply.metadata["intent"], "catalog.search_products")
        self.assertEqual(reply.metadata["result_count"], 1)
        self.assertIn(product.name, reply.message)
        self.assertIn(product.slug, reply.metadata["structured_response"]["products"][0]["public_url"])
        self.assertEqual(reply.metadata["structured_response"]["products"][0]["public_ref"], product.slug)

    def test_requirement_continuation_and_topic_change_are_isolated(self):
        conversation = SmartChatConversation.objects.create()

        first = self.send(conversation, "I need a projector for a church")
        self.assertEqual(first.source_type, "clarification")
        self.assertIn("budget", first.message.lower())

        budget = self.send(conversation, "My budget is ₦1.5 million")
        self.assertNotEqual(budget.source_type, "catalog_empty_result")

        search = self.send(conversation, "Do you have Logitech Group?")
        conversation.refresh_from_db()
        self.assertEqual(search.source_type, "catalog_empty_result")
        self.assertEqual(conversation.context["state"]["active_subject"], "Logitech Group")
        self.assertEqual(conversation.context["state"].get("requirements"), {})

    def test_projector_shopping_session_freezes_category_through_slot_filling(self):
        vendor = User.objects.create_user(
            username="projector-vendor",
            email="projector-vendor@example.com",
            password="password123",
        )
        projector_category = Category.objects.create(name="Projectors", slug="projectors")
        artwork_category = Category.objects.create(name="Artwork", slug="artwork")
        epson = Brand.objects.create(name="Epson", slug="epson")
        Brand.objects.create(name="Artwork House", slug="artwork-house")
        projector = Product.objects.create(
            vendor=vendor,
            category=projector_category,
            brand=epson,
            sku="EPSON-4000-LUMENS",
            name="Epson 4000 Lumens Full HD Projector",
            slug="epson-4000-lumens-full-hd-projector",
            description="A bright projector for boardrooms, schools and churches.",
            specifications="4000 lumens Full HD 1080p HDMI projector.",
            price="390000.00",
            stock_quantity=6,
            approval_status="approved",
            is_active=True,
            condition=Product.CONDITION_BRAND_NEW,
        )
        Product.objects.create(
            vendor=vendor,
            category=artwork_category,
            brand=None,
            sku="ARTWORK-001",
            name="Wall Artwork Canvas",
            slug="wall-artwork-canvas",
            description="Decorative wall art and canvas artwork.",
            specifications="Painting, sculpture and wall artwork.",
            price="200000.00",
            stock_quantity=4,
            approval_status="approved",
            is_active=True,
        )
        conversation = SmartChatConversation.objects.create()

        greeting = self.send(conversation, "hello")
        self.assertEqual(greeting.source_type, "deterministic_conversation")

        messages = [
            "do you have projector",
            "I'm looking for a 4000 lumens projector for about ₦300,000",
            "My budget is ₦400,000",
            "Lagos",
            "brand new",
            "Epson",
        ]
        replies = [self.send(conversation, message) for message in messages]

        conversation.refresh_from_db()
        state = conversation.context["state"]
        smart_state = conversation.context["smart_shopping"]
        requirements = state["requirements"]

        self.assertEqual(state["category"], "Projectors")
        self.assertEqual(state["product_type"], "Projectors")
        self.assertEqual(state["locked_category"], "Projectors")
        self.assertTrue(state["shopping_category_locked"])
        self.assertEqual(smart_state["category"], "Projectors")
        self.assertEqual(requirements["budget_max"], 400000)
        self.assertEqual(requirements["brightness_requirement"], 4000)
        self.assertEqual(requirements["delivery_location"], "Lagos")
        self.assertEqual(requirements["condition"], Product.CONDITION_BRAND_NEW)
        self.assertEqual(requirements["brand"], "Epson")
        self.assertEqual(state["brand"], "Epson")
        self.assertNotEqual(state["category"], "Artwork")

        transcript = "\n".join(reply.message for reply in replies)
        self.assertNotIn("artwork", transcript.lower())
        self.assertNotIn("ai", transcript.lower())
        self.assertIn(projector.name, replies[-1].message)
        self.assertEqual(replies[-1].metadata["result_count"], 1)
        self.assertEqual(
            replies[-1].metadata["structured_response"]["products"][0]["public_ref"],
            projector.slug,
        )
        for reply in replies:
            session_debug = reply.metadata.get("shopping_session", {})
            if session_debug:
                self.assertNotEqual(session_debug["new_category"], "Artwork")
                self.assertIn("previous_category", session_debug)
                self.assertIn("reason_for_change", session_debug)
                self.assertIn("slot_updates", session_debug)
                self.assertIn("shopping_state_before", session_debug)
                self.assertIn("shopping_state_after", session_debug)

    def test_budget_only_followup_never_changes_locked_projector_category(self):
        projector_category = Category.objects.create(name="Projectors", slug="projectors-budget")
        Category.objects.create(name="Artwork", slug="artwork-budget")
        conversation = SmartChatConversation.objects.create(context={
            "state": {
                "category": projector_category.name,
                "product_type": projector_category.name,
                "locked_category": projector_category.name,
                "shopping_category_locked": True,
                "active_subject": projector_category.name,
                "requirements": {},
            },
            "smart_shopping": {
                "category": projector_category.name,
                "product_type": projector_category.name,
                "locked_category": projector_category.name,
                "shopping_category_locked": True,
                "active_subject": projector_category.name,
                "requirements": {},
            },
        })

        reply = self.send(conversation, "₦400,000")

        conversation.refresh_from_db()
        state = conversation.context["state"]
        self.assertEqual(state["category"], "Projectors")
        self.assertEqual(state["locked_category"], "Projectors")
        self.assertEqual(state["requirements"]["budget_max"], 400000)
        self.assertNotIn("artwork", reply.message.lower())
        self.assertEqual(
            reply.metadata["shopping_session"]["reason_for_change"],
            "no_new_category",
        )


class UniversalMarketplaceConversationStateTests(TestCase):
    DOMAIN_CASES = (
        ("Audio-visual equipment", "projector", "commerce", "product"),
        ("Consumer electronics", "television", "commerce", "product"),
        ("Computers", "laptop", "commerce", "product"),
        ("Phones", "smartphone", "commerce", "product"),
        ("Home appliances", "commercial freezer", "commerce", "product"),
        ("Furniture", "office chair", "commerce", "product"),
        ("Fashion", "leather bag", "commerce", "product"),
        ("Beauty products", "skincare kit", "commerce", "product"),
        ("Office equipment", "photocopier", "commerce", "product"),
        ("Industrial equipment", "diesel generator", "commerce", "product"),
        ("Construction equipment", "concrete mixer", "commerce", "product"),
        ("Hospital equipment", "patient monitor", "commerce", "medical_equipment"),
        ("Laboratory equipment", "laboratory equipment", "commerce", "medical_equipment"),
        ("Farm equipment", "tractor", "commerce", "farm_equipment"),
        ("Vehicles", "Toyota Camry", "vehicle", "vehicle"),
        ("Vehicle spare parts", "Toyota gearbox spare part", "vehicle", "vehicle"),
        ("Real estate", "apartment", "real_estate", "property"),
        ("Rentals", "bus rental", "vehicle", "vehicle"),
        ("Software", "school management software", "software", "software"),
        ("Digital services", "e-commerce app developer", "service", "service_provider"),
        ("Installers", "CCTV installer", "service", "service_provider"),
        ("Repair providers", "projector repair technician", "service", "service_provider"),
        ("Consultants", "property valuer", "service", "service_provider"),
        ("Logistics providers", "logistics provider", "service", "service_provider"),
        ("Manufacturers", "manufacturer for custom furniture", "commerce", "product"),
        ("Wholesale sourcing", "wholesale laptops", "commerce", "product"),
    )

    def test_representative_domain_matrix_preserves_subject_through_slot_followups(self):
        for label, subject, intent_family, entity_type in self.DOMAIN_CASES:
            with self.subTest(domain=label):
                Category.objects.create(name=subject.title(), slug=f"{label.lower().replace(' ', '-')}-category")
                conversation = SmartChatConversation.objects.create()

                state = prepare_context(conversation, f"I need {subject}")
                locked_subject = state["active_subject"]
                self.assertTrue(locked_subject)

                for message in ("₦400,000", "Lagos", "brand new", "3 units"):
                    state = prepare_context(conversation, message)
                    self.assertEqual(state["active_subject"], locked_subject)
                    self.assertEqual(state["locked_category"], locked_subject)
                    self.assertNotEqual(state["active_subject"].lower(), "artwork")
                    self.assertNotEqual(state["active_subject"].lower(), "general_marketplace")

                self.assertEqual(state["requirements"]["budget_max"], 400000)
                self.assertEqual(state["requirements"]["currency"], "NGN")
                self.assertEqual(state["requirements"]["delivery_location"], "Lagos")
                self.assertEqual(state["requirements"]["condition"], Product.CONDITION_BRAND_NEW)
                self.assertEqual(state["requirements"]["quantity"], 3)
                self.assertEqual(state["intent_family"], intent_family)
                self.assertEqual(state["entity_type"], entity_type)

    def test_required_projector_conversation_extracts_slots_without_subject_drift(self):
        Category.objects.create(name="Projector", slug="state-projector")
        conversation = SmartChatConversation.objects.create()

        for message in (
            "I need a projector.",
            "4000 lumens.",
            "My budget is ₦400,000.",
            "I need it in Lagos.",
        ):
            state = prepare_context(conversation, message)

        self.assertEqual(state["active_subject"], "Projector")
        self.assertEqual(state["requirements"]["brightness_requirement"], 4000)
        self.assertEqual(state["requirements"]["budget_amount"], 400000)
        self.assertEqual(state["requirements"]["currency"], "NGN")
        self.assertEqual(state["requirements"]["delivery_location"], "Lagos")

    def test_vehicle_purchase_conversation_preserves_vehicle_subject(self):
        conversation = SmartChatConversation.objects.create()
        for message in (
            "I need a Toyota Camry.",
            "2018 or newer.",
            "My budget is ₦18 million.",
            "Used is fine.",
            "Lagos.",
        ):
            state = prepare_context(conversation, message)

        self.assertEqual(state["active_subject"], "toyota camry")
        self.assertEqual(state["entity_type"], "vehicle")
        self.assertEqual(state["transaction_type"], "buy")
        self.assertEqual(state["requirements"]["year_min"], 2018)
        self.assertEqual(state["requirements"]["budget_amount"], 18000000)
        self.assertEqual(state["requirements"]["condition"], Product.CONDITION_FOREIGN_USED)
        self.assertEqual(state["requirements"]["delivery_location"], "Lagos")

    def test_vehicle_repair_conversation_routes_to_service_provider_state(self):
        conversation = SmartChatConversation.objects.create()
        for message in (
            "I need someone to repair my Toyota Hilux.",
            "It has a gearbox problem.",
            "I’m in Abuja.",
            "I need it this week.",
        ):
            state = prepare_context(conversation, message)

        self.assertEqual(state["transaction_type"], "repair")
        self.assertEqual(state["intent_family"], "service")
        self.assertEqual(state["entity_type"], "vehicle")
        self.assertIn("toyota hilux", state["active_subject"])
        self.assertEqual(state["requirements"]["fault_description"], "gearbox problem")
        self.assertEqual(state["requirements"]["service_location"], "Abuja")
        self.assertEqual(state["requirements"]["urgency"], "this week")

    def test_real_estate_rental_conversation_preserves_property_state(self):
        conversation = SmartChatConversation.objects.create()
        for message in (
            "I need an apartment.",
            "Two bedrooms.",
            "Lekki.",
            "Not more than ₦5 million per year.",
        ):
            state = prepare_context(conversation, message)

        self.assertEqual(state["entity_type"], "property")
        self.assertEqual(state["transaction_type"], "rent")
        self.assertEqual(state["requirements"]["bedrooms"], 2)
        self.assertEqual(state["requirements"]["delivery_location"], "Lekki")
        self.assertEqual(state["requirements"]["budget_max"], 5000000)

    def test_explicit_subject_change_clears_old_specific_slots(self):
        Category.objects.create(name="Projector", slug="change-projector")
        Category.objects.create(name="Television", slug="change-television")
        conversation = SmartChatConversation.objects.create()

        prepare_context(conversation, "I need a projector.")
        prepare_context(conversation, "My budget is ₦400,000.")
        state = prepare_context(conversation, "Actually, forget the projector. I need a television.")

        self.assertEqual(state["active_subject"], "Television")
        self.assertEqual(state["locked_category"], "Television")
        self.assertTrue(state["explicit_subject_change"])
        self.assertNotEqual(state["active_subject"], "Projector")

    def test_slot_only_messages_do_not_change_active_category_property_style(self):
        conversation = SmartChatConversation.objects.create()
        state = prepare_context(conversation, "I want land in Owerri.")
        subject = state["active_subject"]
        for message in ("About 600 square metres.", "For commercial use.", "My budget is ₦40 million."):
            state = prepare_context(conversation, message)
            self.assertEqual(state["active_subject"], subject)

        self.assertEqual(state["requirements"]["land_size"], "600 square metres")
        self.assertEqual(state["requirements"]["budget_max"], 40000000)

    def test_budget_location_quantity_condition_and_specs_never_change_active_category(self):
        conversation = SmartChatConversation.objects.create()
        state = prepare_context(conversation, "I need a patient monitor.")
        subject = state["active_subject"]
        for message in ("Five units.", "Brand new.", "For a hospital in Enugu.", "Budget is ₦12 million."):
            state = prepare_context(conversation, message)
            self.assertEqual(state["active_subject"], subject)
            self.assertNotIn(state["active_subject"].lower(), {"wall art", "paintings", "sculptures", "general_marketplace"})

        self.assertEqual(state["entity_type"], "medical_equipment")
        self.assertEqual(state["requirements"]["quantity"], 5)
        self.assertEqual(state["requirements"]["condition"], Product.CONDITION_BRAND_NEW)
        self.assertEqual(state["requirements"]["delivery_location"], "Enugu")
        self.assertEqual(state["requirements"]["budget_max"], 12000000)


@override_settings(OPENAI_API_KEY="", SECURE_SSL_REDIRECT=False)
class SmartChatProductIntelligenceTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username="logitech-vendor",
            email="vendor@example.com",
            password="password123",
            user_type="vendor",
        )
        self.customer = User.objects.create_user(
            username="shopper",
            email="shopper@example.com",
            password="password123",
        )
        self.category = Category.objects.create(
            name="Computer Accessories",
            slug="computer-accessories",
            description="Keyboards, mice, webcams and collaboration accessories.",
        )
        self.brand = Brand.objects.create(
            name="Logitech",
            slug="logitech",
            description="Logitech makes computer peripherals and video collaboration products.",
        )
        self.product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            brand=self.brand,
            sku="LOGI-MX-001",
            name="Logitech MX Master 3S",
            slug="logitech-mx-master-3s",
            description="A quiet wireless productivity mouse for office and creative work.",
            specifications="8000 DPI sensor. Bluetooth and Logi Bolt connectivity.",
            price="145000.00",
            stock_quantity=12,
            rating_avg="4.80",
            rating_count=24,
            approval_status="approved",
        )
        ProductReview.objects.create(
            product=self.product,
            user=self.customer,
            rating=5,
            title="Excellent productivity mouse",
            review="Comfortable, precise and reliable across multiple computers.",
            verified_purchase=True,
        )
        ProductQuestion.objects.create(
            product=self.product,
            user=self.customer,
            question="Does it work with macOS?",
            answer="Yes. Bluetooth works with supported macOS devices.",
            answered_by=self.vendor,
            is_public=True,
        )
        AIKnowledgeBase.objects.create(
            question="Tell me more about Logitech",
            answer="Generic FAQ answer that must not win.",
            keywords="Logitech",
            approved=True,
            priority=100,
        )

    def test_live_product_data_has_priority_over_generic_knowledge(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        user_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_USER,
            user=self.customer,
            message="Tell me more about Logitech",
        )

        reply = create_managed_ai_message(conversation, user_message, self.customer)

        self.assertEqual(reply.source_type, "product_database")
        self.assertIn("Logitech", reply.message)
        self.assertNotIn("Generic FAQ answer", reply.message)
        cards = reply.metadata["product_cards"]
        self.assertEqual(cards[0]["title"], self.product.name)
        self.assertEqual(cards[0]["rating_count"], 24)
        self.assertTrue(cards[0]["popular_qa"])
        self.assertTrue(cards[0]["add_to_cart_url"])

    def test_catalog_search_ranks_main_rally_bar_before_accessories(self):
        conference_category = Category.objects.create(
            name="Video Conferencing",
            slug="video-conferencing-ranking",
            description="Video bars, conferencing systems and accessories.",
        )
        rally_bar = Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-BAR",
            name="Logitech Rally Bar (Graphite) All-in-One Video Conferencing System",
            slug="logitech-rally-bar-graphite-ranking",
            description="Main all-in-one Rally Bar for conference rooms.",
            specifications="Video bar with camera, speakers and microphone array.",
            price="2500000.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=True,
        )
        Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-MOUNT",
            name="Logitech Rally Mounting Kit for Camera, Speakers, Table Hub & Display Hub",
            slug="logitech-rally-mounting-kit-ranking",
            description="Accessory mounting kit for Rally systems.",
            price="200000.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=True,
        )
        Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-WALL",
            name="Logitech Wall Mount for Video Bars – Rally Bar & Rally Bar Mini",
            slug="logitech-wall-mount-rally-bar-ranking",
            description="Wall mount accessory for Rally Bar.",
            price="260500.00",
            stock_quantity=3,
            approval_status="approved",
            is_active=True,
        )

        result = search_products({
            "query": "Logitech Rally Bar",
            "result_limit": 5,
        })
        typo_result = search_products({
            "query": "logitect rally bar",
            "result_limit": 5,
        })

        self.assertEqual(result["products"][0]["name"], rally_bar.name)
        self.assertEqual(typo_result["products"][0]["name"], rally_bar.name)

    def test_message_api_exposes_safe_structured_product_cards(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_AI,
            message="Catalog answer",
            metadata={"product_cards": [{"id": self.product.id, "title": self.product.name}]},
        )
        self.client.force_login(self.customer)

        response = self.client.get(
            reverse("smartchat:api_poll"),
            {"conversation_id": conversation.id, "after_id": message.id - 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["messages"][0]["metadata"]["product_cards"][0]["title"],
            self.product.name,
        )

    def test_message_api_replays_duplicate_client_message_id_without_new_messages(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.client.force_login(self.customer)
        payload = {
            "conversation_id": conversation.id,
            "message": "hello",
            "client_message_id": "web-test-duplicate-001",
        }

        first = self.client.post(
            reverse("smartchat:api_message"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        second = self.client.post(
            reverse("smartchat:api_message"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json().get("idempotent", False))
        self.assertTrue(second.json().get("idempotent"))
        self.assertEqual(
            SmartChatMessage.objects.filter(
                conversation=conversation,
                sender_type=SmartChatMessage.SENDER_USER,
                metadata__client_message_id="web-test-duplicate-001",
            ).count(),
            1,
        )
        self.assertEqual(conversation.messages.count(), 2)

    def ask(self, conversation, text):
        user_message = SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_USER,
            user=self.customer,
            message=text,
        )
        return create_managed_ai_message(conversation, user_message, self.customer)

    def test_follow_up_purchase_payment_and_delivery_do_not_repeat_product_cards(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)

        search_reply = self.ask(conversation, "Tell me about Logitech")
        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, self.product.id)
        self.assertTrue(search_reply.metadata["product_cards"])

        purchase_reply = self.ask(conversation, "I love it, how do I get it?")
        self.assertIn("Add to Cart", purchase_reply.message)
        self.assertNotIn("product_cards", purchase_reply.metadata)

        payment_reply = self.ask(conversation, "What payment options?")
        self.assertIn("checkout", payment_reply.message.lower())
        self.assertNotIn("product_cards", payment_reply.metadata)

        delivery_reply = self.ask(conversation, "Tell me about delivery")
        self.assertIn(self.product.name, delivery_reply.message)
        self.assertNotIn("product_cards", delivery_reply.metadata)

        conversation.refresh_from_db()
        self.assertEqual(conversation.context["current_product_id"], self.product.id)
        self.assertEqual(conversation.context["last_intent"], "delivery_question")

    def test_repeated_purchase_wording_preserves_selected_product(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "Tell me about Logitech")
        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, self.product.id)

        for message in ("how do i purchase it", "how do i buy it", "how do i get it"):
            with self.subTest(message=message):
                reply = self.ask(conversation, message)
                conversation.refresh_from_db()
                self.assertEqual(reply.metadata.get("intent"), "purchase_guidance")
                self.assertEqual(conversation.product_id, self.product.id)
                self.assertIn("Add to Cart", reply.message)
                self.assertNotIn("product_cards", reply.metadata)
                self.assertEqual(reply.metadata["actions"][0]["type"], "view_product")
                self.assertEqual(reply.metadata["actions"][1]["type"], "add_to_cart")

    def test_installation_question_transitions_from_product_to_provider_workflow(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        conversation.product = self.product
        conversation.save(update_fields=["product"])
        state = prepare_context(conversation, "for 20 people")
        state["requirements"]["participant_count"] = 20
        state["requirements"]["budget_max"] = 1000000
        conversation.context = {"state": state}
        conversation.save(update_fields=["context"])

        reply = self.ask(
            conversation,
            "if i buy it or purchase it who will install it for me",
        )
        conversation.refresh_from_db()
        state = (conversation.context or {}).get("state") or {}
        requirements = state.get("requirements") or {}

        self.assertEqual(reply.metadata.get("intent"), "service_provider_request")
        self.assertEqual(conversation.product_id, self.product.id)
        self.assertEqual(state.get("entity_type"), "service_provider")
        self.assertEqual(state.get("transaction_type"), "install")
        self.assertEqual(requirements.get("participant_count"), 20)
        self.assertEqual(requirements.get("budget_max"), 1000000)
        self.assertEqual(requirements.get("equipment_to_install"), self.product.name)
        self.assertIn("installation location", reply.message.lower())
        self.assertNotIn("product_cards", reply.metadata)

    def test_plain_product_reference_uses_current_product_context(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "Tell me about Logitech")
        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, self.product.id)

        reply = self.ask(conversation, "the product")

        self.assertIn(self.product.name, reply.message)
        self.assertNotIn("What would you like help with", reply.message)
        self.assertNotIn("general_marketplace", reply.message)
        self.assertNotIn("product_cards", reply.metadata)

    def test_presence_and_complaint_replies_are_contextual(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )

        presence_reply = self.ask(conversation, "You there?")
        self.assertIn("Yes, I’m here", presence_reply.message)
        self.assertNotIn("product_cards", presence_reply.metadata)

        complaint_reply = self.ask(conversation, "You're not saying anything")
        self.assertIn("Sorry about that", complaint_reply.message)
        self.assertTrue(
            HumanTakeoverRequest.objects.filter(conversation=conversation).exists()
        )

    def test_marketplace_category_router_asks_grounded_qualifying_questions(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)

        property_reply = self.ask(conversation, "I need a house in Ikeja")
        self.assertIn("rent or buy", property_reply.message)
        conversation.refresh_from_db()
        self.assertEqual(conversation.current_intent, "property_inquiry")
        self.assertEqual(conversation.context["marketplace_category"], "property")
        self.assertIn("ikeja", conversation.context["user_location"].lower())

        car_reply = self.ask(conversation, "I need a Toyota Camry")
        self.assertIn("year range", car_reply.message)
        self.assertEqual(
            AIIntentLog.objects.filter(conversation=conversation).latest("created_at").intent,
            "car_inquiry",
        )
        self.assertEqual(
            AICategoryRouterLog.objects.filter(conversation=conversation).latest("created_at").marketplace_category,
            "vehicle",
        )

    def test_new_active_admin_category_is_routed_without_code_changes(self):
        pet_category = Category.objects.create(
            name="Pet Supplies",
            slug="pet-supplies",
            description="Food, grooming, bedding and everyday supplies for pets.",
            meta_keywords="pets, dog food, cat food, animal care",
        )
        pet_product = Product.objects.create(
            vendor=self.vendor,
            category=pet_category,
            sku="PET-FOOD-001",
            name="Premium Dog Food",
            slug="premium-dog-food",
            description="Balanced dry food for adult dogs.",
            price="28500.00",
            stock_quantity=20,
            approval_status="approved",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        reply = self.ask(conversation, "Show me pet supplies")

        conversation.refresh_from_db()
        router_log = AICategoryRouterLog.objects.filter(
            conversation=conversation,
        ).latest("created_at")
        self.assertEqual(reply.source_type, "product_database")
        self.assertEqual(reply.metadata["product_cards"][0]["id"], pet_product.id)
        self.assertEqual(router_log.catalog_category_id, pet_category.id)
        self.assertEqual(router_log.marketplace_category, "Pet Supplies")
        self.assertEqual(router_log.route_source, "active_category_database")

    def test_video_conferencing_category_lock_and_contextual_follow_ups(self):
        conference_product = Product.objects.create(
            vendor=self.vendor,
            category=self.category,
            brand=self.brand,
            sku="LOGI-GROUP-001",
            name="Logitech GROUP Video Conferencing System",
            slug="logitech-group-video-conferencing-system",
            description=(
                "A video conferencing system for mid-to-large meeting rooms, "
                "boardrooms, classrooms, churches and hybrid meetings."
            ),
            specifications=(
                "Conference camera, speakerphone and microphones for rooms with "
                "approximately 14 to 20 people. Supports Zoom and Microsoft Teams."
            ),
            price="989550.00",
            stock_quantity=5,
            approval_status="approved",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        qualifier = self.ask(conversation, "I am looking for a conferencing device")
        conversation.refresh_from_db()
        self.assertEqual(conversation.current_intent, "product_recommendation")
        self.assertEqual(
            conversation.context["current_category_locked"],
            "video_conferencing",
        )
        self.assertIn("boardroom", qualifier.message.lower())
        self.assertNotIn("year range", qualifier.message.lower())
        self.assertNotIn("product_cards", qualifier.metadata)

        recommendation = self.ask(conversation, "500,000 - 1,000,000")
        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, conference_product.id)
        self.assertEqual(
            recommendation.metadata["product_cards"][0]["id"],
            conference_product.id,
        )
        self.assertEqual(conversation.context["user_budget"], "500000 - 1000000")

        usage = self.ask(conversation, "Where can I use this?")
        self.assertIn("boardrooms", usage.message.lower())
        self.assertIn("churches", usage.message.lower())
        self.assertNotIn("product_cards", usage.metadata)

        function = self.ask(conversation, "What is the function of this device?")
        self.assertIn("video conferencing", function.message.lower())
        self.assertIn("see, hear, and speak", function.message.lower())
        self.assertNotIn("wall art", function.message.lower())
        self.assertNotIn("product_cards", function.metadata)

    def test_budget_recommendation_excludes_accessories_from_primary_results(self):
        conference_category = Category.objects.create(
            name="Video Conferencing Systems",
            slug="video-conferencing-systems-primary",
        )
        group = Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-GROUP-BUDGET",
            name="Logitech GROUP Video Conferencing System",
            slug="logitech-group-video-conferencing-system-budget",
            description="Complete video conferencing system for meeting rooms.",
            specifications="Camera, speakerphone and microphone system for 14 to 20 people.",
            price="989550.00",
            stock_quantity=5,
            approval_status="approved",
        )
        Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-MOUNT-BUDGET",
            name="Logitech Rally Mounting Kit for Camera, Speakers, Table Hub & Display Hub",
            slug="logitech-rally-mounting-kit-budget",
            description="Accessory mounting kit for Rally systems.",
            specifications="Mounting accessory, not a standalone conferencing system.",
            price="200000.00",
            stock_quantity=5,
            approval_status="approved",
        )
        Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-MIC-BUDGET",
            name="Logitech Rally Mic Pod Boundary Microphone for Rally Bar",
            slug="logitech-rally-mic-pod-budget",
            description="Accessory microphone for Rally systems.",
            specifications="Microphone accessory, not a standalone conferencing system.",
            price="580550.00",
            stock_quantity=5,
            approval_status="approved",
        )
        Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-C920-BUDGET",
            name="Logitech C920 1080p HD Pro Stream Webcam",
            slug="logitech-c920-budget",
            description="Standalone webcam for personal streaming.",
            specifications="Webcam only.",
            price="75500.00",
            stock_quantity=5,
            approval_status="approved",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        self.ask(conversation, "i want to purchase a conferencing device, can you help with a good choice?")
        self.ask(conversation, "its for a meeting room of 20 people")
        reply = self.ask(conversation, "please give me device of less then 1,000,000")
        conversation.refresh_from_db()
        card_titles = [
            card["title"]
            for card in reply.metadata.get("product_cards", [])
        ]

        self.assertEqual(conversation.product_id, group.id)
        self.assertIn(group.name, card_titles)
        self.assertFalse(any("Mounting Kit" in title for title in card_titles))
        self.assertFalse(any("Mic Pod" in title for title in card_titles))
        self.assertFalse(any("C920" in title for title in card_titles))
        self.assertIn("accessories", reply.message.lower())

    def test_bulk_quote_escalates_with_preserved_context(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )

        reply = self.ask(
            conversation,
            "I need a bulk order quotation for 50 units delivered to Ikeja",
        )

        self.assertIn("quantity", reply.message)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, SmartChatConversation.STATUS_ADMIN_REQUESTED)
        self.assertEqual(conversation.context["current_product_id"], self.product.id)
        self.assertTrue(
            HumanTakeoverRequest.objects.filter(conversation=conversation).exists()
        )
        self.assertIn("Intent: quotation_request", conversation.ai_summary)
        self.assertIn(self.product.name, conversation.ai_summary)
        self.assertIn("Ikeja", conversation.ai_summary)

    def test_generic_projector_context_recommendation_price_and_alternatives(self):
        projector_category = Category.objects.create(
            name="Projectors",
            slug="projectors",
            description="Projectors for meeting rooms, schools, churches and home cinema.",
        )
        optoma = Brand.objects.create(
            name="Optoma",
            slug="optoma",
            description="Projection and display equipment.",
        )
        first = Product.objects.create(
            vendor=self.vendor,
            category=projector_category,
            brand=optoma,
            sku="OPT-W318ST",
            name="Optoma W318ST Short Throw Projector",
            slug="optoma-w318st-short-throw-projector",
            description="A bright short throw projector for small meeting rooms.",
            specifications="4000 lumens. WXGA resolution. Short throw projection.",
            price="650000.00",
            stock_quantity=5,
            rating_avg="4.90",
            rating_count=10,
            approval_status="approved",
        )
        second = Product.objects.create(
            vendor=self.vendor,
            category=projector_category,
            brand=optoma,
            sku="OPT-EH412",
            name="Optoma EH412 Full HD Projector",
            slug="optoma-eh412-full-hd-projector",
            description="A Full HD projector for offices, classrooms and churches.",
            specifications="4500 lumens. Native Full HD 1080p resolution.",
            price="690500.00",
            stock_quantity=8,
            rating_avg="4.70",
            rating_count=6,
            approval_status="approved",
        )
        cheaper = Product.objects.create(
            vendor=self.vendor,
            category=projector_category,
            brand=optoma,
            sku="OPT-S336",
            name="Optoma S336 Projector",
            slug="optoma-s336-projector",
            description="An affordable projector for small rooms.",
            specifications="4000 lumens. SVGA resolution.",
            price="410000.00",
            stock_quantity=4,
            rating_avg="4.00",
            rating_count=2,
            approval_status="approved",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        greeting = self.ask(conversation, "Hello")
        self.assertIn("Welcome to Arolana", greeting.message)

        availability = self.ask(conversation, "Do you have Optoma projectors?")
        self.assertEqual(availability.source_type, "product_database")
        self.assertTrue(availability.metadata["product_cards"])

        room = self.ask(conversation, "For a small room")
        self.assertIn("screen size", room.message.lower())

        screen = self.ask(conversation, "120 inch")
        self.assertIn("120-inch", screen.message)

        choice = self.ask(conversation, "Make a choice for me")
        conversation.refresh_from_db()
        self.assertIn(conversation.product_id, {first.id, second.id, cheaper.id})
        self.assertIn("Optoma", choice.message)
        self.assertEqual(
            conversation.context["state"]["requirements"]["screen_size_inches"],
            120.0,
        )
        self.assertIn("small_room", conversation.context["state"]["requirements"]["room_type"])

        price = self.ask(conversation, "How much?")
        self.assertIn("currently listed at", price.message)
        self.assertNotIn("which product", price.message.lower())

        current_id = conversation.product_id
        alternative = self.ask(conversation, "Show me another one.")
        conversation.refresh_from_db()
        self.assertNotEqual(conversation.product_id, current_id)
        self.assertIn("Another suitable option", alternative.message)

        # Start from the most expensive option so a cheaper live alternative is guaranteed.
        conversation.product = second
        conversation.context["state"]["current_product_id"] = second.id
        conversation.context["state"]["recommendation"]["current_recommendation_id"] = second.id
        conversation.context["state"]["recommendation"]["previous_recommendation_ids"] = [first.id]
        conversation.save(update_fields=["product", "context", "updated_at"])
        cheaper_reply = self.ask(conversation, "Cheaper one.")
        conversation.refresh_from_db()
        self.assertLess(conversation.product.price, Decimal("690500.00"))
        self.assertIn("cheaper suitable option", cheaper_reply.message.lower())

    def test_participant_followup_uses_existing_brand_and_category(self):
        conference_category = Category.objects.create(
            name="Conference Equipment",
            slug="conference-equipment",
            description="Video conferencing cameras, speakerphones and room systems.",
        )
        conference = Product.objects.create(
            vendor=self.vendor,
            category=conference_category,
            brand=self.brand,
            sku="LOGI-RALLY-12",
            name="Logitech Rally Conference System",
            slug="logitech-rally-conference-system",
            description="A conference system for medium meeting rooms.",
            specifications="Designed for 12 people with Zoom and Teams support.",
            price="1200000.00",
            stock_quantity=3,
            approval_status="approved",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        self.ask(conversation, "Do you have Logitech conference equipment?")
        recommendation = self.ask(conversation, "For 12 people.")

        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, conference.id)
        self.assertEqual(
            conversation.context["state"]["requirements"]["participant_count"],
            12,
        )
        self.assertIn("12 people", recommendation.message)

    def test_internal_knowledge_is_never_returned_verbatim(self):
        AIKnowledgeBase.objects.create(
            question="How should follow up context work?",
            answer="Keep the existing conversation context and do not restart the conversation.",
            answer_type="internal_rule",
            keywords="follow up context",
            approved=True,
            priority=100,
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)

        reply = self.ask(conversation, "How should follow up context work?")

        self.assertNotIn("do not restart the conversation", reply.message.lower())

    def test_learning_marks_short_context_as_context_only(self):
        from .models import AISettings

        settings_obj = AISettings.load()
        settings_obj.learning_enabled = True
        settings_obj.save(update_fields=["learning_enabled", "updated_at"])
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            context={
                "state": {
                    "active_subject": "projector",
                    "requirements": {"room_type": "small_room"},
                },
            },
        )

        self.ask(conversation, "120 inch")

        learned = AILearnedKnowledge.objects.get(normalized_question="120 inch")
        self.assertEqual(learned.knowledge_type, "follow_up_context")
        self.assertTrue(learned.requires_previous_context)

    def test_customer_memory_is_never_shared_between_users(self):
        other = User.objects.create_user(
            username="other-shopper",
            email="other-shopper@example.com",
            password="password123",
        )
        conversation = SmartChatConversation.objects.create(user=self.customer)
        other_conversation = SmartChatConversation.objects.create(user=other)
        AICustomerMemory.objects.create(
            user=self.customer,
            memory_key="shopping_preference",
            memory_value="quiet office equipment",
            source_conversation=conversation,
        )

        from .ai_manager import customer_memories_for

        self.assertEqual(customer_memories_for(conversation).count(), 1)
        self.assertEqual(customer_memories_for(other_conversation).count(), 0)

    def test_shared_mobile_api_reuses_conversation_and_returns_state(self):
        self.client.force_login(self.customer)
        started = self.client.post(
            reverse("smartchat_api:start"),
            data=json.dumps({
                "device_id": "ios-investor-demo",
                "product_id": self.product.id,
                "preferred_language": "en",
            }),
            content_type="application/json",
        )
        self.assertEqual(started.status_code, 200)
        conversation_id = started.json()["conversation_id"]

        sent = self.client.post(
            reverse("smartchat_api:message"),
            data=json.dumps({
                "conversation_id": conversation_id,
                "message": "How much?",
                "device_id": "ios-investor-demo",
            }),
            content_type="application/json",
        )

        self.assertEqual(sent.status_code, 200)
        payload = sent.json()
        self.assertEqual(payload["conversation_id"], conversation_id)
        self.assertEqual(payload["conversation"]["current_intent"], "price_question")
        self.assertEqual(
            payload["conversation"]["context"]["state"]["current_product_id"],
            self.product.id,
        )
        self.assertIn("currently listed at", payload["messages"][-1]["message"])

    def test_explicit_vendor_topic_clears_product_cards_and_preserves_topic_stack(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )

        reply = self.ask(conversation, "How do I sell on Arolana?")

        conversation.refresh_from_db()
        self.assertEqual(reply.metadata["intent"], "vendor_registration")
        self.assertNotIn("product_cards", reply.metadata)
        self.assertEqual(reply.metadata["cards"], [])
        self.assertIn("vendor registration", reply.message.lower())
        self.assertIsNone(conversation.product_id)
        self.assertEqual(
            conversation.context["state"]["last_topic"],
            "vendor_registration",
        )
        self.assertEqual(
            conversation.context["state"]["topic_stack"][-1]["current_product_id"],
            self.product.id,
        )

    def test_platform_information_never_leaks_internal_instructions(self):
        AIKnowledgeBase.objects.create(
            question="What is Arolana all about?",
            answer=(
                "Describe what you need naturally and keep the existing conversation "
                "context, transcript, detected intent, and escalation reason."
            ),
            answer_type="customer_answer",
            approved=True,
            priority=100,
        )
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )

        reply = self.ask(conversation, "What is Arolana all about?")

        self.assertIn("multi-category marketplace", reply.message.lower())
        self.assertNotIn("detected intent", reply.message.lower())
        self.assertEqual(reply.metadata["cards"], [])
        self.assertTrue(reply.metadata["actions"])

    def test_vendor_plan_followup_stays_on_vendor_topic_without_product_cards(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )
        self.ask(conversation, "How do I sell on Arolana?")

        reply = self.ask(conversation, "Which plan should I choose?")

        self.assertEqual(reply.metadata["intent"], "vendor_subscription_overview")
        self.assertEqual(reply.metadata["cards"], [])
        self.assertNotIn("product_cards", reply.metadata)
        self.assertIn("plans", reply.message.lower())

    def test_return_to_previous_product_restores_context(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )
        self.ask(conversation, "How do I sell on Arolana?")

        reply = self.ask(conversation, "Go back to the product")

        conversation.refresh_from_db()
        self.assertEqual(conversation.product_id, self.product.id)
        self.assertIn(self.product.name, reply.message)

    def test_closed_mobile_api_conversation_reopens_for_ai(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
            status=SmartChatConversation.STATUS_CLOSED,
        )
        HumanTakeoverRequest.objects.create(
            conversation=conversation,
            requested_by=self.customer,
        )
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("smartchat_api:message"),
            data=json.dumps({
                "conversation_id": conversation.id,
                "message": "What is Arolana all about?",
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["reopened"])
        self.assertEqual(payload["conversation_status"], SmartChatConversation.STATUS_AI)
        self.assertEqual(payload["cards"], [])
        self.assertEqual(
            conversation.takeover_requests.get().status,
            HumanTakeoverRequest.STATUS_CANCELLED,
        )

    def test_contextual_guard_typo_continues_vendor_onboarding(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "how do i become a vendor")

        reply = self.ask(conversation, "can you guard me?")

        conversation.refresh_from_db()
        self.assertEqual(reply.metadata["intent"], "vendor_onboarding_guidance")
        self.assertEqual(reply.metadata["topic_relation"], "continue")
        self.assertIn("guide you through it step by step", reply.message.lower())
        self.assertEqual(
            reply.metadata["text_resolution"]["normalized"].lower(),
            "can you guide me?",
        )
        workflow = conversation.context["state"]["workflow"]
        self.assertEqual(workflow["type"], "vendor_onboarding")
        self.assertEqual(workflow["current_step"], 1)
        self.assertEqual(reply.metadata["cards"], [])
        self.assertEqual(
            reply.metadata["actions"][0]["url"],
            reverse("vendor_register_redirect"),
        )

    def test_explicit_step_by_step_guidance_starts_vendor_workflow(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "how do i become a vendor")

        reply = self.ask(conversation, "can you guide me step by step?")

        self.assertIn("1. Sign in", reply.message)
        self.assertIn("12. Manage orders", reply.message)
        conversation.refresh_from_db()
        self.assertEqual(
            conversation.context["state"]["workflow"]["status"],
            "in_progress",
        )

    def test_what_next_advances_current_vendor_workflow_step(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "how do i become a vendor")
        self.ask(conversation, "can you guide me?")

        reply = self.ask(conversation, "what next?")

        conversation.refresh_from_db()
        self.assertIn("Step 2", reply.message)
        self.assertEqual(
            conversation.context["state"]["workflow"]["current_step"],
            2,
        )

    def test_completed_kyc_updates_workflow_and_moves_to_submission(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "how do i become a vendor")

        reply = self.ask(conversation, "i have completed kyc")

        conversation.refresh_from_db()
        workflow = conversation.context["state"]["workflow"]
        self.assertIn(5, workflow["completed_steps"])
        self.assertEqual(workflow["current_step"], 6)
        self.assertIn("submit your vendor application", reply.message.lower())

    def test_guard_my_account_is_not_corrected_to_guide(self):
        conversation = SmartChatConversation.objects.create(user=self.customer)
        self.ask(conversation, "how do i become a vendor")

        reply = self.ask(conversation, "can you guard my account?")

        self.assertEqual(reply.metadata["intent"], "account_security")
        self.assertIn("secure your arolana account", reply.message.lower())
        self.assertFalse(
            reply.metadata.get("text_resolution", {}).get("applied", False),
        )

    def test_common_contextual_typos_feed_existing_product_engine(self):
        conversation = SmartChatConversation.objects.create(
            user=self.customer,
            product=self.product,
        )

        price = self.ask(conversation, "how mush?")
        alternative = self.ask(conversation, "show me anoda one")

        self.assertIn("currently listed at", price.message)
        self.assertEqual(
            price.metadata["text_resolution"]["normalized"].lower(),
            "how much?",
        )
        self.assertEqual(
            alternative.metadata["text_resolution"]["normalized"].lower(),
            "show me another one",
        )

    def test_safe_typo_dictionary_handles_vendor_conference_and_room_phrases(self):
        from .text_normalizer import resolve_contextual_text

        conversation = SmartChatConversation.objects.create(user=self.customer)
        sale_reply = self.ask(conversation, "how do i sale on arolana")
        conference = resolve_contextual_text(
            conversation,
            "i need conferening device",
        )
        room = resolve_contextual_text(conversation, "for small rom")

        self.assertEqual(sale_reply.metadata["intent"], "vendor_registration")
        self.assertEqual(
            sale_reply.metadata["text_resolution"]["normalized"].lower(),
            "how do i sell on arolana",
        )
        self.assertEqual(
            conference["normalized"].lower(),
            "i need conferencing device",
        )
        self.assertEqual(room["normalized"].lower(), "for a small room")

    def test_web_and_mobile_api_share_contextual_typo_and_workflow_engine(self):
        web_conversation = SmartChatConversation.objects.create(user=self.customer)
        mobile_conversation = SmartChatConversation.objects.create(
            user=self.customer,
            channel="mobile",
        )
        for conversation in (web_conversation, mobile_conversation):
            self.ask(conversation, "how do i become a vendor")
        self.client.force_login(self.customer)

        web_response = self.client.post(
            reverse("smartchat:api_message"),
            data=json.dumps({
                "conversation_id": web_conversation.id,
                "message": "can you guard me?",
            }),
            content_type="application/json",
        )
        mobile_response = self.client.post(
            reverse("smartchat_api:message"),
            data=json.dumps({
                "conversation_id": mobile_conversation.id,
                "message": "can you guard me?",
            }),
            content_type="application/json",
        )

        self.assertEqual(web_response.status_code, 200)
        self.assertEqual(mobile_response.status_code, 200)
        web_ai = web_response.json()["messages"][-1]
        mobile_ai = mobile_response.json()["reply"]
        for payload in (web_ai, mobile_ai):
            self.assertEqual(
                payload["metadata"]["intent"],
                "vendor_onboarding_guidance",
            )
            self.assertIn("guide you through it", payload["message"].lower())
