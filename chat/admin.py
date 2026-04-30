from django.contrib import admin
from django.utils.html import format_html
from .models import ChatRoom, ChatMessage, ChatNotification, ChatTypingStatus, VendorChatRoom, VendorChatMessage

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'room_type', 'name', 'participant_count', 'is_active', 'updated_at']
    list_filter = ['room_type', 'is_active']
    filter_horizontal = ['participants']
    search_fields = ['name', 'participants__username']
    readonly_fields = ['created_at', 'updated_at']
    
    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Participants'

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'sender', 'message_preview', 'room', 'is_read', 'created_at']
    list_filter = ['is_read', 'is_edited', 'is_deleted']
    search_fields = ['message', 'sender__username']
    readonly_fields = ['created_at', 'read_at', 'delivered_at']
    
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message'

@admin.register(ChatNotification)
class ChatNotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'is_read', 'created_at']
    list_filter = ['is_read']
    search_fields = ['user__username']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(ChatTypingStatus)
class ChatTypingStatusAdmin(admin.ModelAdmin):
    list_display = ['room', 'user', 'is_typing', 'last_typing_at']
    list_filter = ['is_typing']
    search_fields = ['user__username', 'room__name']
    readonly_fields = ['last_typing_at', 'created_at', 'updated_at']

@admin.register(VendorChatRoom)
class VendorChatRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'vendor', 'customer', 'product', 'last_message_preview', 'vendor_unread', 'customer_unread', 'last_message_time']
    list_filter = ['is_active']
    search_fields = ['vendor__username', 'customer__username', 'product__name']
    readonly_fields = ['last_message_time', 'created_at', 'updated_at']
    
    def last_message_preview(self, obj):
        return obj.get_last_message_preview()
    last_message_preview.short_description = 'Last Message'

@admin.register(VendorChatMessage)
class VendorChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'sender', 'room', 'message_preview', 'is_read', 'created_at']
    list_filter = ['is_read']
    search_fields = ['message', 'sender__username']
    readonly_fields = ['created_at', 'read_at', 'updated_at']
    
    def message_preview(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    message_preview.short_description = 'Message'
