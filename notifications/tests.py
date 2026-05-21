import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Notification, NotificationPreference, WebPushSubscription


User = get_user_model()


class WebPushNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='pushuser',
            email='pushuser@example.com',
            password='pass12345',
        )

    @override_settings(
        WEB_PUSH_ENABLED=True,
        WEB_PUSH_VAPID_PUBLIC_KEY='BExamplePublicKey',
        WEB_PUSH_VAPID_PRIVATE_KEY='ExamplePrivateKey',
    )
    def test_push_config_and_subscription_api(self):
        config_response = self.client.get('/notifications/api/push/config/')
        self.assertEqual(config_response.status_code, 200)
        self.assertFalse(config_response.json()['authenticated'])

        self.client.force_login(self.user)
        payload = {
            'subscription': {
                'endpoint': 'https://push.example.test/subscription/1',
                'keys': {
                    'p256dh': 'public-key',
                    'auth': 'auth-secret',
                },
            },
            'device_name': 'Test phone',
            'browser_name': 'Chrome',
        }
        response = self.client.post(
            '/notifications/api/push/subscribe/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        subscription = WebPushSubscription.objects.get(user=self.user)
        self.assertEqual(subscription.endpoint, payload['subscription']['endpoint'])
        self.assertEqual(subscription.device_name, 'Test phone')
        self.assertTrue(subscription.is_active)

        unsubscribe = self.client.post(
            '/notifications/api/push/unsubscribe/',
            data=json.dumps({'endpoint': subscription.endpoint}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(unsubscribe.status_code, 200)
        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)

    @override_settings(
        WEB_PUSH_ENABLED=True,
        WEB_PUSH_VAPID_PUBLIC_KEY='BExamplePublicKey',
        WEB_PUSH_VAPID_PRIVATE_KEY='ExamplePrivateKey',
        WEB_PUSH_VAPID_SUBJECT='mailto:test@example.com',
    )
    def test_notification_send_delivers_to_active_push_subscription(self):
        WebPushSubscription.objects.create(
            user=self.user,
            endpoint='https://push.example.test/subscription/2',
            p256dh='public-key',
            auth='auth-secret',
            browser_name='Chrome',
        )

        with patch('notifications.webpush.webpush') as mocked_webpush:
            notification = Notification.send(
                user=self.user,
                notification_type='message',
                title='New chat',
                message='Arolana admin replied.',
                link='/notifications/',
            )

        mocked_webpush.assert_called_once()
        notification.refresh_from_db()
        self.assertTrue(notification.push_sent)
        self.assertIsNotNone(notification.push_sent_at)

    @override_settings(
        WEB_PUSH_ENABLED=True,
        WEB_PUSH_VAPID_PUBLIC_KEY='BExamplePublicKey',
        WEB_PUSH_VAPID_PRIVATE_KEY='ExamplePrivateKey',
    )
    def test_notification_respects_push_preferences(self):
        WebPushSubscription.objects.create(
            user=self.user,
            endpoint='https://push.example.test/subscription/3',
            p256dh='public-key',
            auth='auth-secret',
        )
        preferences, _ = NotificationPreference.objects.get_or_create(user=self.user)
        preferences.push_notifications = False
        preferences.save()

        with patch('notifications.webpush.webpush') as mocked_webpush:
            notification = Notification.send(
                user=self.user,
                notification_type='message',
                title='Muted chat',
                message='This should stay in web only.',
            )

        mocked_webpush.assert_not_called()
        notification.refresh_from_db()
        self.assertFalse(notification.push_sent)
