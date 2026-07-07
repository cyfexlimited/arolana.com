from django.db import models
from core.models import BaseModel
from accounts.models import User
from products.models import Product, ProductVariant, Accessory, VendorProductOffer
from decimal import Decimal
from django.utils import timezone
import uuid

class Cart(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    is_active = models.BooleanField(default=True)
    
    @property
    def total_items(self):
        return self.items.aggregate(total=models.Sum('quantity'))['total'] or 0
    
    @property
    def subtotal(self):
        return sum(item.subtotal for item in self.items.all())
    
    @property
    def total(self):
        return self.subtotal
    
    def __str__(self):
        return f"Cart #{self.id} - {self.user.username}"

class CartItem(BaseModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    vendor_offer = models.ForeignKey(VendorProductOffer, on_delete=models.SET_NULL, null=True, blank=True)
    accessory = models.ForeignKey(Accessory, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    price_at_add = models.DecimalField(max_digits=10, decimal_places=2)
    
    def save(self, *args, **kwargs):
        if not self.price_at_add:
            if self.vendor_offer:
                self.product = self.vendor_offer.product
                self.variant = self.vendor_offer.variant
                self.price_at_add = self.vendor_offer.final_price
            elif self.product:
                self.price_at_add = self.product.price
            elif self.variant:
                self.price_at_add = self.variant.product.price + self.variant.price_adjustment
            elif self.accessory:
                self.price_at_add = self.accessory.price
        super().save(*args, **kwargs)
    
    @property
    def subtotal(self):
        return self.price_at_add * self.quantity
    
    @property
    def item_name(self):
        if self.vendor_offer:
            return self.vendor_offer.display_name
        if self.product:
            return self.product.name
        elif self.variant:
            return f"{self.variant.product.name} - {self.variant.value}"
        elif self.accessory:
            return self.accessory.name
        return "Item"
    
    def __str__(self):
        return f"{self.quantity} x {self.item_name}"

class Order(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')

    # Customer contact fields for mobile/guest checkout.
    # These make customer details visible and searchable directly on the order.
    customer_name = models.CharField(max_length=160, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)

    order_number = models.CharField(max_length=20, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    shipping_address = models.TextField()
    billing_address = models.TextField()
    payment_method = models.CharField(max_length=50, default='paystack')
    payment_status = models.CharField(max_length=20, default='pending')
    tracking_number = models.CharField(max_length=100, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            import random
            self.order_number = f"ARO-{random.randint(100000, 999999)}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Order #{self.order_number}"


class DeliveryProvider(BaseModel):
    """Delivery partner or dispatch method available at checkout."""

    PROVIDER_AROLANA_DRIVER = 'arolana_driver'
    PROVIDER_MANUAL_DISPATCH = 'manual_dispatch'
    PROVIDER_UBER_DIRECT = 'uber_direct'
    PROVIDER_DHL = 'dhl'
    PROVIDER_GIG_LOGISTICS = 'gig_logistics'
    PROVIDER_VENDOR_PICKUP = 'vendor_pickup'
    PROVIDER_OTHER = 'other'

    PROVIDER_TYPE_CHOICES = [
        (PROVIDER_AROLANA_DRIVER, 'Arolana Driver'),
        (PROVIDER_MANUAL_DISPATCH, 'Manual Dispatch'),
        (PROVIDER_UBER_DIRECT, 'Uber Direct'),
        (PROVIDER_DHL, 'DHL'),
        (PROVIDER_GIG_LOGISTICS, 'GIG Logistics'),
        (PROVIDER_VENDOR_PICKUP, 'Pickup from Vendor'),
        (PROVIDER_OTHER, 'Other Provider'),
    ]

    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80, unique=True)
    provider_type = models.CharField(max_length=30, choices=PROVIDER_TYPE_CHOICES, default=PROVIDER_AROLANA_DRIVER)
    description = models.TextField(blank=True)
    base_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    supports_tracking = models.BooleanField(default=True)
    supports_driver_assignment = models.BooleanField(default=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    contact_email = models.EmailField(blank=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'provider_type']),
        ]

    def __str__(self):
        return self.name


class DeliveryRequest(BaseModel):
    """Track order delivery assignment, rider status, and customer tracking."""

    SERVICE_STANDARD = 'standard'
    SERVICE_EXPRESS = 'express'
    SERVICE_AROLANA_DISPATCH = 'arolana_dispatch'
    SERVICE_UBER_DIRECT = 'uber_direct'
    SERVICE_PICKUP_VENDOR = 'pickup_from_vendor'

    SERVICE_LEVEL_CHOICES = [
        (SERVICE_STANDARD, 'Standard Delivery'),
        (SERVICE_EXPRESS, 'Express Delivery'),
        (SERVICE_AROLANA_DISPATCH, 'Arolana Dispatch'),
        (SERVICE_UBER_DIRECT, 'Uber Direct'),
        (SERVICE_PICKUP_VENDOR, 'Pickup from Vendor'),
    ]

    STATUS_PENDING_ASSIGNMENT = 'pending_assignment'
    STATUS_ASSIGNED = 'assigned'
    STATUS_ACCEPTED = 'accepted'
    STATUS_PICKED_UP = 'picked_up'
    STATUS_IN_TRANSIT = 'in_transit'
    STATUS_DELIVERED = 'delivered'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    TRACKING_STATUS_CHOICES = [
        (STATUS_PENDING_ASSIGNMENT, 'Pending Assignment'),
        (STATUS_ASSIGNED, 'Assigned to Driver'),
        (STATUS_ACCEPTED, 'Accepted by Driver'),
        (STATUS_PICKED_UP, 'Picked Up'),
        (STATUS_IN_TRANSIT, 'In Transit'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='delivery_requests')
    provider = models.ForeignKey(DeliveryProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_requests')
    service_level = models.CharField(max_length=30, choices=SERVICE_LEVEL_CHOICES, default=SERVICE_STANDARD)
    pickup_address = models.TextField(blank=True)
    dropoff_address = models.TextField()
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tracking_status = models.CharField(max_length=30, choices=TRACKING_STATUS_CHOICES, default=STATUS_PENDING_ASSIGNMENT, db_index=True)
    tracking_code = models.CharField(max_length=32, unique=True, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    driver_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_assignments')
    driver_name = models.CharField(max_length=120, blank=True)
    driver_phone = models.CharField(max_length=50, blank=True)
    latest_location = models.CharField(max_length=255, blank=True)
    latest_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    latest_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tracking_status', '-created_at']),
            models.Index(fields=['service_level', '-created_at']),
            models.Index(fields=['tracking_code']),
        ]

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            self.tracking_code = f"ADR-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def assign_driver(self, driver_user=None, driver_name='', driver_phone=''):
        self.driver_user = driver_user or self.driver_user
        self.driver_name = driver_name or self.driver_name
        self.driver_phone = driver_phone or self.driver_phone
        self.tracking_status = self.STATUS_ASSIGNED
        self.save(update_fields=['driver_user', 'driver_name', 'driver_phone', 'tracking_status', 'updated_at'])

    def mark_accepted(self):
        self.tracking_status = self.STATUS_ACCEPTED
        self.accepted_at = timezone.now()
        self.save(update_fields=['tracking_status', 'accepted_at', 'updated_at'])

    def mark_picked_up(self):
        self.tracking_status = self.STATUS_PICKED_UP
        self.picked_up_at = timezone.now()
        self.save(update_fields=['tracking_status', 'picked_up_at', 'updated_at'])

    def mark_in_transit(self):
        self.tracking_status = self.STATUS_IN_TRANSIT
        self.save(update_fields=['tracking_status', 'updated_at'])

    def mark_delivered(self):
        self.tracking_status = self.STATUS_DELIVERED
        self.delivered_at = timezone.now()
        self.save(update_fields=['tracking_status', 'delivered_at', 'updated_at'])

    def __str__(self):
        return f"{self.tracking_code} - {self.order.order_number}"


class DeliveryQuoteRequest(BaseModel):
    """Admin-negotiated delivery quote for DHL, GIG, and special routes."""

    STATUS_PENDING = 'pending'
    STATUS_REVIEWING = 'reviewing'
    STATUS_QUOTED = 'quoted'
    STATUS_ACCEPTED = 'accepted'
    STATUS_DECLINED = 'declined'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Admin Review'),
        (STATUS_REVIEWING, 'Admin Reviewing'),
        (STATUS_QUOTED, 'Quote Sent'),
        (STATUS_ACCEPTED, 'Customer Accepted'),
        (STATUS_DECLINED, 'Customer Declined'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    ROUTE_DOMESTIC = 'domestic'
    ROUTE_BULKY = 'bulky'
    ROUTE_IMPORT = 'international_import'
    ROUTE_EXPORT = 'international_export'
    ROUTE_OTHER = 'other'

    ROUTE_TYPE_CHOICES = [
        (ROUTE_DOMESTIC, 'Domestic / Interstate'),
        (ROUTE_BULKY, 'Bulky or Fragile Item'),
        (ROUTE_IMPORT, 'International Import'),
        (ROUTE_EXPORT, 'International Export'),
        (ROUTE_OTHER, 'Other Special Route'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_quote_requests')
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_quote_requests')
    provider = models.ForeignKey(DeliveryProvider, on_delete=models.SET_NULL, null=True, blank=True, related_name='quote_requests')
    session_key = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    service_level = models.CharField(max_length=30, choices=DeliveryRequest.SERVICE_LEVEL_CHOICES, default=DeliveryRequest.SERVICE_STANDARD)
    route_type = models.CharField(max_length=40, choices=ROUTE_TYPE_CHOICES, default=ROUTE_DOMESTIC)
    customer_name = models.CharField(max_length=160, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    pickup_address = models.TextField(blank=True)
    dropoff_address = models.TextField(blank=True)
    package_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    package_details = models.TextField(blank=True)
    admin_quote_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    admin_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['route_type', '-created_at']),
        ]

    def __str__(self):
        provider_name = self.provider.name if self.provider else 'Delivery provider'
        return f"{provider_name} quote for {self.customer_email or self.customer_name or 'customer'}"

class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    vendor_offer = models.ForeignKey(VendorProductOffer, on_delete=models.SET_NULL, null=True, blank=True)
    accessory = models.ForeignKey(Accessory, on_delete=models.SET_NULL, null=True, blank=True)
    vendor_id_snapshot = models.PositiveIntegerField(null=True, blank=True)
    vendor_name_snapshot = models.CharField(max_length=220, blank=True)
    product_name_snapshot = models.CharField(max_length=260, blank=True)
    variant_name_snapshot = models.CharField(max_length=220, blank=True)
    seller_sku_snapshot = models.CharField(max_length=120, blank=True)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    
    def save(self, *args, **kwargs):
        if self.vendor_offer_id:
            self.product = self.vendor_offer.product
            self.variant = self.vendor_offer.variant
            if not self.vendor_id_snapshot:
                self.vendor_id_snapshot = self.vendor_offer.vendor_id
            if not self.vendor_name_snapshot:
                self.vendor_name_snapshot = self.vendor_offer.vendor_display_name
            if not self.product_name_snapshot:
                self.product_name_snapshot = self.vendor_offer.product.name
            if not self.variant_name_snapshot and self.vendor_offer.variant_id:
                self.variant_name_snapshot = self.vendor_offer.variant.value
            if not self.seller_sku_snapshot:
                self.seller_sku_snapshot = self.vendor_offer.seller_sku
        self.subtotal = self.price * self.quantity
        super().save(*args, **kwargs)
    
    @property
    def item_name(self):
        if self.product_name_snapshot:
            return self.product_name_snapshot
        if self.vendor_offer:
            return self.vendor_offer.display_name
        if self.product:
            return self.product.name
        elif self.variant:
            return f"{self.variant.product.name} - {self.variant.value}"
        elif self.accessory:
            return self.accessory.name
        return "Item"
    
    def __str__(self):
        return f"{self.quantity} x {self.item_name}"


class MobilePushToken(BaseModel):
    """Expo push token for Arolana mobile app notifications."""

    phone_number = models.CharField(max_length=50, db_index=True)
    email = models.EmailField(blank=True)
    expo_push_token = models.CharField(max_length=255, unique=True)
    device_name = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)
    last_registered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-last_registered_at']
        indexes = [
            models.Index(fields=['phone_number', 'is_active']),
            models.Index(fields=['email', 'is_active']),
        ]

    def __str__(self):
        return f"{self.phone_number} - {self.device_name or self.platform or 'mobile'}"


from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


@receiver(pre_save, sender=DeliveryRequest)
def remember_previous_delivery_state(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_tracking_status = None
        instance._previous_latest_location = None
        instance._previous_latest_latitude = None
        instance._previous_latest_longitude = None
        return

    previous = sender.objects.filter(pk=instance.pk).only(
        'tracking_status',
        'latest_location',
        'latest_latitude',
        'latest_longitude',
    ).first()
    instance._previous_tracking_status = previous.tracking_status if previous else None
    instance._previous_latest_location = previous.latest_location if previous else None
    instance._previous_latest_latitude = previous.latest_latitude if previous else None
    instance._previous_latest_longitude = previous.latest_longitude if previous else None


@receiver(post_save, sender=DeliveryRequest)
def send_delivery_tracking_notifications(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    try:
        from .delivery_notifications import handle_delivery_saved

        handle_delivery_saved(instance, created=created)
    except Exception:
        return
