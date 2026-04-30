from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import KYCRecord, KYCDocument
from vendors.models import VendorProfile

@login_required
def kyc_dashboard(request):
    if not hasattr(request.user, 'vendor_profile'):
        return redirect('vendors:become')
    
    kyc_record, created = KYCRecord.objects.get_or_create(vendor=request.user.vendor_profile)
    documents = KYCDocument.objects.filter(vendor=request.user.vendor_profile)
    
    context = {
        'kyc_record': kyc_record,
        'documents': documents,
        'is_complete': kyc_record.is_complete(),
    }
    return render(request, 'kyc/dashboard.html', context)

@login_required
def submit_kyc(request):
    if not hasattr(request.user, 'vendor_profile'):
        return redirect('vendors:become')
    
    kyc_record, created = KYCRecord.objects.get_or_create(vendor=request.user.vendor_profile)
    
    if request.method == 'POST':
        # Update KYC record with form data
        fields = ['legal_business_name', 'registration_number', 'tax_id', 'vat_number', 
                  'business_address', 'city', 'state', 'country', 'postal_code',
                  'business_phone', 'business_email', 'website', 'business_type',
                  'year_established', 'authorized_person_name', 'authorized_person_title',
                  'authorized_person_email', 'authorized_person_phone']
        
        for field in fields:
            if field in request.POST:
                value = request.POST[field]
                if value:
                    setattr(kyc_record, field, value)
        
        kyc_record.kyc_status = 'pending'
        kyc_record.save()
        
        messages.success(request, 'KYC information submitted for review!')
        return redirect('kyc:dashboard')
    
    return render(request, 'kyc/submit.html', {'kyc_record': kyc_record})

@login_required
def upload_document(request):
    if not hasattr(request.user, 'vendor_profile'):
        return redirect('vendors:become')
    
    if request.method == 'POST' and request.FILES.get('document_file'):
        KYCDocument.objects.create(
            vendor=request.user.vendor_profile,
            document_type=request.POST.get('document_type'),
            document_file=request.FILES['document_file'],
            document_number=request.POST.get('document_number', ''),
            expiry_date=request.POST.get('expiry_date') or None,
            description=request.POST.get('description', '')
        )
        messages.success(request, 'Document uploaded successfully!')
        return redirect('kyc:dashboard')
    
    return render(request, 'kyc/upload_form.html')

@login_required
def kyc_status(request):
    if not hasattr(request.user, 'vendor_profile'):
        return redirect('vendors:become')
    
    kyc_record = KYCRecord.objects.get(vendor=request.user.vendor_profile)
    return render(request, 'kyc/status.html', {'kyc_record': kyc_record})
