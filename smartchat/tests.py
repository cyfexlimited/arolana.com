import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification
from .models import SmartChatConversation


User = get_user_model()


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
