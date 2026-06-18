from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q, Sum
from django.contrib import messages
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.cache import cache
from django.views.decorators.http import require_GET, require_POST
from .models import ChatRoom, ChatMessage, VendorChatRoom, VendorChatMessage
from products.models import Product
from orders.models import Order
from subscriptions.models import user_has_paid_subscription, user_subscription_limits, user_subscription_tier

User = get_user_model()


def _vendor_profile_for(user):
    try:
        return user.vendor_profile
    except ObjectDoesNotExist:
        return None


def _vendor_display_name(user):
    profile = _vendor_profile_for(user)
    if profile and profile.store_name:
        return profile.store_name
    return user.get_full_name() or user.username or user.email


def _vendor_chat_locked_redirect(request, room, for_vendor=False):
    if user_has_paid_subscription(room.vendor):
        return None

    messages.info(request, 'Vendor chat is available only for sellers with an active paid subscription.')
    if for_vendor:
        return redirect('subscriptions:plans')
    if room.product:
        return redirect(room.product.get_absolute_url())
    return redirect('vendors:list')


def _vendor_room_for_participant(request, room_id):
    return get_object_or_404(
        VendorChatRoom.objects.select_related('vendor', 'customer', 'product'),
        Q(vendor=request.user) | Q(customer=request.user),
        id=room_id,
        is_active=True,
    )


def _chat_name_for(user, room):
    if user == room.vendor:
        return _vendor_display_name(user)
    return user.get_full_name() or user.username or user.email


def _typing_cache_key(room_id, user_id):
    return f'vendor-chat-typing:{room_id}:{user_id}'


def _user_display_name(user):
    if not user:
        return 'Arolana Support'
    return user.get_full_name() or user.username or user.email


def _send_message_notification(user, sender, message, link, room_type='chat', room_id=None):
    try:
        from notifications.models import Notification
        sender_name = _user_display_name(sender)
        Notification.send(
            user=user,
            notification_type='message',
            title=f'New message from {sender_name}',
            message=(message[:140] + '...') if len(message) > 140 else message,
            link=link,
            metadata={'room_type': room_type, 'room_id': room_id, 'sender_id': sender.id},
            priority=3,
        )
    except Exception:
        pass


def _request_ip_address(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip.strip()
    return request.META.get("REMOTE_ADDR")


def _request_country_code(request):
    for header in ("HTTP_CF_IPCOUNTRY", "HTTP_CLOUDFRONT_VIEWER_COUNTRY", "HTTP_X_COUNTRY_CODE", "HTTP_X_FORWARDED_COUNTRY", "HTTP_X_APPENGINE_COUNTRY", "HTTP_FLY_CLIENT_IP_COUNTRY"):
        country_code = (request.META.get(header) or "").strip().upper()
        if len(country_code) == 2 and country_code != "XX":
            return country_code
    return request.session.get("user_country_code", "")


def _product_absolute_url(request, product):
    if not product:
        return ""
    try:
        return request.build_absolute_uri(product.get_absolute_url())
    except Exception:
        return ""


def _record_vendor_chat_lead(request, room, action_type, message=None, extra=None):
    try:
        from vendors.models import VendorLead
        vendor_profile = room.vendor.vendor_profile
        if not request.session.session_key:
            request.session.save()
        product_url = _product_absolute_url(request, room.product)
        VendorLead.objects.create(
            vendor=vendor_profile,
            product=room.product,
            customer_user=room.customer,
            guest_session_key=request.session.session_key or "",
            action_type=action_type,
            customer_name=room.customer.get_full_name() or room.customer.username,
            customer_email=room.customer.email or "",
            source=(request.POST.get("source") or request.GET.get("source") or "web")[:40],
            page_url=(request.META.get("HTTP_REFERER") or product_url or request.build_absolute_uri())[:800],
            product_url=product_url[:800],
            ip_address=_request_ip_address(request),
            country=_request_country_code(request),
            currency=(getattr(request, "user_currency", "") or request.session.get("user_currency", "") or "").upper()[:10],
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={"room_id": room.id, "message_id": getattr(message, "id", None)},
            extra_data=extra or {},
        )
    except Exception:
        pass


def _vendor_chat_message_payload(message, request_user):
    return {
        "id": message.id,
        "message": message.message,
        "sender_id": message.sender_id,
        "sender_name": _user_display_name(message.sender),
        "is_mine": message.sender_id == request_user.id,
        "timestamp": message.created_at.strftime("%H:%M"),
        "created_at": message.created_at.isoformat(),
    }


def _total_chat_unread(user):
    direct_unread = ChatMessage.objects.filter(
        room__participants=user,
        room__is_active=True,
        is_active=True,
        is_read=False,
    ).exclude(sender=user).count()
    customer_unread = VendorChatRoom.objects.filter(customer=user, is_active=True).aggregate(total=Sum('customer_unread'))['total'] or 0
    vendor_unread = VendorChatRoom.objects.filter(vendor=user, is_active=True).aggregate(total=Sum('vendor_unread'))['total'] or 0
    return direct_unread + customer_unread + vendor_unread


def _report_vendor_chat_to_admin(room, message=None, event='message'):
    """Create an admin-visible alert for vendor/customer chat activity."""
    try:
        from dashboard.models import SystemAlert
        if event == 'started':
            title = 'New vendor/customer chat started'
            body = f'{room.customer.email} opened a chat with {room.vendor.email}.'
        else:
            sender = message.sender.email if message else 'Unknown sender'
            body = f'{sender} sent a message in vendor chat #{room.id}.'
            title = 'Vendor/customer chat message logged'
        if room.product:
            body += f' Product: {room.product.name}.'
        SystemAlert.objects.create(
            title=title,
            message=body,
            level='info',
            link=f'/admin/chat/vendorchatroom/{room.id}/change/'
        )
    except Exception:
        pass

@login_required
def chat_list(request):
    """Unified message inbox for the current user."""
    rooms = request.user.chat_rooms.filter(is_active=True).prefetch_related('participants').order_by('-updated_at')
    
    room_data = []
    for room in rooms:
        last_message = room.get_last_message()
        unread_count = room.get_unread_count(request.user)
        other_participant = room.participants.exclude(id=request.user.id).first()
        room_data.append({
            'room': room,
            'kind': 'direct',
            'title': room.name or _user_display_name(other_participant),
            'subtitle': room.product.name if room.product else (f'Order #{room.order.order_number}' if room.order else 'Direct message'),
            'avatar_icon': 'fa-user',
            'url': reverse('chat:room', args=[room.id]),
            'last_message': last_message,
            'last_message_text': last_message.message if last_message else '',
            'last_message_time': last_message.created_at if last_message else room.updated_at,
            'unread_count': unread_count,
        })

    customer_rooms = VendorChatRoom.objects.filter(customer=request.user, is_active=True).select_related('vendor', 'product', 'vendor__vendor_profile')
    for room in customer_rooms:
        room_data.append({
            'room': room,
            'kind': 'vendor_customer',
            'title': _vendor_display_name(room.vendor),
            'subtitle': room.product.name if room.product else 'Vendor store chat',
            'avatar_icon': 'fa-store',
            'url': reverse('chat:customer_room', args=[room.id]),
            'last_message': None,
            'last_message_text': room.last_message,
            'last_message_time': room.last_message_time,
            'unread_count': room.customer_unread,
        })

    vendor_rooms = VendorChatRoom.objects.filter(vendor=request.user, is_active=True).select_related('customer', 'product')
    for room in vendor_rooms:
        room_data.append({
            'room': room,
            'kind': 'vendor_customer',
            'title': _user_display_name(room.customer),
            'subtitle': room.product.name if room.product else 'Customer store chat',
            'avatar_icon': 'fa-user',
            'url': reverse('chat:vendor_room', args=[room.id]),
            'last_message': None,
            'last_message_text': room.last_message,
            'last_message_time': room.last_message_time,
            'unread_count': room.vendor_unread,
        })

    room_data.sort(key=lambda item: item['last_message_time'] or timezone.now(), reverse=True)
    
    return render(request, 'chat/chat_list.html', {
        'room_data': room_data,
        'total_unread': sum(item['unread_count'] for item in room_data),
    })

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
        if other_user.user_type == 'vendor':
            return start_vendor_chat(request, vendor_id=other_user.id)
        
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

        if not user_has_paid_subscription(vendor):
            messages.info(request, 'Vendor chat is available only for sellers with an active paid subscription.')
            return redirect(product.get_absolute_url())
        
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
            for recipient in room.participants.exclude(id=request.user.id):
                _send_message_notification(
                    recipient,
                    request.user,
                    message_text,
                    reverse('chat:room', args=[room.id]),
                    room_type='direct',
                    room_id=room.id,
                )
            
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
    
    return JsonResponse({'unread_count': _total_chat_unread(request.user)})

@login_required
def vendor_chat_list(request):
    """List all chats for a vendor"""
    if request.user.user_type != 'vendor' and not request.user.is_staff:
        messages.error(request, 'Only vendors can access this page.')
        return redirect('home')

    chat_enabled = user_has_paid_subscription(request.user)
    if not chat_enabled:
        return render(request, 'chat/vendor_chat_list.html', {
            'chat_rooms': [],
            'total_unread': 0,
            'chat_locked': True,
            'chat_enabled': False,
            'subscription_tier': user_subscription_tier(request.user),
            'subscription_limits': user_subscription_limits(request.user),
        })
    
    chat_rooms = VendorChatRoom.objects.filter(vendor=request.user, is_active=True).select_related('customer', 'product')
    
    for room in chat_rooms:
        room.unread_count = room.vendor_unread
    
    context = {
        'chat_rooms': chat_rooms,
        'total_unread': sum(room.vendor_unread for room in chat_rooms),
        'chat_locked': False,
        'chat_enabled': True,
        'subscription_tier': user_subscription_tier(request.user),
        'subscription_limits': user_subscription_limits(request.user),
    }
    return render(request, 'chat/vendor_chat_list.html', context)

@login_required
def vendor_chat_room(request, room_id):
    """View a specific vendor chat room"""
    room = get_object_or_404(VendorChatRoom, id=room_id, vendor=request.user, is_active=True)
    locked_response = _vendor_chat_locked_redirect(request, room, for_vendor=True)
    if locked_response:
        return locked_response
    
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
        locked_response = _vendor_chat_locked_redirect(request, room, for_vendor=True)
        if locked_response:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Vendor chat requires an active paid subscription.'}, status=403)
            return locked_response

        message_text = request.POST.get('message', '').strip()
        
        if message_text:
            message = VendorChatMessage.objects.create(
                room=room,
                sender=request.user,
                message=message_text
            )
            _report_vendor_chat_to_admin(room, message)
            _record_vendor_chat_lead(request, room, 'chat_message_sent', message=message, extra={'sender_role': 'vendor'})
            
            room.last_message = message_text
            room.last_message_time = timezone.now()
            room.customer_unread += 1
            room.save()
            _send_message_notification(
                room.customer,
                request.user,
                message_text,
                reverse('chat:customer_room', args=[room.id]),
                room_type='vendor_customer',
                room_id=room.id,
            )
            
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
        locked_response = _vendor_chat_locked_redirect(request, room)
        if locked_response:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'Vendor chat requires an active paid subscription.'}, status=403)
            return locked_response

        message_text = request.POST.get('message', '').strip()
        
        if message_text:
            message = VendorChatMessage.objects.create(
                room=room,
                sender=request.user,
                message=message_text
            )
            _report_vendor_chat_to_admin(room, message)
            _record_vendor_chat_lead(request, room, 'chat_message_sent', message=message, extra={'sender_role': 'customer'})
            
            room.last_message = message_text
            room.last_message_time = timezone.now()
            room.vendor_unread += 1
            room.save()
            _send_message_notification(
                room.vendor,
                request.user,
                message_text,
                reverse('chat:vendor_room', args=[room.id]),
                room_type='vendor_customer',
                room_id=room.id,
            )
            
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

    if not user_has_paid_subscription(vendor):
        messages.info(request, 'Vendor chat is available only for sellers with an active paid subscription.')
        if product:
            return redirect(product.get_absolute_url())
        return redirect('vendors:list')
    
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
        _report_vendor_chat_to_admin(room, event='started')
        _record_vendor_chat_lead(request, room, 'chat_started', extra={'created_from': 'redirect_start'})
    
    return redirect('chat:customer_room', room_id=room.id)


@login_required
@require_GET
def vendor_chat_context_api(request, vendor_id, product_id=None):
    """Create/load a vendor chat room for same-page web and mobile chat UIs."""
    vendor = get_object_or_404(User, id=vendor_id, user_type='vendor')
    product = get_object_or_404(Product, id=product_id) if product_id else None

    if not user_has_paid_subscription(vendor):
        return JsonResponse({
            'success': False,
            'message': 'Vendor chat is available only for sellers with an active paid subscription. You can request a callback or use Arolana support.',
        }, status=403)

    room, created = VendorChatRoom.objects.get_or_create(
        vendor=vendor,
        customer=request.user,
        product=product,
        defaults={},
    )
    if created:
        _report_vendor_chat_to_admin(room, event='started')
        _record_vendor_chat_lead(request, room, 'chat_started', extra={'created_from': 'ajax_context'})
    else:
        _record_vendor_chat_lead(request, room, 'chat_click', extra={'created_from': 'ajax_context'})

    room.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    room.customer_unread = 0
    room.save(update_fields=['customer_unread', 'updated_at'])

    messages_list = room.messages.select_related('sender').order_by('created_at')[:80]
    vendor_profile = _vendor_profile_for(vendor)
    return JsonResponse({
        'success': True,
        'room': {
            'id': room.id,
            'send_url': reverse('chat:customer_send', args=[room.id]),
            'typing_url': reverse('chat:vendor_typing', args=[room.id]),
            'typing_status_url': reverse('chat:vendor_typing_status', args=[room.id]),
        },
        'vendor': {
            'id': vendor.id,
            'name': _vendor_display_name(vendor),
            'store_name': getattr(vendor_profile, 'store_name', '') if vendor_profile else '',
        },
        'product': {
            'id': product.id,
            'name': product.name,
            'url': _product_absolute_url(request, product),
        } if product else None,
        'messages': [_vendor_chat_message_payload(message, request.user) for message in messages_list],
    })

@login_required
def customer_chat_room(request, room_id):
    """View a specific chat room as a customer"""
    room = get_object_or_404(VendorChatRoom, id=room_id, customer=request.user, is_active=True)
    locked_response = _vendor_chat_locked_redirect(request, room)
    if locked_response:
        return locked_response
    
    room.messages.filter(is_read=False).exclude(sender=request.user).update(is_read=True, read_at=timezone.now())
    room.customer_unread = 0
    room.save()
    
    messages_list = room.messages.all().select_related('sender')
    
    context = {
        'room': room,
        'messages': messages_list,
        'vendor': room.vendor,
        'vendor_profile': _vendor_profile_for(room.vendor),
        'vendor_display_name': _vendor_display_name(room.vendor),
        'product': room.product,
    }
    return render(request, 'chat/customer_chat_room.html', context)


@login_required
@require_POST
def vendor_chat_typing(request, room_id):
    """Record a short-lived typing signal for a vendor/customer chat room."""
    room = _vendor_room_for_participant(request, room_id)
    locked_response = _vendor_chat_locked_redirect(request, room, for_vendor=request.user == room.vendor)
    if locked_response:
        return JsonResponse({'success': False, 'error': 'Chat is not available for this seller.'}, status=403)

    cache.set(_typing_cache_key(room.id, request.user.id), True, timeout=6)
    return JsonResponse({'success': True})


@login_required
@require_GET
def vendor_chat_typing_status(request, room_id):
    """Return whether the other participant is currently typing."""
    room = _vendor_room_for_participant(request, room_id)
    other_user = room.customer if request.user == room.vendor else room.vendor
    is_typing = bool(cache.get(_typing_cache_key(room.id, other_user.id)))
    return JsonResponse({
        'is_typing': is_typing,
        'name': _chat_name_for(other_user, room),
    })

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
