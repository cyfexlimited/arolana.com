from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import User, UserProfile, Address, NewsletterSubscriber, UserOTP, UserActivityLog, LoginAttempt, RegistrationMessageTemplate

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profile'
    
    def get_extra(self, request, obj=None, **kwargs):
        """Return the number of empty forms to display"""
        return 0 if obj and hasattr(obj, 'profile') else 1

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'username', 'user_type', 'is_active', 'email_verified', 'last_login', 'avatar_preview']
    list_filter = ['user_type', 'is_active', 'email_verified', 'is_staff']
    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['-date_joined']
    inlines = [UserProfileInline]
    
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'avatar', 'phone_number', 'country')}),
        ('Permissions', {'fields': ('user_type', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Verification', {'fields': ('email_verified', 'two_factor_enabled')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'last_seen')}),
        ('OAuth', {'fields': ('google_id', 'facebook_id'), 'classes': ('collapse',)}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'user_type'),
        }),
    )
    
    def avatar_preview(self, obj):
        if obj.avatar and obj.avatar.url:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />', obj.avatar.url)
        elif hasattr(obj, 'profile') and obj.profile.avatar:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />', obj.profile.avatar.url)
        else:
            avatar_url = f'https://ui-avatars.com/api/?name={obj.username}&background=0066b3&color=fff&size=50'
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%; object-fit: cover;" />', avatar_url)
    avatar_preview.short_description = 'Avatar'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('profile')
    
    def save_model(self, request, obj, form, change):
        """Save the user and create profile if it doesn't exist"""
        super().save_model(request, obj, form, change)
        if not hasattr(obj, 'profile'):
            UserProfile.objects.create(user=obj)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'avatar_preview', 'newsletter_subscription', 'promo_emails', 'order_updates', 'created_at']
    list_filter = ['newsletter_subscription', 'promo_emails', 'order_updates', 'marketing_emails']
    search_fields = ['user__email', 'user__username', 'company', 'location']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'avatar', 'bio', 'birth_date', 'website', 'location', 'company')
        }),
        ('Preferences', {
            'fields': ('newsletter_subscription', 'promo_emails', 'order_updates', 'marketing_emails')
        }),
        ('Social Links', {
            'fields': ('social_links',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def avatar_preview(self, obj):
        if obj.avatar and obj.avatar.url:
            return format_html('<img src="{}" width="40" height="40" style="border-radius: 50%; object-fit: cover;" />', obj.avatar.url)
        return format_html('<img src="https://ui-avatars.com/api/?name={}&background=0066b3&color=fff&size=40" width="40" height="40" style="border-radius: 50%;" />', obj.user.username)
    avatar_preview.short_description = 'Avatar'

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ['user', 'address_line1', 'city', 'country', 'is_default', 'address_type']
    list_filter = ['is_default', 'is_billing', 'is_shipping', 'address_type', 'country']
    search_fields = ['user__email', 'address_line1', 'city', 'postal_code']
    list_editable = ['is_default']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user',)
        }),
        ('Address Details', {
            'fields': ('address_line1', 'address_line2', 'city', 'state', 'postal_code', 'country', 'phone_number')
        }),
        ('Address Type', {
            'fields': ('address_type', 'is_default', 'is_billing', 'is_shipping')
        }),
    )

@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'subscribed_at', 'is_active', 'source']
    list_filter = ['is_active', 'subscribed_at', 'source']
    search_fields = ['email', 'name']
    list_editable = ['is_active']
    actions = ['activate_subscribers', 'deactivate_subscribers', 'export_subscribers']
    
    def activate_subscribers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} subscribers activated.")
    activate_subscribers.short_description = "Activate selected subscribers"
    
    def deactivate_subscribers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} subscribers deactivated.")
    deactivate_subscribers.short_description = "Deactivate selected subscribers"
    
    def export_subscribers(self, request, queryset):
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="newsletter_subscribers.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Email', 'Name', 'Subscribed Date', 'Status', 'Source'])
        
        for subscriber in queryset:
            writer.writerow([
                subscriber.email,
                subscriber.name,
                subscriber.subscribed_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Active' if subscriber.is_active else 'Inactive',
                subscriber.source
            ])
        return response
    export_subscribers.short_description = "Export selected subscribers"

@admin.register(UserOTP)
class UserOTPAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp_code', 'otp_type', 'is_used', 'attempts', 'created_at', 'expires_at']
    list_filter = ['otp_type', 'is_used']
    search_fields = ['user__email', 'otp_code', 'destination']
    readonly_fields = ['created_at', 'expires_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return True

@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action', 'ip_address', 'timestamp']
    list_filter = ['action', 'timestamp']
    search_fields = ['user__email', 'ip_address']  # Fixed: added equals sign
    readonly_fields = ['user', 'action', 'ip_address', 'user_agent', 'timestamp', 'details']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False

@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ['email', 'ip_address', 'attempt_count', 'is_locked', 'last_attempt', 'locked_until']
    list_filter = ['is_locked']
    search_fields = ['email', 'ip_address']
    readonly_fields = ['email', 'ip_address', 'attempt_count', 'last_attempt']
    
    actions = ['unlock_accounts']
    
    def unlock_accounts(self, request, queryset):
        for attempt in queryset:
            attempt.reset_attempts()
        self.message_user(request, f"{queryset.count()} accounts unlocked.")
    unlock_accounts.short_description = "Unlock selected accounts"
    
    def has_add_permission(self, request):
        return False

@admin.register(RegistrationMessageTemplate)
class RegistrationMessageTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'role', 'channel', 'subject', 'is_active', 'updated_at']
    list_filter = ['role', 'channel', 'is_active']
    search_fields = ['name', 'subject', 'body']
    list_editable = ['is_active']
    fieldsets = (
        ('Audience', {
            'fields': ('name', 'role', 'channel', 'is_active')
        }),
        ('Message', {
            'fields': ('subject', 'body', 'notification_title', 'notification_link')
        }),
    )
