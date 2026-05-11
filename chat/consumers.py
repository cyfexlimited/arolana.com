import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone
from chat.models import ChatRoom, ChatMessage, VendorChatRoom, VendorChatMessage

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """Generic chat consumer for multi-participant chat rooms"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.room_id = self.scope['url_route']['kwargs'].get('room_id')
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope['user']

        # Check if user is authenticated and is a participant
        if not self.user.is_authenticated:
            await self.close()
            return

        room = await self.get_room(self.room_id)
        if not room:
            await self.close()
            return

        participants = await self.get_room_participants(room)
        if self.user not in participants:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'message')

            if message_type == 'message':
                await self.handle_message(data)
            elif message_type == 'typing':
                await self.handle_typing(data)
            elif message_type == 'read_receipt':
                await self.handle_read_receipt(data)
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def handle_message(self, data):
        """Handle chat message"""
        message = data.get('message', '').strip()
        if not message:
            return

        msg = await self.save_message(self.room_id, self.user, message)

        if msg:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message,
                    'username': self.user.username,
                    'user_id': self.user.id,
                    'message_id': msg.id,
                    'timestamp': msg.created_at.isoformat(),
                }
            )

    async def handle_typing(self, data):
        """Handle typing indicator"""
        is_typing = data.get('is_typing', False)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'username': self.user.username,
                'user_id': self.user.id,
                'is_typing': is_typing
            }
        )

    async def handle_read_receipt(self, data):
        """Handle read receipt for messages"""
        message_id = data.get('message_id')

        if message_id:
            await self.mark_message_read(message_id, self.user)

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'read_receipt',
                    'message_id': message_id,
                    'user_id': self.user.id,
                    'username': self.user.username
                }
            )

    async def chat_message(self, event):
        """Send chat message to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
        }))

    async def typing_indicator(self, event):
        """Send typing indicator to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'user_id': event['user_id'],
            'is_typing': event['is_typing'],
        }))

    async def read_receipt(self, event):
        """Send read receipt to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'read',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username']
        }))

    @database_sync_to_async
    def get_room(self, room_id):
        """Get chat room by ID"""
        try:
            return ChatRoom.objects.get(id=room_id, is_active=True)
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def get_room_participants(self, room):
        """Get all participants in a chat room"""
        return list(room.participants.all())

    @database_sync_to_async
    def save_message(self, room_id, user, message):
        """Save message to database"""
        try:
            room = ChatRoom.objects.get(id=room_id)
            msg = ChatMessage.objects.create(
                room=room,
                sender=user,
                message=message
            )
            room.save()
            return msg
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def mark_message_read(self, message_id, user):
        """Mark message as read"""
        try:
            msg = ChatMessage.objects.get(id=message_id)
            if not msg.is_read and msg.sender != user:
                msg.is_read = True
                msg.read_at = timezone.now()
                msg.save()
        except ChatMessage.DoesNotExist:
            pass


class VendorChatConsumer(AsyncWebsocketConsumer):
    """Specialized consumer for vendor-customer chats"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.room_id = self.scope['url_route']['kwargs'].get('vendor_room_id')
        self.room_group_name = f'vendor_chat_{self.room_id}'
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        room = await self.get_room(self.room_id)
        if not room:
            await self.close()
            return

        if self.user != room.vendor and self.user != room.customer:
            await self.close()
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message = data.get('message', '').strip()

            if not message:
                return

            msg = await self.save_message(self.room_id, self.user, message)

            if msg:
                await self.update_unread_count(self.room_id, self.user)

                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'vendor_message',
                        'message': message,
                        'username': self.user.username,
                        'user_id': self.user.id,
                        'timestamp': msg.created_at.isoformat()
                    }
                )
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def vendor_message(self, event):
        """Send vendor message to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'timestamp': event['timestamp']
        }))

    @database_sync_to_async
    def get_room(self, room_id):
        """Get vendor chat room by ID"""
        try:
            return VendorChatRoom.objects.get(id=room_id, is_active=True)
        except VendorChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def save_message(self, room_id, user, message):
        """Save vendor message to database"""
        try:
            room = VendorChatRoom.objects.get(id=room_id)
            msg = VendorChatMessage.objects.create(
                room=room,
                sender=user,
                message=message
            )
            room.last_message = message
            room.last_message_time = timezone.now()

            if user == room.vendor:
                room.customer_unread += 1
            else:
                room.vendor_unread += 1

            room.save()
            return msg
        except VendorChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def update_unread_count(self, room_id, user):
        """Update unread message count for vendor chat"""
        try:
            room = VendorChatRoom.objects.get(id=room_id)
            if user == room.vendor:
                room.vendor_unread = 0
            else:
                room.customer_unread = 0
            room.save()
        except VendorChatRoom.DoesNotExist:
            pass


class SupportConsumer(AsyncWebsocketConsumer):
    """Consumer for customer support chats"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.user = self.scope['user']

        if not self.user.is_authenticated or not self.user.is_staff:
            await self.close()
            return

        self.room_group_name = 'support_group'
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message = data.get('message', '').strip()

            if not message:
                return

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'support_message',
                    'message': message,
                    'username': self.user.username,
                    'user_id': self.user.id
                }
            )
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def support_message(self, event):
        """Send support message to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id']
        }))
