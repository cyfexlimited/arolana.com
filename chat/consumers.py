import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from chat.models import ChatRoom, ChatMessage, VendorChatRoom, VendorChatMessage
from accounts.models import User

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        
        # Check if user is participant
        user = self.scope['user']
        if user.is_authenticated:
            room = await self.get_room(self.room_id)
            if room and user in await self.get_room_participants(room):
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                await self.accept()
                return
        
        await self.close()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type', 'message')
        
        if message_type == 'message':
            await self.handle_message(data)
        elif message_type == 'typing':
            await self.handle_typing(data)
        elif message_type == 'read_receipt':
            await self.handle_read_receipt(data)
    
    async def handle_message(self, data):
        message = data.get('message', '')
        user = self.scope['user']
        
        # Save message to database
        msg = await self.save_message(self.room_id, user, message)
        
        # Send to group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'username': user.username,
                'user_id': user.id,
                'timestamp': msg.created_at.isoformat() if msg else '',
                'message_id': msg.id if msg else None
            }
        )
    
    async def handle_typing(self, data):
        user = self.scope['user']
        is_typing = data.get('is_typing', False)
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'typing_indicator',
                'username': user.username,
                'is_typing': is_typing
            }
        )
    
    async def handle_read_receipt(self, data):
        user = self.scope['user']
        message_id = data.get('message_id')
        
        if message_id:
            await self.mark_message_read(message_id, user)
    
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'timestamp': event['timestamp'],
            'message_id': event['message_id']
        }))
    
    async def typing_indicator(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'username': event['username'],
            'is_typing': event['is_typing']
        }))
    
    @database_sync_to_async
    def get_room(self, room_id):
        try:
            return ChatRoom.objects.get(id=room_id, is_active=True)
        except ChatRoom.DoesNotExist:
            return None
    
    @database_sync_to_async
    def get_room_participants(self, room):
        return list(room.participants.all())
    
    @database_sync_to_async
    def save_message(self, room_id, user, message):
        room = ChatRoom.objects.get(id=room_id)
        msg = ChatMessage.objects.create(
            room=room,
            sender=user,
            message=message
        )
        # Update room's updated_at
        room.save()
        return msg
    
    @database_sync_to_async
    def mark_message_read(self, message_id, user):
        try:
            msg = ChatMessage.objects.get(id=message_id, room__participants=user)
            if not msg.is_read and msg.sender != user:
                msg.is_read = True
                msg.read_at = timezone.now()
                msg.save()
        except ChatMessage.DoesNotExist:
            pass


class VendorChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['vendor_room_id']
        self.room_group_name = f'vendor_chat_{self.room_id}'
        self.user = self.scope['user']
        
        # Check if user is vendor or customer
        if self.user.is_authenticated:
            room = await self.get_room(self.room_id)
            if room and (self.user == room.vendor or self.user == room.customer):
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                await self.accept()
                return
        
        await self.close()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message', '')
        
        # Save message
        msg = await self.save_message(self.room_id, self.user, message)
        
        # Update unread count
        await self.update_unread_count(self.room_id, self.user)
        
        # Send to group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'vendor_message',
                'message': message,
                'username': self.user.username,
                'user_id': self.user.id,
                'timestamp': msg.created_at.isoformat() if msg else ''
            }
        )
    
    async def vendor_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'timestamp': event['timestamp']
        }))
    
    @database_sync_to_async
    def get_room(self, room_id):
        try:
            return VendorChatRoom.objects.get(id=room_id, is_active=True)
        except VendorChatRoom.DoesNotExist:
            return None
    
    @database_sync_to_async
    def save_message(self, room_id, user, message):
        room = VendorChatRoom.objects.get(id=room_id)
        msg = VendorChatMessage.objects.create(
            room=room,
            sender=user,
            message=message
        )
        room.last_message = message
        room.last_message_time = timezone.now()
        
        # Increment unread count for the other user
        if user == room.vendor:
            room.customer_unread += 1
        else:
            room.vendor_unread += 1
        
        room.save()
        return msg
    
    @database_sync_to_async
    def update_unread_count(self, room_id, user):
        room = VendorChatRoom.objects.get(id=room_id)
        if user == room.vendor:
            room.vendor_unread = 0
        else:
            room.customer_unread = 0
        room.save()


class SupportConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated and self.user.is_staff:
            self.room_group_name = 'support_group'
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
        else:
            await self.close()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message', '')
        
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'support_message',
                'message': message,
                'username': self.user.username,
                'user_id': self.user.id
            }
        )
    
    async def support_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id']
        }))
