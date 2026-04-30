import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatRoom, ChatMessage, ChatTypingStatus
from django.utils import timezone

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send online status
        await self.send_online_status()
    
    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # Send offline status
        await self.send_offline_status()
    
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type', 'message')
        
        if message_type == 'message':
            await self.handle_message(text_data_json)
        elif message_type == 'typing':
            await self.handle_typing(text_data_json)
        elif message_type == 'read':
            await self.handle_read_receipt(text_data_json)
        elif message_type == 'edit':
            await self.handle_edit_message(text_data_json)
        elif message_type == 'delete':
            await self.handle_delete_message(text_data_json)
    
    async def handle_message(self, data):
        message = data.get('message', '')
        sender_id = data.get('sender_id')
        room_id = data.get('room_id')
        reply_to_id = data.get('reply_to_id')
        
        # Save message to database
        saved_message = await self.save_message(
            room_id, sender_id, message, reply_to_id
        )
        
        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'sender_id': sender_id,
                'sender_name': await self.get_user_name(sender_id),
                'message_id': saved_message.id,
                'timestamp': str(saved_message.created_at),
                'reply_to': reply_to_id,
            }
        )
    
    async def handle_typing(self, data):
        room_id = data.get('room_id')
        user_id = data.get('user_id')
        is_typing = data.get('is_typing', False)
        
        # Save typing status
        await self.save_typing_status(room_id, user_id, is_typing)
        
        # Send typing status to room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_status',
                'user_id': user_id,
                'user_name': await self.get_user_name(user_id),
                'is_typing': is_typing,
            }
        )
    
    async def handle_read_receipt(self, data):
        message_id = data.get('message_id')
        user_id = data.get('user_id')
        
        await self.mark_message_read(message_id, user_id)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'read_receipt',
                'message_id': message_id,
                'user_id': user_id,
            }
        )
    
    async def chat_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
            'reply_to': event.get('reply_to'),
        }))
    
    async def typing_status(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'user_id': event['user_id'],
            'user_name': event['user_name'],
            'is_typing': event['is_typing'],
        }))
    
    async def read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
        }))
    
    @database_sync_to_async
    def save_message(self, room_id, sender_id, message, reply_to_id=None):
        room = ChatRoom.objects.get(id=room_id)
        sender = User.objects.get(id=sender_id)
        reply_to = None
        if reply_to_id:
            reply_to = ChatMessage.objects.get(id=reply_to_id)
        
        return ChatMessage.objects.create(
            room=room,
            sender=sender,
            message=message,
            reply_to=reply_to
        )
    
    @database_sync_to_async
    def get_user_name(self, user_id):
        try:
            user = User.objects.get(id=user_id)
            return user.get_full_name() or user.username
        except:
            return "Unknown User"
    
    @database_sync_to_async
    def save_typing_status(self, room_id, user_id, is_typing):
        room = ChatRoom.objects.get(id=room_id)
        user = User.objects.get(id=user_id)
        status, created = ChatTypingStatus.objects.get_or_create(
            room=room, user=user,
            defaults={'is_typing': is_typing}
        )
        if not created:
            status.is_typing = is_typing
            status.last_typing_at = timezone.now()
            status.save()
    
    @database_sync_to_async
    def mark_message_read(self, message_id, user_id):
        try:
            message = ChatMessage.objects.get(id=message_id)
            if not message.is_read:
                message.is_read = True
                message.read_at = timezone.now()
                message.save()
        except:
            pass
    
    async def send_online_status(self):
        # Implementation for online status
        pass
    
    async def send_offline_status(self):
        # Implementation for offline status
        pass

class VendorChatConsumer(AsyncWebsocketConsumer):
    """Specialized consumer for vendor-customer chats"""
    async def connect(self):
        self.vendor_id = self.scope['url_route']['kwargs']['vendor_id']
        self.room_group_name = f'vendor_{self.vendor_id}'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        # Similar to ChatConsumer but with vendor-specific logic
        pass

class SupportConsumer(AsyncWebsocketConsumer):
    """Consumer for customer support chats"""
    async def connect(self):
        self.room_group_name = 'support_chat'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        # Support chat logic
        pass
