from django.contrib import admin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .services import assign_nearest_rider, nearby_available_riders
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
from notifications.models import Notification


ADMIN_DELIVERY_LIVE_MAP_ASSETS = mark_safe("""
<style>
    .arolana-admin-live-map {
        border: 1px solid #dbe3ef;
        border-radius: 14px;
        overflow: hidden;
        background: #f8fafc;
        max-width: 920px;
    }

    .arolana-admin-live-map-canvas {
        height: 360px;
        min-height: 280px;
        width: 100%;
    }

    .arolana-admin-live-map-status {
        align-items: center;
        border-top: 1px solid #e5e7eb;
        color: #475569;
        display: flex;
        flex-wrap: wrap;
        font-size: 12px;
        font-weight: 700;
        gap: 8px;
        justify-content: space-between;
        padding: 10px 12px;
    }

    .arolana-admin-map-links {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .arolana-admin-map-links a {
        background: #eff6ff;
        border-radius: 999px;
        color: #1d4ed8;
        font-size: 12px;
        font-weight: 800;
        padding: 6px 10px;
        text-decoration: none;
    }

    .arolana-admin-map-empty {
        align-items: center;
        color: #64748b;
        display: flex;
        font-weight: 800;
        height: 100%;
        justify-content: center;
        padding: 20px;
        text-align: center;
    }
</style>
<script>
(function () {
    "use strict";
    if (window.ArolanaAdminDeliveryMapBooted) return;
    window.ArolanaAdminDeliveryMapBooted = true;

    function numberOrNull(value) {
        var parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }

    function markerIcon(color) {
        return window.L.divIcon({
            className: "",
            html: '<span style="display:block;width:18px;height:18px;border-radius:999px;background:' + color + ';border:3px solid #fff;box-shadow:0 6px 18px rgba(15,23,42,.25);"></span>',
            iconSize: [18, 18],
            iconAnchor: [9, 9]
        });
    }

    function setStatus(root, message) {
        var status = root.querySelector("[data-admin-map-status]");
        if (status) status.textContent = message;
    }

    function mapLink(lat, lng, label) {
        if (lat === null || lng === null) return "";
        return '<a target="_blank" rel="noopener" href="https://www.google.com/maps?q=' + encodeURIComponent(lat + "," + lng) + '">' + label + '</a>';
    }

    function fetchLocation(root) {
        return fetch(root.dataset.locationUrl, {
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" }
        }).then(function (response) {
            if (!response.ok) throw new Error("Could not load live location.");
            return response.json();
        });
    }

    function addOrMoveMarker(state, key, lat, lng, label, color) {
        if (lat === null || lng === null) return null;
        var point = [lat, lng];
        if (!state[key]) {
            state[key] = window.L.marker(point, { icon: markerIcon(color) }).addTo(state.map).bindPopup(label);
        } else {
            state[key].setLatLng(point);
            state[key].bindPopup(label);
        }
        return state[key].getLatLng();
    }

    function initAdminMap(root) {
        if (!window.L || root.dataset.mapReady === "true") return;
        root.dataset.mapReady = "true";

        var canvas = root.querySelector("[data-admin-map-canvas]");
        if (!canvas) return;

        var map = window.L.map(canvas, { scrollWheelZoom: false });
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "OpenStreetMap"
        }).addTo(map);

        var state = { map: map, pickup: null, dropoff: null, rider: null };

        function refresh() {
            fetchLocation(root).then(function (data) {
                var bounds = [];
                var pickupLat = numberOrNull(data.pickup.latitude);
                var pickupLng = numberOrNull(data.pickup.longitude);
                var dropoffLat = numberOrNull(data.dropoff.latitude);
                var dropoffLng = numberOrNull(data.dropoff.longitude);
                var riderLat = numberOrNull(data.rider.latitude);
                var riderLng = numberOrNull(data.rider.longitude);

                var pickup = addOrMoveMarker(state, "pickup", pickupLat, pickupLng, "Pickup: " + (data.pickup.label || data.pickup.address || ""), "#2563eb");
                var dropoff = addOrMoveMarker(state, "dropoff", dropoffLat, dropoffLng, "Drop-off: " + (data.dropoff.label || data.dropoff.address || ""), "#16a34a");
                var rider = addOrMoveMarker(state, "rider", riderLat, riderLng, "Rider: " + (data.rider.name || "No rider name"), "#f97316");

                [pickup, dropoff, rider].forEach(function (item) {
                    if (item) bounds.push(item);
                });
                if (bounds.length) {
                    map.fitBounds(window.L.latLngBounds(bounds).pad(0.22));
                } else {
                    map.setView([6.5244, 3.3792], 11);
                }

                var links = root.querySelector("[data-admin-map-links]");
                if (links) {
                    links.innerHTML = [
                        mapLink(pickupLat, pickupLng, "Open pickup"),
                        mapLink(dropoffLat, dropoffLng, "Open drop-off"),
                        mapLink(riderLat, riderLng, "Open rider")
                    ].filter(Boolean).join("");
                }
                setStatus(root, data.rider.last_location_at ? "Last rider ping: " + data.rider.last_location_at : "Waiting for rider live location.");
            }).catch(function (error) {
                setStatus(root, error.message || "Could not refresh live location.");
            });
        }

        refresh();
        window.setInterval(refresh, 15000);
    }

    function boot() {
        if (!window.L) {
            window.setTimeout(boot, 250);
            return;
        }
        document.querySelectorAll("[data-admin-delivery-live-map]").forEach(initAdminMap);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }
})();
</script>
""")


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
    list_display = ("__str__", "rider_type", "vehicle", "zone", "kyc_status", "profile_edit_status", "is_online", "is_available", "preferred_language", "completed_deliveries", "rating_avg")
    list_filter = ("rider_type", "kyc_status", "profile_edit_status", "is_online", "is_available", "is_suspended", "preferred_language", "vehicle", "zone")
    search_fields = ("user__email", "user__first_name", "user__last_name", "phone")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Account", {"fields": ("user", "rider_type", "phone", "emergency_phone", "about", "profile_photo", "dashboard_image")}),
        ("Vehicle & Zone", {"fields": ("vehicle", "zone")}),
        ("KYC Documents", {"fields": ("kyc_status", "id_document", "driver_license", "vehicle_document")}),
        ("Profile Edit Review", {"fields": ("profile_edit_status", "profile_edit_pending_data", "profile_edit_requested_at", "profile_edit_available_at")}),
        ("Payout Bank", {"fields": ("payout_bank_name", "payout_account_name", "payout_account_number", "payout_bank_country", "payout_preferred_currency")}),
        ("Live Operations", {"fields": ("is_online", "is_available", "is_suspended", "current_latitude", "current_longitude", "last_location_at")}),
        ("Preferences", {"fields": ("preferred_language", "notification_preferences")}),
        ("Performance", {"fields": ("completed_deliveries", "failed_deliveries", "rating_avg")}),
        ("Admin", {"fields": ("admin_notes", "created_at", "updated_at")}),
    )
    actions = ("approve_riders", "approve_profile_edits", "reject_profile_edits", "suspend_riders", "set_online", "set_offline")

    @admin.action(description="Approve selected riders")
    def approve_riders(self, request, queryset):
        for rider in queryset:
            if rider.profile_edit_status == "pending_admin_review" and rider.profile_edit_pending_data:
                rider.apply_pending_profile_edit()
            else:
                rider.kyc_status = RiderProfile.KYC_APPROVED
                rider.is_suspended = False
                rider.save(update_fields=["kyc_status", "is_suspended", "updated_at"])
            RiderWallet.objects.get_or_create(rider=rider)

    @admin.action(description="Approve pending rider profile edits")
    def approve_profile_edits(self, request, queryset):
        for rider in queryset.filter(profile_edit_status="pending_admin_review"):
            rider.apply_pending_profile_edit()
            RiderWallet.objects.get_or_create(rider=rider)

    @admin.action(description="Reject pending rider profile edits")
    def reject_profile_edits(self, request, queryset):
        queryset.filter(profile_edit_status="pending_admin_review").update(
            profile_edit_status="rejected",
            profile_edit_pending_data={},
            updated_at=timezone.now(),
        )

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
    list_display = ("tracking_code", "order", "status", "is_ready_for_rider", "rider", "delivery_fee", "rider_earning", "distance_km", "created_at")
    list_filter = ("status", "is_ready_for_rider", "zone", "requested_vehicle", "rider")
    search_fields = ("tracking_code", "order__order_number", "dropoff_name", "dropoff_phone", "dropoff_address")
    readonly_fields = (
        "tracking_code",
        "admin_live_map",
        "nearby_online_riders",
        "distance_km",
        "estimated_duration_minutes",
        "package_weight_kg",
        "base_fare",
        "distance_fee",
        "time_fee",
        "weight_fee",
        "service_fee",
        "express_fee",
        "surge_multiplier",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("order", "legacy_delivery", "rider", "zone", "requested_vehicle")
    inlines = (DeliveryStatusHistoryInline, DeliveryLocationPingInline)
    actions = ("release_to_riders", "hold_from_riders", "mark_assigned", "mark_picked_up", "mark_in_transit", "mark_delivered", "mark_failed")

    fieldsets = (
        ("Delivery", {"fields": ("order", "legacy_delivery", "tracking_code", "status", "is_ready_for_rider", "zone", "rider", "requested_vehicle")}),
        ("Live Map", {"fields": ("admin_live_map", "nearby_online_riders")}),
        ("Pickup", {"fields": ("pickup_name", "pickup_phone", "pickup_address", "pickup_latitude", "pickup_longitude")}),
        ("Drop-off", {"fields": ("dropoff_name", "dropoff_phone", "dropoff_address", "dropoff_latitude", "dropoff_longitude")}),
        ("Pricing", {"fields": (
            "distance_km",
            "estimated_duration_minutes",
            "package_weight_kg",
            "base_fare",
            "distance_fee",
            "time_fee",
            "weight_fee",
            "service_fee",
            "express_fee",
            "surge_multiplier",
            "delivery_fee",
            "rider_earning",
        )}),
        ("Proof and notes", {"fields": ("customer_note", "rider_note", "proof_of_delivery", "proof_note", "failed_reason")}),
        ("Timestamps", {"fields": ("accepted_at", "picked_up_at", "delivered_at", "created_at", "updated_at")}),
    )

    class Media:
        css = {
            "all": (
                "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
            )
        }
        js = (
            "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        )

    @admin.display(description="Live rider map")
    def admin_live_map(self, obj):
        if not obj or not obj.pk:
            return "Save this delivery first to view the live map."
        return format_html(
            '<div class="arolana-admin-live-map" data-admin-delivery-live-map data-location-url="{}">'
            '<div class="arolana-admin-live-map-canvas" data-admin-map-canvas>'
            '<div class="arolana-admin-map-empty">Loading delivery map...</div>'
            '</div>'
            '<div class="arolana-admin-live-map-status">'
            '<span data-admin-map-status>Waiting for rider live location.</span>'
            '<span class="arolana-admin-map-links" data-admin-map-links></span>'
            '</div>'
            '</div>{}',
            reverse("deliveries:api_admin_delivery_location", args=[obj.pk]),
            ADMIN_DELIVERY_LIVE_MAP_ASSETS,
        )

    @admin.display(description="Nearby online riders")
    def nearby_online_riders(self, obj):
        if not obj or not obj.pickup_latitude or not obj.pickup_longitude:
            return "Add pickup coordinates to rank nearby riders."
        ranked = nearby_available_riders(obj.pickup_latitude, obj.pickup_longitude, limit=5)
        if not ranked:
            return "No approved online riders with live location near this pickup."
        return format_html_join(
            "",
            "{} - {} km - {}<br>",
            ((rider, distance, rider.vehicle or "No vehicle") for rider, distance in ranked),
        )

    def _set_status(self, request, queryset, status):
        for delivery in queryset:
            delivery.set_status(status, actor=request.user)
            try:
                from order_robot.services import sync_from_live_delivery

                sync_from_live_delivery(delivery)
            except Exception:
                pass

    @admin.action(description="Mark assigned")
    def mark_assigned(self, request, queryset):
        self._set_status(request, queryset, DeliveryRequest.STATUS_ASSIGNED)

    @admin.action(description="Release selected deliveries to online riders")
    def release_to_riders(self, request, queryset):
        released = 0
        assigned = 0
        for delivery in queryset:
            if delivery.status not in {DeliveryRequest.STATUS_PENDING, DeliveryRequest.STATUS_ASSIGNED}:
                continue
            if not delivery.is_ready_for_rider:
                delivery.is_ready_for_rider = True
                delivery.save(update_fields=["is_ready_for_rider", "updated_at"])
                delivery.status_history.create(
                    status=delivery.status,
                    actor=request.user,
                    note="Admin released this delivery to riders.",
                )
                released += 1
            if not delivery.rider_id and assign_nearest_rider(delivery):
                assigned += 1
            try:
                from order_robot.services import sync_from_live_delivery

                sync_from_live_delivery(delivery)
            except Exception:
                pass
        self.message_user(request, f"{released} delivery request(s) released. {assigned} nearest rider assignment(s) made.")

    @admin.action(description="Hold selected deliveries from riders")
    def hold_from_riders(self, request, queryset):
        updated = queryset.update(is_ready_for_rider=False)
        self.message_user(request, f"{updated} delivery request(s) hidden from riders.")

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
    list_filter = ("status", "bank_name", "created_at", "paid_at")
    date_hierarchy = "created_at"
    search_fields = ("rider__user__email", "account_name", "account_number")
    actions = ("approve_payouts", "mark_paid")

    @admin.action(description="Approve payouts")
    def approve_payouts(self, request, queryset):
        for payout in queryset.filter(status=RiderPayout.STATUS_PENDING):
            payout.status = RiderPayout.STATUS_APPROVED
            payout.save(update_fields=["status", "updated_at"])
            Notification.send(
                user=payout.rider.user,
                notification_type="payment",
                title="Payout approved",
                message=f"Your rider payout of NGN {payout.amount} has been approved.",
                metadata={"payout_id": payout.id, "amount": str(payout.amount), "status": payout.status},
            )

    @admin.action(description="Mark payouts paid")
    def mark_paid(self, request, queryset):
        for payout in queryset.exclude(status=RiderPayout.STATUS_PAID):
            payout.mark_paid()
            Notification.send(
                user=payout.rider.user,
                notification_type="payment",
                title="Payout paid",
                message=f"Your rider payout of NGN {payout.amount} has been marked paid.",
                metadata={"payout_id": payout.id, "amount": str(payout.amount), "status": payout.status},
            )
