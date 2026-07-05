import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from notifications.models import Notification
from products.models import Brand, Category, Product, ProductQuestion, ProductReview
from .ai_manager import create_managed_ai_message
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
        self.assertIn("I’m here", greeting.message)

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
