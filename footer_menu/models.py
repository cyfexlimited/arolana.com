from django.db import models
from core.models import BaseModel
from django_ckeditor_5.fields import CKEditor5Field

class FooterMenuCategory(BaseModel):
    """Categories like 'Shop', 'Support', 'Company', etc."""
    name = models.CharField(max_length=100, help_text="e.g., Shop, Support, Company")
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=50, blank=True, help_text="FontAwesome icon class")
    description = CKEditor5Field(blank=True, null=True, help_text="Description for this menu section (supports HTML formatting)")
    display_order = models.IntegerField(default=0, help_text="Order in footer")
    
    class Meta:
        verbose_name = "Footer Menu Category"
        verbose_name_plural = "Footer Menu Categories"
        ordering = ['display_order', 'name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

class FooterMenuItem(BaseModel):
    """Individual menu items like 'All Products', 'Help Center', etc."""
    category = models.ForeignKey(FooterMenuCategory, on_delete=models.CASCADE, related_name='items')
    title = models.CharField(max_length=100, help_text="Display text for the menu item")
    url = models.CharField(max_length=500, help_text="URL or path (e.g., /products/, /contact/)")
    open_in_new_tab = models.BooleanField(default=False, help_text="Open link in new tab")
    display_order = models.IntegerField(default=0, help_text="Order within category")
    is_external = models.BooleanField(default=False, help_text="Is this an external link?")
    
    class Meta:
        verbose_name = "Footer Menu Item"
        verbose_name_plural = "Footer Menu Items"
        ordering = ['category__display_order', 'display_order', 'title']
    
    def __str__(self):
        return f"{self.category.name} - {self.title}"
    
    def get_full_url(self):
        if self.is_external:
            return self.url
        return self.url
