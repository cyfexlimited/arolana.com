from django.contrib import admin
from django.utils import timezone

from .models import (
    DeliveryLocationPing,
    DeliveryPricingRule,
    DeliveryRequest,
    DeliveryStatusHistory,
    DeliveryVehicle,
    DeliveryZone,
    RiderPayout,
    RiderProfile,
    RiderWallet,
)


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "country", "radius_km", "is_active")
    list_filter = ("country", "state", "is_active")
    search_fields = ("name", "code", "city", "state", "country")
    prepopulated_fields = {"code": ("name",)}


@admin.register(DeliveryVehicle)
class DeliveryVehicleAdmin(admin.ModelAdmin):
    list_display = ("name", "vehicle_type", "base_capacity_kg", "base_speed_kmph", "base_fee", "per_km_fee", "is_active")
    list_filter = ("vehicle_type", "is_active")
    search_fields = ("name", "vehicle_type")


@admin.register(DeliveryPricingRule)
class DeliveryPricingRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "zone", "vehicle", "base_fee", "per_km_fee", "minimum_fee", "surge_multiplier", "is_default", "is_active")
    list_filter = ("is_default", "is_active", "zone", "vehicle")
    search_fields = ("name", "zone__name", "vehicle__name")


@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "rider_type", "vehicle", "zone", "kyc_status", "is_online", "is_available", "completed_deliveries", "rating_avg")
    list_filter = ("rider_type", "kyc_status", "is_online", "is_available", "is_suspended", "vehicle", "zone")
    search_fields = ("user__email", "user__first_name", "user__last_name", "phone")
    actions = ("approve_riders", "suspend_riders", "set_online", "set_offline")

    @admin.action(description="Approve selected riders")
    def approve_riders(self, request, queryset):
        queryset.update(kyc_status=RiderProfile.KYC_APPROVED, is_suspended=False, updated_at=timezone.now())
        for rider in queryset:
            RiderWallet.objects.get_or_create(rider=rider)

    @admin.action(description="Suspend selected riders")
    def suspend_riders(self, request, queryset):
        queryset.update(kyc_status=RiderProfile.KYC_SUSPENDED, is_online=False, is_suspended=True, updated_at=timezone.now())

    @admin.action(description="Set selected riders online")
    def set_online(self, request, queryset):
        queryset.filter(kyc_status=RiderProfile.KYC_APPROVED, is_suspended=False).update(is_online=True, updated_at=timezone.now())

    @admin.action(description="Set selected riders offline")
    def set_offline(self, request, queryset):
        queryset.update(is_online=False, updated_at=timezone.now())


class DeliveryStatusHistoryInline(admin.TabularInline):
    model = DeliveryStatusHistory
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("status", "actor", "note", "latitude", "longitude", "location_label", "created_at")


class DeliveryLocationPingInline(admin.TabularInline):
    model = DeliveryLocationPing
    extra = 0
    readonly_fields = ("latitude", "longitude", "speed_kmph", "accuracy_meters", "created_at")
    fields = ("rider", "latitude", "longitude", "speed_kmph", "accuracy_meters", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DeliveryRequest)
class DeliveryRequestAdmin(admin.ModelAdmin):
    list_display = ("tracking_code", "order", "status", "rider", "delivery_fee", "rider_earning", "distance_km", "created_at")
    list_filter = ("status", "zone", "requested_vehicle", "rider")
    search_fields = ("tracking_code", "order__order_number", "dropoff_name", "dropoff_phone", "dropoff_address")
    readonly_fields = ("tracking_code", "distance_km", "estimated_duration_minutes", "created_at", "updated_at")
    autocomplete_fields = ("order", "legacy_delivery", "rider", "zone", "requested_vehicle")
    inlines = (DeliveryStatusHistoryInline, DeliveryLocationPingInline)
    actions = ("mark_assigned", "mark_picked_up", "mark_in_transit", "mark_delivered", "mark_failed")

    fieldsets = (
        ("Delivery", {"fields": ("order", "legacy_delivery", "tracking_code", "status", "zone", "rider", "requested_vehicle")}),
        ("Pickup", {"fields": ("pickup_name", "pickup_phone", "pickup_address", "pickup_latitude", "pickup_longitude")}),
        ("Drop-off", {"fields": ("dropoff_name", "dropoff_phone", "dropoff_address", "dropoff_latitude", "dropoff_longitude")}),
        ("Pricing", {"fields": ("distance_km", "estimated_duration_minutes", "delivery_fee", "rider_earning")}),
        ("Proof and notes", {"fields": ("customer_note", "rider_note", "proof_of_delivery", "proof_note", "failed_reason")}),
        ("Timestamps", {"fields": ("accepted_at", "picked_up_at", "delivered_at", "created_at", "updated_at")}),
    )

    def _set_status(self, request, queryset, status):
        for delivery in queryset:
            delivery.set_status(status, actor=request.user)

    @admin.action(description="Mark assigned")
    def mark_assigned(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_ASSIGNED)

    @admin.action(description="Mark picked up")
    def mark_picked_up(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_PICKED_UP)

    @admin.action(description="Mark in transit")
    def mark_in_transit(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_IN_TRANSIT)

    @admin.action(description="Mark delivered")
    def mark_delivered(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_DELIVERED)

    @admin.action(description="Mark failed")
    def mark_failed(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_FAILED)


@admin.register(DeliveryStatusHistory)
class DeliveryStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("delivery", "status", "actor", "location_label", "created_at")
    list_filter = ("status",)
    search_fields = ("delivery__tracking_code", "delivery__order__order_number", "note", "location_label")


@admin.register(DeliveryLocationPing)
class DeliveryLocationPingAdmin(admin.ModelAdmin):
    list_display = ("delivery", "rider", "latitude", "longitude", "speed_kmph", "created_at")
    list_filter = ("rider",)
    search_fields = ("delivery__tracking_code", "delivery__order__order_number", "rider__user__email")


@admin.register(RiderWallet)
class RiderWalletAdmin(admin.ModelAdmin):
    list_display = ("rider", "balance", "pending_balance", "total_earned", "total_paid_out")
    search_fields = ("rider__user__email", "rider__phone")


@admin.register(RiderPayout)
class RiderPayoutAdmin(admin.ModelAdmin):
    list_display = ("rider", "amount", "status", "bank_name", "account_number", "created_at", "paid_at")
    list_filter = ("status", "bank_name")
    search_fields = ("rider__user__email", "account_name", "account_number")
    actions = ("approve_payouts", "mark_paid")

    @admin.action(description="Approve payouts")
    def approve_payouts(self, request, queryset):
        queryset.filter(status=RiderPayout.STATUS_PENDING).update(status=RiderPayout.STATUS_APPROVED, updated_at=timezone.now())

    @admin.action(description="Mark payouts paid")
    def mark_paid(self, request, queryset):
        for payout in queryset.exclude(status=RiderPayout.STATUS_PAID):
            payout.mark_paid()
