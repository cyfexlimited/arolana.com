import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import BaseModel


class DeliveryZone(BaseModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80, unique=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Nigeria')
    center_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    center_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    radius_km = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('15.00'))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['country', 'state', 'city', 'name']

    def __str__(self):
        return self.name


class DeliveryVehicle(BaseModel):
    VEHICLE_BICYCLE = 'bicycle'
    VEHICLE_MOTORCYCLE = 'motorcycle'
    VEHICLE_CAR = 'car'
    VEHICLE_VAN = 'van'
    VEHICLE_TRUCK = 'truck'

    VEHICLE_TYPE_CHOICES = [
        (VEHICLE_BICYCLE, 'Bicycle'),
        (VEHICLE_MOTORCYCLE, 'Motorcycle'),
        (VEHICLE_CAR, 'Car'),
        (VEHICLE_VAN, 'Van'),
        (VEHICLE_TRUCK, 'Truck'),
    ]

    name = models.CharField(max_length=80)
    vehicle_type = models.CharField(max_length=30, choices=VEHICLE_TYPE_CHOICES, unique=True)
    base_capacity_kg = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('10.00'))
    base_speed_kmph = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('30.00'))
    base_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1000.00'))
    per_km_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('250.00'))
    rider_commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('70.00'))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class RiderProfile(BaseModel):
    RIDER_AROLANA = 'arolana'
    RIDER_VENDOR = 'vendor'
    RIDER_INDEPENDENT = 'independent'
    RIDER_ADMIN_ASSIGNED = 'admin_assigned'

    RIDER_TYPE_CHOICES = [
        (RIDER_AROLANA, 'Arolana Rider'),
        (RIDER_VENDOR, 'Vendor Rider'),
        (RIDER_INDEPENDENT, 'Independent Dispatch Rider'),
        (RIDER_ADMIN_ASSIGNED, 'Admin Assigned Rider'),
    ]

    KYC_PENDING = 'pending'
    KYC_APPROVED = 'approved'
    KYC_REJECTED = 'rejected'
    KYC_SUSPENDED = 'suspended'

    KYC_STATUS_CHOICES = [
        (KYC_PENDING, 'Pending Review'),
        (KYC_APPROVED, 'Approved'),
        (KYC_REJECTED, 'Rejected'),
        (KYC_SUSPENDED, 'Suspended'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='rider_profile')
    rider_type = models.CharField(max_length=30, choices=RIDER_TYPE_CHOICES, default=RIDER_INDEPENDENT)
    vehicle = models.ForeignKey(DeliveryVehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='riders')
    zone = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='riders')
    phone = models.CharField(max_length=50, blank=True)
    emergency_phone = models.CharField(max_length=50, blank=True)
    kyc_status = models.CharField(max_length=20, choices=KYC_STATUS_CHOICES, default=KYC_PENDING, db_index=True)
    id_document = models.FileField(upload_to='delivery/riders/id_documents/', blank=True, null=True)
    driver_license = models.FileField(upload_to='delivery/riders/licenses/', blank=True, null=True)
    vehicle_document = models.FileField(upload_to='delivery/riders/vehicle_documents/', blank=True, null=True)
    profile_photo = models.ImageField(upload_to='delivery/riders/photos/', blank=True, null=True)
    is_online = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    is_suspended = models.BooleanField(default=False)
    current_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)
    completed_deliveries = models.PositiveIntegerField(default=0)
    failed_deliveries = models.PositiveIntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('0.00'))
    admin_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['kyc_status', 'is_online', 'is_available']),
            models.Index(fields=['rider_type', 'kyc_status']),
        ]

    def __str__(self):
        return self.user.get_full_name() or self.user.email or self.user.username

    @property
    def can_accept_deliveries(self):
        return self.kyc_status == self.KYC_APPROVED and self.is_online and self.is_available and not self.is_suspended


class DeliveryPricingRule(BaseModel):
    name = models.CharField(max_length=120)
    zone = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='pricing_rules')
    vehicle = models.ForeignKey(DeliveryVehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='pricing_rules')
    base_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1000.00'))
    per_km_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('250.00'))
    minimum_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1500.00'))
    maximum_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    surge_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    rider_commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('70.00'))
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-is_default', 'name']

    def __str__(self):
        return self.name


class DeliveryRequest(BaseModel):
    STATUS_PENDING = 'pending'
    STATUS_ASSIGNED = 'assigned'
    STATUS_ACCEPTED = 'accepted'
    STATUS_ARRIVED_PICKUP = 'arrived_at_pickup'
    STATUS_PICKED_UP = 'picked_up'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_ARRIVED_CUSTOMER = 'arrived_at_customer'
    STATUS_DELIVERED = 'delivered'
    STATUS_CANCELLED = 'cancelled'
    STATUS_FAILED = 'failed'
    STATUS_RETURNED = 'returned'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ASSIGNED, 'Assigned'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_ARRIVED_PICKUP, 'Arrived at Pickup'),
        (STATUS_PICKED_UP, 'Picked Up'),
        (STATUS_IN_TRANSIT, 'In Transit'),
        (STATUS_ARRIVED_CUSTOMER, 'Arrived at Customer'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_RETURNED, 'Returned'),
    ]

    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='live_delivery_requests')
    legacy_delivery = models.OneToOneField('orders.DeliveryRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='live_delivery')
    zone = models.ForeignKey(DeliveryZone, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    rider = models.ForeignKey(RiderProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='deliveries')
    requested_vehicle = models.ForeignKey(DeliveryVehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_requests')
    tracking_code = models.CharField(max_length=32, unique=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    pickup_name = models.CharField(max_length=160, blank=True)
    pickup_phone = models.CharField(max_length=50, blank=True)
    pickup_address = models.TextField()
    pickup_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    pickup_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    dropoff_name = models.CharField(max_length=160, blank=True)
    dropoff_phone = models.CharField(max_length=50, blank=True)
    dropoff_address = models.TextField()
    dropoff_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    dropoff_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    estimated_duration_minutes = models.PositiveIntegerField(default=0)
    package_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    base_fare = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    distance_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    time_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    weight_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    express_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    surge_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    rider_earning = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_ready_for_rider = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Show this delivery to riders only after vendor/admin confirms it is ready for pickup.',
    )
    customer_note = models.TextField(blank=True)
    rider_note = models.TextField(blank=True)
    proof_of_delivery = models.ImageField(upload_to='delivery/proofs/', blank=True, null=True)
    proof_note = models.TextField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['tracking_code']),
            models.Index(fields=['rider', 'status']),
        ]

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = f"ADL-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tracking_code} - {self.order.order_number}"

    def set_status(self, status, actor=None, note='', latitude=None, longitude=None, location_label=''):
        if status not in dict(self.STATUS_CHOICES):
            raise ValueError(f"Unknown delivery status: {status}")

        now = timezone.now()
        first_delivery_completion = status == self.STATUS_DELIVERED and not self.delivered_at
        self.status = status
        update_fields = ['status', 'updated_at']

        if status == self.STATUS_ACCEPTED and not self.accepted_at:
            self.accepted_at = now
            update_fields.append('accepted_at')
        elif status == self.STATUS_PICKED_UP and not self.picked_up_at:
            self.picked_up_at = now
            update_fields.append('picked_up_at')
        elif status == self.STATUS_DELIVERED and not self.delivered_at:
            self.delivered_at = now
            update_fields.append('delivered_at')

        self.save(update_fields=update_fields)
        DeliveryStatusHistory.objects.create(
            delivery=self,
            status=status,
            actor=actor,
            note=note,
            latitude=latitude,
            longitude=longitude,
            location_label=location_label,
        )
        self.sync_legacy_delivery_status()
        if self.rider_id:
            busy_statuses = {
                self.STATUS_ASSIGNED,
                self.STATUS_ACCEPTED,
                self.STATUS_ARRIVED_PICKUP,
                self.STATUS_PICKED_UP,
                self.STATUS_IN_TRANSIT,
                self.STATUS_ARRIVED_CUSTOMER,
            }
            terminal_statuses = {
                self.STATUS_DELIVERED,
                self.STATUS_CANCELLED,
                self.STATUS_FAILED,
                self.STATUS_RETURNED,
            }
            if status in busy_statuses and self.rider.is_available:
                self.rider.is_available = False
                self.rider.save(update_fields=['is_available', 'updated_at'])
            elif status in terminal_statuses and not self.rider.is_available and not self.rider.is_suspended:
                self.rider.is_available = True
                self.rider.save(update_fields=['is_available', 'updated_at'])
        if first_delivery_completion and self.rider_id:
            self.credit_rider_wallet()

    def sync_legacy_delivery_status(self):
        if not self.legacy_delivery_id:
            return

        legacy_status_map = {
            self.STATUS_PENDING: 'pending_assignment',
            self.STATUS_ASSIGNED: 'assigned',
            self.STATUS_ACCEPTED: 'assigned',
            self.STATUS_ARRIVED_PICKUP: 'assigned',
            self.STATUS_PICKED_UP: 'picked_up',
            self.STATUS_IN_TRANSIT: 'in_transit',
            self.STATUS_ARRIVED_CUSTOMER: 'in_transit',
            self.STATUS_DELIVERED: 'delivered',
            self.STATUS_CANCELLED: 'cancelled',
            self.STATUS_FAILED: 'failed',
            self.STATUS_RETURNED: 'failed',
        }
        legacy_status = legacy_status_map.get(self.status)
        if legacy_status:
            self.legacy_delivery.tracking_status = legacy_status
            self.legacy_delivery.delivery_fee = self.delivery_fee
            self.legacy_delivery.save(update_fields=['tracking_status', 'delivery_fee', 'updated_at'])

    @property
    def latest_location(self):
        return self.location_pings.order_by('-created_at').first()

    def credit_rider_wallet(self):
        wallet, _created = RiderWallet.objects.get_or_create(rider=self.rider)
        wallet.balance = wallet.balance + self.rider_earning
        wallet.total_earned = wallet.total_earned + self.rider_earning
        wallet.save(update_fields=['balance', 'total_earned', 'updated_at'])
        self.rider.completed_deliveries = self.rider.completed_deliveries + 1
        self.rider.save(update_fields=['completed_deliveries', 'updated_at'])


class DeliveryStatusHistory(BaseModel):
    delivery = models.ForeignKey(DeliveryRequest, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=30, choices=DeliveryRequest.STATUS_CHOICES)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_status_updates')
    note = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_label = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.delivery.tracking_code} - {self.get_status_display()}"


class DeliveryLocationPing(BaseModel):
    delivery = models.ForeignKey(DeliveryRequest, on_delete=models.CASCADE, related_name='location_pings')
    rider = models.ForeignKey(RiderProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='location_pings')
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    heading = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    speed_kmph = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    accuracy_meters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['delivery', '-created_at'])]


class RiderWallet(BaseModel):
    rider = models.OneToOneField(RiderProfile, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    pending_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_earned = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total_paid_out = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.rider} wallet"


class RiderPayout(BaseModel):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_PAID = 'paid'
    STATUS_REJECTED = 'rejected'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_PAID, 'Paid'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    rider = models.ForeignKey(RiderProfile, on_delete=models.CASCADE, related_name='payouts')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    bank_name = models.CharField(max_length=120, blank=True)
    account_name = models.CharField(max_length=160, blank=True)
    account_number = models.CharField(max_length=40, blank=True)
    admin_note = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def mark_paid(self):
        self.status = self.STATUS_PAID
        self.paid_at = timezone.now()
        self.save(update_fields=['status', 'paid_at', 'updated_at'])

    def __str__(self):
        return f"{self.rider} - {self.amount}"
