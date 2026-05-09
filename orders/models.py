from django.db import models
from core.models import BaseModel
from accounts.models import User
from products.models import Product, ProductVariant, Accessory

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
    accessory = models.ForeignKey(Accessory, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    price_at_add = models.DecimalField(max_digits=10, decimal_places=2)
    
    def save(self, *args, **kwargs):
        if not self.price_at_add:
            if self.product:
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
    order_number = models.CharField(max_length=20, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    shipping_address = models.TextField()
    billing_address = models.TextField()
    payment_method = models.CharField(max_length=50, default='stripe')
    payment_status = models.CharField(max_length=20, default='pending')
    tracking_number = models.CharField(max_length=100, blank=True)
    
    def save(self, *args, **kwargs):
        if not self.order_number:
            import random
            self.order_number = f"ARO-{random.randint(100000, 999999)}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Order #{self.order_number}"

class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    accessory = models.ForeignKey(Accessory, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    
    def save(self, *args, **kwargs):
        self.subtotal = self.price * self.quantity
        super().save(*args, **kwargs)
    
    @property
    def item_name(self):
        if self.product:
            return self.product.name
        elif self.variant:
            return f"{self.variant.product.name} - {self.variant.value}"
        elif self.accessory:
            return self.accessory.name
        return "Item"
    
    def __str__(self):
        return f"{self.quantity} x {self.item_name}"