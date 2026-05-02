from django.db import models
from core.models import BaseModel
from accounts.models import User
from vendors.models import VendorProfile

class KYCDocument(BaseModel):
    """KYC Documents for vendors"""
    DOCUMENT_TYPES = [
        ('business_registration', 'Business Registration Certificate'),
        ('tax_id', 'Tax ID / VAT Certificate'),
        ('bank_statement', 'Bank Account Statement'),
        ('utility_bill', 'Utility Bill (Address Proof)'),
        ('id_proof', 'Government ID Proof'),
        ('product_license', 'Product License/Certification'),
        ('other', 'Other Document'),
    ]
    
    vendor = models.ForeignKey(VendorProfile, on_delete=models.CASCADE, related_name='kyc_documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    document_file = models.FileField(upload_to='kyc/documents/%Y/%m/')
    document_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    
    description = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    # Verification
    VERIFICATION_STATUS = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_STATUS, default='pending')
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_documents')
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return f"{self.vendor.store_name} - {self.get_document_type_display()}"

class KYCRecord(BaseModel):
    """Complete KYC Record for a vendor"""
    vendor = models.OneToOneField(VendorProfile, on_delete=models.CASCADE, related_name='kyc_record')
    
    # Business Information
    legal_business_name = models.CharField(max_length=200)
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    vat_number = models.CharField(max_length=100, blank=True)
    
    # Address
    business_address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    
    # Contact
    business_phone = models.CharField(max_length=50)
    business_email = models.EmailField()
    website = models.URLField(blank=True)
    
    # Business Details
    business_type = models.CharField(max_length=100, choices=[
        ('sole_proprietorship', 'Sole Proprietorship'),
        ('partnership', 'Partnership'),
        ('llc', 'Limited Liability Company (LLC)'),
        ('corporation', 'Corporation'),
        ('non_profit', 'Non-Profit'),
        ('other', 'Other'),
    ], default='sole_proprietorship')
    
    year_established = models.IntegerField(null=True, blank=True)
    number_of_employees = models.IntegerField(null=True, blank=True)
    estimated_annual_revenue = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    
    # Bank Account
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)
    bank_routing_number = models.CharField(max_length=100, blank=True)
    iban = models.CharField(max_length=100, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    
    # Authorized Person
    authorized_person_name = models.CharField(max_length=200)
    authorized_person_title = models.CharField(max_length=100)
    authorized_person_email = models.EmailField()
    authorized_person_phone = models.CharField(max_length=50)
    
    # KYC Status
    KYC_STATUS = [
        ('not_started', 'Not Started'),
        ('pending', 'Pending Verification'),
        ('in_review', 'Under Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended'),
    ]
    kyc_status = models.CharField(max_length=20, choices=KYC_STATUS, default='not_started')
    
    # Risk Assessment
    risk_score = models.IntegerField(default=0, help_text="Risk score 0-100")
    risk_level = models.CharField(max_length=20, choices=[
        ('low', 'Low Risk'),
        ('medium', 'Medium Risk'),
        ('high', 'High Risk'),
    ], default='low')
    
    # Review
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='kyc_reviews')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Compliance
    pep_check = models.BooleanField(default=False, help_text="Politically Exposed Person check passed")
    sanctions_check = models.BooleanField(default=False, help_text="Sanctions list check passed")
    adverse_media_check = models.BooleanField(default=False, help_text="Adverse media check passed")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"KYC for {self.vendor.store_name} - {self.kyc_status}"
    
    def is_complete(self):
        """Check if all required fields are filled"""
        required_fields = ['legal_business_name', 'business_address', 'city', 'country', 
                          'business_phone', 'business_email', 'authorized_person_name', 
                          'authorized_person_email', 'authorized_person_phone']
        for field in required_fields:
            if not getattr(self, field):
                return False
        return True
    
    def calculate_risk_score(self):
        """Calculate risk score based on various factors"""
        score = 0
        # Higher risk for certain business types
        if self.business_type in ['sole_proprietorship', 'partnership']:
            score += 20
        # Higher risk for new businesses
        if self.year_established and (timezone.now().year - self.year_established) < 2:
            score += 15
        # Risk based on country (simplified)
        high_risk_countries = ['', '']  # Add high-risk country codes
        if self.country in high_risk_countries:
            score += 30
        # Industry risk (can be expanded)
        # Score based on document verification status
        pending_docs = self.vendor.kyc_documents.filter(verification_status='pending').count()
        if pending_docs > 0:
            score += 10 * min(pending_docs, 5)
        return min(score, 100)
    
    def update_risk_score(self):
        self.risk_score = self.calculate_risk_score()
        if self.risk_score >= 60:
            self.risk_level = 'high'
        elif self.risk_score >= 30:
            self.risk_level = 'medium'
        else:
            self.risk_level = 'low'
        self.save()
