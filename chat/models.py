from django.db import models
from django.contrib.auth import get_user_model
from core.models import BaseModel
from products.models import Product
from orders.models import Order
from django.conf import settings

User = get_user_model()

class ChatRoom(BaseModel):
    """Chat room between users"""
    ROOM_TYPES = [
        ('direct', 'Direct Message'),
        ('vendor_customer', 'Vendor-Customer'),
        ('support', 'Support Chat'),
        ('group', 'Group Chat'),
    ]
    
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES, default='direct')
    name = models.CharField(max_length=255, blank=True, help_text="Room name for group chats")
    participants = models.ManyToManyField(User, related_name='chat_rooms')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_rooms')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_rooms')
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        if self.name:
            return self.name
        return f"Chat {self.id} - {self.room_type}"
    
    def get_last_message(self):
        return self.messages.filter(is_active=True).order_by('-created_at').first()
    
    def get_unread_count(self, user):
        return self.messages.filter(is_active=True, is_read=False).exclude(sender=user).count()

class ChatMessage(BaseModel):
    """Individual chat messages"""
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    message = models.TextField(blank=True)
    attachment = models.FileField(upload_to='chat/attachments/%Y/%m/', null=True, blank=True)
    attachment_type = models.CharField(max_length=50, blank=True, choices=[
        ('image', 'Image'),
        ('file', 'File'),
        ('video', 'Video'),
        ('audio', 'Audio'),
    ])
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.sender.username}: {self.message[:50]}"

class ChatNotification(BaseModel):
    """Push notifications for chat"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_notifications')
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='notifications')
    is_read = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Notification for {self.user.username}"

class ChatTypingStatus(BaseModel):
    """Track who is typing"""
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='typing_status')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='typing_status')
    is_typing = models.BooleanField(default=False)
    last_typing_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['room', 'user']
    
    def __str__(self):
        return f"{self.user.username} typing in room {self.room.id}"

class VendorChatRoom(BaseModel):
    """Chat room specifically for vendors"""
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vendor_chats')
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_chats')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    last_message = models.TextField(blank=True)
    last_message_time = models.DateTimeField(auto_now=True)
    customer_unread = models.IntegerField(default=0)
    vendor_unread = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['vendor', 'customer', 'product']
        ordering = ['-last_message_time']
    
    def __str__(self):
        return f"Chat between {self.vendor.username} and {self.customer.username}"
    
    def get_last_message_preview(self):
        return self.last_message[:50] + '...' if len(self.last_message) > 50 else self.last_message
    
    def mark_read(self, user):
        """Mark messages as read for a specific user"""
        if user == self.vendor:
            self.vendor_unread = 0
        else:
            self.customer_unread = 0
        self.save()

class VendorChatMessage(BaseModel):
    """Messages in vendor chat rooms"""
    room = models.ForeignKey(VendorChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vendor_messages_sent')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    attachment = models.FileField(upload_to='chat/vendor_attachments/%Y/%m/', null=True, blank=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.sender.username}: {self.message[:50]}"
