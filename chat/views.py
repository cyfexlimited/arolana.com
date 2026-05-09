from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import ChatRoom, ChatMessage, VendorChatRoom, VendorChatMessage
from products.models import Product
from orders.models import Order

User = get_user_model()

@login_required
def chat_list(request):
    """List all chats for the current user"""
    rooms = request.user.chat_rooms.filter(is_active=True).order_by('-updated_at')
    
    room_data = []
    for room in rooms:
        last_message = room.get_last_message()
        unread_count = room.get_unread_count(request.user)
        room_data.append({
            'room': room,
            'last_message': last_message,
            'unread_count': unread_count,
        })
    
    return render(request, 'chat/chat_list.html', {'room_data': room_data})

@login_required
def chat_room(request, room_id):
    """View a specific chat room"""
    room = get_object_or_404(ChatRoom, id=room_id, participants=request.user, is_active=True)
    
    room.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    
    messages_list = room.messages.filter(is_deleted=False).select_related('sender')
    other_participant = room.participants.exclude(id=request.user.id).first()
    
    context = {
        'room': room,
        'messages': messages_list,
        'other_participant': other_participant,
        'product': room.product,
        'order': room.order,
    }
    return render(request, 'chat/chat_room.html', context)

@login_required
def start_chat(request, user_id=None, product_id=None, order_id=None):
    """Start a new chat"""
    if user_id:
        other_user = get_object_or_404(User, id=user_id)
        
        existing_room = ChatRoom.objects.filter(
            room_type='direct',
            participants=request.user
        ).filter(participants=other_user).first()
        
        if existing_room:
            return redirect('chat:room', room_id=existing_room.id)
        
        room = ChatRoom.objects.create(room_type='direct')
        room.participants.add(request.user, other_user)
        
        return redirect('chat:room', room_id=room.id)
    
    elif product_id:
        product = get_object_or_404(Product, id=product_id)
        vendor = product.vendor
        
        existing_room = ChatRoom.objects.filter(
            room_type='vendor_customer',
            product=product,
            participants=request.user
        ).filter(participants=vendor).first()
        
        if existing_room:
            return redirect('chat:room', room_id=existing_room.id)
        
        room = ChatRoom.objects.create(
            room_type='vendor_customer',
            product=product
        )
        room.participants.add(request.user, vendor)
        
        return redirect('chat:room', room_id=room.id)
    
    elif order_id:
        order = get_object_or_404(Order, id=order_id)
        
        room = ChatRoom.objects.create(
            room_type='support',
            order=order,
            name=f"Order #{order.order_number} Support"
        )
        room.participants.add(request.user)
        
        support_staff = User.objects.filter(is_staff=True).first()
        if support_staff:
            room.participants.add(support_staff)
        
        return redirect('chat:room', room_id=room.id)
    
    return redirect('chat:list')

@login_required
def send_message(request, room_id):
    """Send a message via POST"""
    if request.method == 'POST':
        room = get_object_or_404(ChatRoom, id=room_id, participants=request.user)
        message_text = request.POST.get('message', '').strip()
        
        if message_text:
            message = ChatMessage.objects.create(
                room=room,
                sender=request.user,
                message=message_text
            )
            room.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message_id': message.id,
                    'message': message.message,
                    'timestamp': message.created_at.strftime('%H:%M'),
                    'date': message.created_at.strftime('%b %d, %Y'),
                })
        
        return redirect('chat:room', room_id=room_id)
    
    return redirect('chat:list')

@login_required
def mark_read(request, room_id):
    """Mark all messages in a room as read"""
    if request.method == 'POST':
        room = get_object_or_404(ChatRoom, id=room_id, participants=request.user)
        room.messages.filter(is_read=False).exclude(sender=request.user).update(
            is_read=True, 
            read_at=timezone.now()
        )
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})

def get_unread_count(request):
    """Get unread chat count for current user"""
    if not request.user.is_authenticated:
        return JsonResponse({'unread_count': 0})
    
    from .models import ChatRoom, ChatMessage
    rooms = ChatRoom.objects.filter(participants=request.user, is_active=True)
    unread = 0
    for room in rooms:
        unread += room.get_unread_count(request.user)
    return JsonResponse({'unread_count': unread})

@login_required
def vendor_chat_list(request):
    """List all chats for a vendor"""
    if request.user.user_type != 'vendor' and not request.user.is_staff:
        messages.error(request, 'Only vendors can access this page.')
        return redirect('home')
    
    chat_rooms = VendorChatRoom.objects.filter(vendor=request.user, is_active=True).select_related('customer', 'product')
    
    for room in chat_rooms:
        room.unread_count = room.vendor_unread
    
    context = {
        'chat_rooms': chat_rooms,
        'total_unread': sum(room.vendor_unread for room in chat_rooms),
    }
    return render(request, 'chat/vendor_chat_list.html', context)

@login_required
def vendor_chat_room(request, room_id):
    """View a specific vendor chat room"""
    room = get_object_or_404(VendorChatRoom, id=room_id, vendor=request.user, is_active=True)
    
    room.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    room.vendor_unread = 0
    room.save()
    
    messages_list = room.messages.all().select_related('sender')
    
    context = {
        'room': room,
        'messages': messages_list,
        'customer': room.customer,
        'product': room.product,
        'order': room.order,
    }
    return render(request, 'chat/vendor_chat_room.html', context)

@login_required
def vendor_send_message(request, room_id):
    """Send a message from vendor to customer"""
    if request.method == 'POST':
        room = get_object_or_404(VendorChatRoom, id=room_id, vendor=request.user)
        message_text = request.POST.get('message', '').strip()
        
        if message_text:
            message = VendorChatMessage.objects.create(
                room=room,
                sender=request.user,
                message=message_text
            )
            
            room.last_message = message_text
            room.last_message_time = timezone.now()
            room.customer_unread += 1
            room.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message_id': message.id,
                    'message': message.message,
                    'timestamp': message.created_at.strftime('%H:%M'),
                })
        
        return redirect('chat:vendor_room', room_id=room_id)
    
    return redirect('chat:vendor_list')

@login_required
def customer_send_message(request, room_id):
    """Send a message from customer to vendor"""
    if request.method == 'POST':
        room = get_object_or_404(VendorChatRoom, id=room_id, customer=request.user)
        message_text = request.POST.get('message', '').strip()
        
        if message_text:
            message = VendorChatMessage.objects.create(
                room=room,
                sender=request.user,
                message=message_text
            )
            
            room.last_message = message_text
            room.last_message_time = timezone.now()
            room.vendor_unread += 1
            room.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message_id': message.id,
                    'message': message.message,
                    'timestamp': message.created_at.strftime('%H:%M'),
                })
        
        return redirect('chat:customer_room', room_id=room_id)
    
    return redirect('chat:list')

@login_required
def start_vendor_chat(request, vendor_id, product_id=None):
    """Start a new chat with a vendor (customer initiated)"""
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    product = None
    if product_id:
        product = get_object_or_404(Product, id=product_id)
    
    room = VendorChatRoom.objects.filter(
        vendor=vendor,
        customer=request.user,
        product=product
    ).first()
    
    if not room:
        room = VendorChatRoom.objects.create(
            vendor=vendor,
            customer=request.user,
            product=product
        )
    
    return redirect('chat:customer_room', room_id=room.id)

@login_required
def customer_chat_room(request, room_id):
    """View a specific chat room as a customer"""
    room = get_object_or_404(VendorChatRoom, id=room_id, customer=request.user, is_active=True)
    
    room.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    room.customer_unread = 0
    room.save()
    
    messages_list = room.messages.all().select_related('sender')
    
    context = {
        'room': room,
        'messages': messages_list,
        'vendor': room.vendor,
        'product': room.product,
    }
    return render(request, 'chat/customer_chat_room.html', context)

@login_required
def get_vendor_unread_count(request):
    """Get unread message count for vendor dashboard"""
    if request.user.user_type == 'vendor':
        unread_count = VendorChatRoom.objects.filter(
            vendor=request.user,
            vendor_unread__gt=0,
            is_active=True
        ).aggregate(total=Sum('vendor_unread'))['total'] or 0
    else:
        unread_count = VendorChatRoom.objects.filter(
            customer=request.user,
            customer_unread__gt=0,
            is_active=True
        ).aggregate(total=Sum('customer_unread'))['total'] or 0
    
    return JsonResponse({'unread_count': unread_count})
