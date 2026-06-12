import os
import re
from urllib.parse import urlencode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse

from .models import SmartChatConversation, SmartChatMessage, SmartChatSupportTicket


User = get_user_model()


HANDOFF_WORDS = (
    "human",
    "admin",
    "agent",
    "representative",
    "support",
    "operator",
    "person",
    "manager",
    "speak to someone",
    "talk to someone",
    "customer care",
    "real person",
    "complain",
    "complaint",
    "call me",
    "contact me",
)

URGENT_WORDS = (
    "refund",
    "payment failed",
    "scam",
    "fraud",
    "wrong item",
    "damaged",
    "angry",
    "lawsuit",
    "police",
    "cancel order",
    "not delivered",
)

SENSITIVE_ACTION_WORDS = (
    "approve refund",
    "refund me",
    "refund this",
    "approve payout",
    "pay me",
    "approve kyc",
    "delete account",
    "change price",
    "reduce price",
    "manual price",
    "approve product",
    "reject product",
    "cancel payout",
)

INTENT_KEYWORDS = {
    "product_search": ("search", "find", "recommend", "show me", "looking for", "product", "price of", "do you have", "do u have", "available", "in stock", "phones", "laptop", "tv", "camera"),
    "order_tracking": ("track", "tracking", "where is my order", "order status", "delivery status"),
    "payment_support": ("payment", "paid", "paystack", "flutterwave", "stripe", "paypal", "failed payment", "checkout"),
    "refund_support": ("refund", "return", "wrong item", "damaged", "not delivered"),
    "vendor_support": ("vendor", "store", "sales", "subscription", "kyc", "product upload", "manufacturer"),
    "rider_support": ("rider", "pickup", "delivery", "wallet", "payout", "earning", "route"),
    "human_handoff": HANDOFF_WORDS,
    "faq": ("policy", "how do i", "what is", "help", "support", "faq"),
}


def should_handoff(message):
    text = str(message or "").lower()
    return any(word in text for word in HANDOFF_WORDS) or any(
        word in text for word in URGENT_WORDS
    )


def detect_intent(message, audience="customer"):
    text = str(message or "").lower()
    if any(word in text for word in SENSITIVE_ACTION_WORDS):
        return {
            "intent": "sensitive_admin_action",
            "urgency": "urgent",
            "requires_handoff": True,
            "reason": "Sensitive account, money, approval, or pricing action requires admin approval.",
        }
    if _looks_like_product_interest(text):
        return {
            "intent": "product_search",
            "urgency": "normal",
            "requires_handoff": False,
            "reason": "",
        }
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(word in text for word in keywords):
            urgency = "high" if intent in {"payment_support", "refund_support", "human_handoff"} else "normal"
            return {
                "intent": intent,
                "urgency": urgency,
                "requires_handoff": intent in {"refund_support", "human_handoff"},
                "reason": "",
            }
    if audience == SmartChatConversation.AUDIENCE_VENDOR:
        return {"intent": "vendor_support", "urgency": "normal", "requires_handoff": False, "reason": ""}
    if audience == SmartChatConversation.AUDIENCE_RIDER:
        return {"intent": "rider_support", "urgency": "normal", "requires_handoff": False, "reason": ""}
    return {"intent": "general_support", "urgency": "normal", "requires_handoff": False, "reason": ""}


def _money(value):
    try:
        return f"₦{float(value or 0):,.0f}"
    except Exception:
        return f"₦{value or 0}"


def _human_status(value):
    text = str(value or "").replace("_", " ").strip()
    return text.title() if text else "Not available"


def _product_limit_label(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return "not set"
    if limit < 0:
        return "unlimited"
    return f"{limit:,}"


def _yes_no(value):
    return "Yes" if value else "No"


def _looks_like_vendor_onboarding_question(message):
    text = str(message or "").lower()
    return (
        "become a vendor" in text
        or "become vendor" in text
        or "register as vendor" in text
        or "open vendor" in text
        or "sell on arolana" in text
        or "start selling" in text
    )


def _looks_like_shopping_question(message):
    text = str(message or "").lower()
    return (
        "how do i shop" in text
        or "how to shop" in text
        or "how can i buy" in text
        or "how do i buy" in text
        or "how to buy" in text
        or "place order" in text
        or "make an order" in text
        or "order something" in text
        or "buy product" in text
        or "purchase" in text
    )


def _looks_like_step_by_step_question(message):
    text = str(message or "").lower().strip()
    return (
        "step by step" in text
        or "can you help" in text
        or "guide me" in text
        or "walk me through" in text
        or text in {"help", "help me", "yes help", "yes please"}
    )


def _looks_like_checkout_question(message):
    text = str(message or "").lower()
    return (
        "checkout" in text
        or "check out" in text
        or "pay for" in text
        or "pay online" in text
        or "payment gateway" in text
        or "delivery address" in text
    )


def _looks_like_account_question(message):
    text = str(message or "").lower()
    return (
        "create account" in text
        or "register" in text
        or "sign up" in text
        or "login" in text
        or "log in" in text
        or "pin" in text
        or "password" in text
    )


def _looks_like_rfq_question(message):
    text = str(message or "").lower()
    return (
        "rfq" in text
        or "quotation" in text
        or "quote" in text
        or "bulk order" in text
        or "wholesale" in text
        or "moq" in text
    )


def _looks_like_product_interest(message):
    text = str(message or "").lower()
    product_words = (
        "phone", "phones", "laptop", "tv", "television", "camera", "watch", "shoe", "bag",
        "tablet", "speaker", "earbud", "earbuds", "headphone", "charger", "fridge",
        "freezer", "generator", "inverter", "samsung", "iphone", "apple", "sony",
        "lg", "hp", "dell", "lenovo", "tecno", "infinix", "xiaomi", "oppo"
    )
    buying_words = (
        "do you have", "do u have", "can i get", "i need", "i want", "looking for",
        "available", "in stock", "how much", "price", "sell", "get me", "show me"
    )
    return any(word in text for word in product_words) and (
        any(word in text for word in buying_words)
        or len(text.split()) <= 5
    )


def _looks_like_greeting(message):
    text = str(message or "").lower().strip()
    return text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "are you there", "you there"} or text.startswith(("hi ", "hello ", "hey "))


def _looks_like_thanks(message):
    text = str(message or "").lower().strip()
    return any(word in text for word in ["thank you", "thanks", "appreciate", "nice one", "great", "perfect"])


def _extract_product_search_terms(query):
    text = re.sub(r"[^a-zA-Z0-9\s-]", " ", str(query or "").lower())
    replacements = {
        "smart phones": "phone",
        "smartphone": "phone",
        "mobile phone": "phone",
        "cell phone": "phone",
        "television": "tv",
        "ear phones": "earphone",
        "earbuds": "earbud",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    stop_words = {
        "do", "you", "u", "have", "has", "had", "please", "pls", "can", "i", "get",
        "buy", "want", "need", "looking", "for", "show", "me", "find", "recommend",
        "available", "stock", "in", "the", "a", "an", "on", "arolana", "any", "is",
        "there", "with", "under", "below", "above", "best", "good", "cheap",
        "affordable", "price", "prices", "sell", "selling",
    }
    tokens = [token.strip() for token in text.split() if len(token.strip()) > 1 and token.strip() not in stop_words]
    normalized = []
    for token in tokens:
        if token.endswith("s") and len(token) > 3:
            normalized.append(token[:-1])
        normalized.append(token)
    seen = []
    for token in normalized:
        if token not in seen:
            seen.append(token)
    return seen[:8]


def _shopping_guide_reply():
    return (
        "Of course. Here is how to shop on Arolana step by step:\n\n"
        "1. Search for what you need using the search bar, category page, or product recommendations.\n"
        "2. Open a product and check the price, stock, vendor type, verified badge, delivery details, warranty, and reviews.\n"
        "3. If the product has variants, choose the right color, size, model, or capacity.\n"
        "4. Tap Add to Cart, then open your cart and confirm quantity. If the product has MOQ, your quantity must meet the minimum.\n"
        "5. Go to checkout and enter your name, phone number, delivery address, city/state, and order note if needed.\n"
        "6. Choose payment method and pay securely through Arolana checkout.\n"
        "7. After payment, Arolana creates your order, receipt/invoice, tracking code, and notification.\n"
        "8. You can track the order from Orders or Tracking until the rider delivers it.\n\n"
        "Tell me what you want to buy, your budget, or the brand you prefer, and I can help you find a good option."
    )


def _greeting_reply():
    return (
        "Yes, I’m here. Welcome to Arolana.\n\n"
        "You can talk to me normally. I can help you find products, compare prices, check vendor trust badges, explain checkout, track orders, or connect you to support when a human needs to step in.\n\n"
        "What are you trying to do today?"
    )


def _thanks_reply():
    return (
        "You’re welcome. I’m here whenever you need help shopping, tracking an order, checking payment, or talking to Arolana support."
    )


def _product_interest_no_match_reply(user_message):
    terms = _extract_product_search_terms(user_message)
    requested = " ".join(terms) if terms else "that product"
    product_url = _product_list_url_for_message(user_message)
    return (
        f"I can help with {requested}. I did not find a perfect live match yet, but you can still browse the closest product results here:\n\n"
        f"[View related products]({product_url})\n\n"
        "Tell me:\n"
        "• Your budget\n"
        "• New or used\n"
        "• Preferred model or storage size\n"
        "• Your delivery location\n\n"
        "For example: “Samsung phone under ₦300,000, brand new” or “Samsung A-series fairly used.”"
    )


def _product_list_url_for_message(user_message):
    terms = _extract_product_search_terms(user_message)
    terms = [
        term for term in terms
        if not (term.endswith("s") and len(term) > 3 and term[:-1] in terms)
    ]
    query = " ".join(terms).strip() or str(user_message or "").strip()
    params = urlencode({"q": query}) if query else ""
    return f"/products/?{params}" if params else "/products/"


def _product_interest_with_matches_reply(products, user_message):
    product_url = _product_list_url_for_message(user_message)
    return (
        "Yes, I found matching products that may fit what you asked for. It is better to view them in the product list so you can compare images, prices, vendor badges, stock, and delivery details clearly.\n\n"
        f"[View matching products]({product_url})"
    )


def _checkout_guide_reply():
    return (
        "Here is the checkout process:\n\n"
        "1. Open Cart and review your items, quantity, vendor, and total.\n"
        "2. Confirm any MOQ or stock warning before continuing.\n"
        "3. Enter your delivery address and phone number carefully because the rider uses it for delivery.\n"
        "4. Choose a payment method. Online payment is safest because Arolana can confirm your order faster.\n"
        "5. Complete payment inside the checkout flow.\n"
        "6. Wait for the success screen with your order number, tracking code, and receipt/invoice.\n\n"
        "If payment succeeds but your order does not update, send me the order number or payment reference and I can help check it."
    )


def _account_guide_reply():
    return (
        "To use Arolana smoothly, create or log in to your customer account:\n\n"
        "1. Open Account.\n"
        "2. Choose Register if you are new, or Login if you already have an account.\n"
        "3. Enter your full name, phone, email, and PIN/password.\n"
        "4. Verify your email or phone if Arolana asks for verification.\n"
        "5. Add your delivery address before checkout so orders and riders have the correct location.\n\n"
        "If you cannot log in, tell me whether it is email, phone, PIN, or verification causing the problem."
    )


def _rfq_guide_reply():
    return (
        "For wholesale, MOQ, or manufacturer buying, use Request for Quotation:\n\n"
        "1. Open the product or vendor store.\n"
        "2. Tap Request Quotation.\n"
        "3. Enter quantity, budget, delivery location, expected delivery date, and your message.\n"
        "4. Submit the RFQ to the vendor/manufacturer.\n"
        "5. The vendor can reply with price, lead time, and notes.\n"
        "6. You can accept, reject, or chat with the vendor before converting it to an order.\n\n"
        "RFQ is best when you need bulk quantity, factory pricing, custom supply, or negotiation."
    )


def _step_by_step_reply(audience):
    if audience == SmartChatConversation.AUDIENCE_VENDOR:
        return (
            "Yes, I can guide you step by step. For vendors, I can help with:\n\n"
            "• Completing your store profile\n"
            "• Submitting KYC\n"
            "• Adding bank details\n"
            "• Uploading products, images, variants, PDF manuals, and certificates\n"
            "• Understanding subscription limits and benefits\n"
            "• Checking orders and marking them ready for pickup\n"
            "• Reading wallet, invoices, and payouts\n\n"
            "Tell me which one you want to do first, and I will walk you through it."
        )
    if audience == SmartChatConversation.AUDIENCE_RIDER:
        return (
            "Yes, I can guide you step by step. For riders, I can help with:\n\n"
            "• Going online and becoming available\n"
            "• Accepting assigned pickups\n"
            "• Navigating to vendor and customer locations\n"
            "• Updating delivery status correctly\n"
            "• Uploading delivery proof\n"
            "• Understanding wallet, earnings, and payout status\n"
            "• Reporting failed deliveries or problems\n\n"
            "Tell me what you are trying to do now."
        )
    return (
        "Yes, I can guide you step by step. I can help you:\n\n"
        "• Find the right product\n"
        "• Compare prices, brands, vendors, MOQ, and warranty\n"
        "• Add items to cart\n"
        "• Checkout and pay\n"
        "• Track your order\n"
        "• Chat with a vendor or admin\n"
        "• Submit an RFQ for wholesale or manufacturer pricing\n\n"
        "If you want to shop, say what product you need and your budget. If you already ordered, send your order number or tracking code."
    )


def search_products_tool(query, limit=5):
    try:
        from products.models import Product

        text = str(query or "").strip()
        terms = _extract_product_search_terms(text)
        qs = Product.objects.select_related("brand", "category", "vendor").filter(is_active=True)
        if hasattr(Product, "approval_status"):
            qs = qs.filter(approval_status="approved")
        if text:
            aliases = {
                "google": ("google", "pixel"),
                "pixel": ("pixel", "google"),
                "phone": ("phone", "phones", "smartphone", "mobile"),
                "phones": ("phone", "phones", "smartphone", "mobile"),
                "tv": ("tv", "television"),
                "television": ("tv", "television"),
            }
            recognized_brands = {
                "acer", "apple", "asus", "google", "hp", "huawei", "infinix",
                "itel", "lenovo", "lg", "nokia", "oneplus", "oppo", "pixel",
                "samsung", "sony", "tecno", "vivo", "xiaomi",
            }

            def term_q(term):
                result = Q()
                for value in aliases.get(term, (term,)):
                    result |= (
                        Q(name__icontains=value)
                        | Q(sku__icontains=value)
                        | Q(manufacturer_sku__icontains=value)
                        | Q(brand__name__icontains=value)
                        | Q(category__name__icontains=value)
                        | Q(vendor__vendor_profile__store_name__icontains=value)
                    )
                return result

            strict_q = Q()
            for term in terms:
                strict_q &= term_q(term)
            strict_matches = qs.filter(strict_q).distinct() if terms else qs.none()
            if strict_matches.exists():
                qs = strict_matches
            elif recognized_brands.intersection(terms):
                qs = qs.none()
            else:
                loose_q = term_q(text.lower())
                for term in terms:
                    loose_q |= term_q(term)
                qs = qs.filter(loose_q).distinct()
        products = []

        def product_score(product):
            name = str(getattr(product, "name", "") or "").lower()
            sku = str(getattr(product, "sku", "") or "").lower()
            manufacturer_sku = str(getattr(product, "manufacturer_sku", "") or "").lower()
            brand = str(getattr(getattr(product, "brand", None), "name", "") or "").lower()
            category = str(getattr(getattr(product, "category", None), "name", "") or "").lower()
            vendor_profile = getattr(product.vendor, "vendor_profile", None)
            vendor_name = str(getattr(vendor_profile, "store_name", "") or "").lower()
            haystack = " ".join([name, sku, manufacturer_sku, brand, category, vendor_name])
            score = 0
            if text and text.lower() in haystack:
                score += 20
            for term in terms:
                if term in brand:
                    score += 12
                if term in name:
                    score += 8
                if term in category:
                    score += 5
                if term in sku or term in manufacturer_sku:
                    score += 7
                if term in vendor_name:
                    score += 2
            if terms and all(term in haystack for term in terms):
                score += 15
            if any(term in {"phone", "phones"} for term in terms):
                if "phone" in category or "smartphone" in category or "phone" in name or "galaxy" in name or "iphone" in name:
                    score += 8
                if "case" in name or "case" in category or "watch" in name or "watch" in category:
                    score -= 8
            score += int(getattr(product, "stock_quantity", 0) or 0) > 0
            return score

        candidates = list(qs.order_by("-updated_at")[:80])
        candidates.sort(key=product_score, reverse=True)

        for product in candidates[:limit]:
            vendor_profile = getattr(product.vendor, "vendor_profile", None)
            products.append({
                "id": product.id,
                "name": product.name,
                "sku": getattr(product, "sku", ""),
                "manufacturer_sku": getattr(product, "manufacturer_sku", ""),
                "brand": getattr(getattr(product, "brand", None), "name", ""),
                "category": getattr(getattr(product, "category", None), "name", ""),
                "price": str(getattr(product, "price", "")),
                "price_display": _money(getattr(product, "price", 0)),
                "stock_quantity": getattr(product, "stock_quantity", 0),
                "vendor_name": getattr(vendor_profile, "store_name", "") or product.vendor.get_full_name() or product.vendor.email,
                "vendor_type": getattr(vendor_profile, "vendor_type", ""),
                "verified_vendor": bool(getattr(vendor_profile, "is_verified", False)),
            })
        return products
    except Exception:
        return []


def order_tracking_tool(user=None, order_reference="", phone=""):
    try:
        from orders.models import Order

        reference = str(order_reference or "").strip()
        qs = Order.objects.all()
        if user and getattr(user, "is_authenticated", False) and not user.is_staff:
            qs = qs.filter(user=user)
        if reference:
            qs = qs.filter(Q(order_number__icontains=reference) | Q(tracking_number__icontains=reference))
        if phone:
            qs = qs.filter(customer_phone__icontains=phone)
        order = qs.order_by("-created_at").first()
        if not order:
            return {}
        delivery = None
        try:
            delivery = order.live_delivery_requests.order_by("-created_at").first()
        except Exception:
            delivery = None
        return {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "payment_status": order.payment_status,
            "total": str(order.total),
            "total_display": _money(order.total),
            "tracking_number": getattr(order, "tracking_number", ""),
            "delivery_status": getattr(delivery, "status", ""),
            "delivery_tracking_code": getattr(delivery, "tracking_code", ""),
            "rider_name": getattr(getattr(delivery, "rider", None), "user", None).get_full_name() if delivery and delivery.rider_id else "",
        }
    except Exception:
        return {}


def vendor_support_tool(user=None):
    try:
        profile = getattr(user, "vendor_profile", None)
        if not profile:
            return {}
        products_count = user.products.count() if hasattr(user, "products") else 0
        return {
            "store_name": profile.store_name,
            "vendor_type": profile.vendor_type,
            "kyc_status": getattr(profile, "kyc_status", getattr(profile, "approval_status", "")),
            "approval_status": profile.approval_status,
            "subscription": getattr(profile, "badge_level", "") or getattr(profile, "subscription_tier", ""),
            "product_limit": profile.product_limit,
            "products_count": products_count,
            "can_upload_products": products_count < profile.product_limit or profile.product_limit < 0,
            "is_verified": bool(getattr(profile, "is_verified", False)),
            "manufacturer_verified": bool(getattr(profile, "manufacturer_verified", False)),
            "vendor_type": getattr(profile, "vendor_type", ""),
            "profile_completion_percent": getattr(profile, "profile_completion_percent", 0),
            "subscription_active": bool(getattr(profile, "subscription_active", False)),
            "wallet_balance": str(getattr(profile, "wallet_balance", "")),
        }
    except Exception:
        return {}


def rider_support_tool(rider=None):
    try:
        if not rider:
            return {}
        active = rider.deliveries.exclude(status__in=["delivered", "failed", "cancelled", "returned"]).count()
        completed = rider.deliveries.filter(status="delivered").count()
        wallet = getattr(rider, "wallet", None)
        return {
            "rider_name": rider.user.get_full_name() or rider.user.email,
            "kyc_status": rider.kyc_status,
            "online": rider.is_online,
            "available": rider.is_available,
            "active_deliveries": active,
            "completed_deliveries": completed,
            "wallet_balance": str(getattr(wallet, "balance", "")) if wallet else "",
            "pending_balance": str(getattr(wallet, "pending_balance", "")) if wallet else "",
        }
    except Exception:
        return {}


def create_support_ticket(conversation, title, description, intent="", priority="normal", metadata=None):
    ticket = SmartChatSupportTicket.objects.create(
        conversation=conversation,
        created_by=conversation.user,
        title=str(title or "Arolana support ticket")[:220],
        description=description or "",
        audience=conversation.audience,
        intent=intent or conversation.current_intent,
        priority=priority,
        order=conversation.order,
        product=conversation.product,
        vendor_profile=conversation.vendor_profile,
        rider_profile=conversation.rider_profile,
        metadata=metadata or {},
    )
    conversation.mark_admin_requested()
    try:
        from notifications.models import Notification

        for admin in User.objects.filter(is_staff=True, is_active=True)[:25]:
            Notification.send(
                user=admin,
                notification_type="message",
                title=f"AI support ticket #{ticket.id}",
                message=ticket.title,
                link=reverse("admin:smartchat_smartchatsupportticket_change", args=[ticket.id]),
                metadata={"ticket_id": ticket.id, "conversation_id": conversation.id, "intent": intent},
                priority=4 if priority == "urgent" else 3,
            )
    except Exception:
        pass
    return ticket


def build_operations_context(conversation, user_message, audience="customer", actor_user=None, rider=None):
    intent = detect_intent(user_message, audience=audience)
    context = {
        "intent": intent,
        "products": [],
        "order": {},
        "vendor": {},
        "rider": {},
    }
    if intent["intent"] == "product_search":
        context["products"] = search_products_tool(user_message)
    if intent["intent"] == "order_tracking" or conversation.order_id:
        context["order"] = order_tracking_tool(actor_user, getattr(conversation.order, "order_number", "") or user_message, conversation.customer_phone)
    if audience == SmartChatConversation.AUDIENCE_VENDOR or intent["intent"] == "vendor_support":
        context["vendor"] = vendor_support_tool(actor_user)
    if audience == SmartChatConversation.AUDIENCE_RIDER or intent["intent"] == "rider_support":
        context["rider"] = rider_support_tool(rider or getattr(conversation, "rider_profile", None))
    return context


def operations_fallback_reply(conversation, user_message, context):
    intent = context.get("intent", {}).get("intent", "general_support")
    products = context.get("products") or []
    order = context.get("order") or {}
    vendor = context.get("vendor") or {}
    rider = context.get("rider") or {}

    if intent == "sensitive_admin_action":
        return "I can help prepare this for review, but I cannot approve refunds, payouts, KYC, account deletion, or price changes. I have created an admin support ticket so Arolana can review it safely."
    if _looks_like_greeting(user_message):
        return _greeting_reply()
    if _looks_like_thanks(user_message):
        return _thanks_reply()
    if _looks_like_rfq_question(user_message):
        return _rfq_guide_reply()
    if _looks_like_product_interest(user_message):
        if products:
            return _product_interest_with_matches_reply(products, user_message)
        return _product_interest_no_match_reply(user_message)
    if _looks_like_shopping_question(user_message):
        return _shopping_guide_reply()
    if _looks_like_checkout_question(user_message):
        return _checkout_guide_reply()
    if _looks_like_account_question(user_message) and not _looks_like_vendor_onboarding_question(user_message):
        return _account_guide_reply()
    if _looks_like_step_by_step_question(user_message):
        return _step_by_step_reply(conversation.audience)
    if _looks_like_vendor_onboarding_question(user_message):
        return (
            "Yes. To become a vendor on Arolana, open the vendor registration flow and submit your store details, contact information, pickup address, and KYC documents.\n\n"
            "What you will need:\n"
            "• Store or company name\n"
            "• Email and phone number\n"
            "• Business/vendor type, such as Manufacturer, Distributor, Wholesaler, Retailer, or Service Provider\n"
            "• Business, warehouse, or pickup address\n"
            "• KYC documents for verification\n"
            "• Bank account details for payouts\n\n"
            "After submission, Arolana admin reviews your profile. Once approved, you can upload products, receive orders, chat with customers, and choose a subscription plan for more visibility and higher limits."
        )
    if intent == "product_search":
        if products:
            return _product_interest_with_matches_reply(products, user_message)
        return _product_interest_no_match_reply(user_message)
    if intent == "order_tracking":
        if order:
            return f"Order {order.get('order_number')} is currently {order.get('status')} with payment {order.get('payment_status')}. Delivery status: {order.get('delivery_status') or 'not assigned yet'}. Total: {order.get('total_display')}."
        return "I could not find that order from the details available. Send the order number, tracking code, or phone number used at checkout."
    if intent == "vendor_support" and vendor:
        product_limit = _product_limit_label(vendor.get("product_limit"))
        products_count = int(vendor.get("products_count") or 0)
        upload_line = (
            "You can still upload products under your current plan."
            if vendor.get("can_upload_products")
            else "You have reached your current product upload limit. Upgrade your plan or contact admin if this looks wrong."
        )
        verification = f"Verified: {_yes_no(vendor.get('is_verified'))}"
        if vendor.get("vendor_type") == "manufacturer":
            verification += f" • Manufacturer verified: {_yes_no(vendor.get('manufacturer_verified'))}"
        return (
            f"Here is your vendor account snapshot for {vendor.get('store_name')}:\n\n"
            f"• Plan: {vendor.get('subscription') or 'Free Vendor'}\n"
            f"• Subscription active: {_yes_no(vendor.get('subscription_active'))}\n"
            f"• Products: {products_count:,} of {product_limit}\n"
            f"• Approval status: {_human_status(vendor.get('approval_status'))}\n"
            f"• KYC status: {_human_status(vendor.get('kyc_status'))}\n"
            f"• {verification}\n"
            f"• Wallet balance: {_money(vendor.get('wallet_balance'))}\n\n"
            f"{upload_line}\n\n"
            "You can ask me to check product upload limits, subscription benefits, KYC next steps, wallet, orders, or why a product is not visible to customers."
        )
    if intent == "rider_support" and rider:
        return f"You are {'online' if rider.get('online') else 'offline'} and {'available' if rider.get('available') else 'busy'}. Active deliveries: {rider.get('active_deliveries')}. Wallet balance: {rider.get('wallet_balance') or '0'}."
    if intent in {"payment_support", "refund_support", "human_handoff"}:
        return "I have enough context to alert Arolana support. I created a support ticket so an admin can review and respond from the dashboard."
    if intent == "faq":
        return _step_by_step_reply(conversation.audience)
    return (
        "Tell me the product, brand, category, technology, order number, or shopping task you need help with. "
        "For catalog questions I will check Arolana products, specifications, reviews, ratings, Q&A, stock, "
        "warranty, delivery, and prices before answering. If the needed information is not listed, I will say so "
        "and connect you with Arolana support."
    )


def ai_operations_reply(
    conversation,
    user_message,
    audience="customer",
    actor_user=None,
    rider=None,
    customer_memory=None,
):
    context = build_operations_context(conversation, user_message, audience=audience, actor_user=actor_user, rider=rider)
    context["customer_memory"] = customer_memory or []
    intent = context.get("intent", {})
    conversation.audience = audience or conversation.audience
    conversation.current_intent = intent.get("intent", "")
    conversation.urgency = intent.get("urgency", "normal")
    conversation.context = context
    conversation.save(update_fields=["audience", "current_intent", "urgency", "context", "updated_at"])

    if intent.get("requires_handoff"):
        priority = "urgent" if intent.get("urgency") == "urgent" else "high"
        create_support_ticket(
            conversation,
            title=f"{conversation.get_audience_display()} support: {intent.get('intent', 'support')}",
            description=user_message,
            intent=intent.get("intent", ""),
            priority=priority,
            metadata=context,
        )
        return operations_fallback_reply(conversation, user_message, context), context

    api_key = getattr(settings, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return operations_fallback_reply(conversation, user_message, context), context

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = getattr(settings, "AROLANA_AI_MODEL", "gpt-5.5")
        instructions = """
You are Arolana Chat, the intelligent operations assistant for a manufacturer-focused marketplace.
Act like a smart human support agent: warm, concise, practical, and accurate.
Use only the provided Arolana database context. Do not invent payments, stock, delivery times, approvals, or refunds.
You may explain status, search/recommend products, summarize vendor/rider/account information, and suggest next steps.
You must not directly approve refunds, payouts, KYC, account deletion, price changes, product approval, or vendor suspension.
For sensitive decisions, say admin review is required and offer a support ticket/handoff.
""".strip()
        input_text = f"""
AUDIENCE: {audience}
CUSTOMER/USER: {conversation.customer_display}
INTENT: {intent}
TOOLS CONTEXT: {context}
RECENT HISTORY:
{build_history(conversation)}
MESSAGE:
{user_message}
""".strip()
        response = client.responses.create(model=model, instructions=instructions, input=input_text)
        reply = (getattr(response, "output_text", "") or "").strip()
        return reply or operations_fallback_reply(conversation, user_message, context), context
    except Exception as exc:
        SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_SYSTEM,
            message="AI operations provider error. Fallback reply was used.",
            metadata={"error": str(exc)[:500]},
        )
        return operations_fallback_reply(conversation, user_message, context), context


def clean_html(value, limit=1200):
    try:
        return re.sub(r"<[^>]+>", " ", str(value or ""))[:limit]
    except Exception:
        return ""


def product_context(product):
    if not product:
        return "No product context."

    stock = getattr(product, "stock_quantity", None)
    category = getattr(getattr(product, "category", None), "name", "")
    brand = getattr(getattr(product, "brand", None), "name", "")
    sku = getattr(product, "sku", "")
    price = getattr(product, "price", "")
    compare_price = getattr(product, "compare_price", "")
    rating = getattr(product, "rating_avg", "")
    sales = getattr(product, "sales_count", "")
    description = clean_html(getattr(product, "description", ""))

    return f"""
Product name: {product.name}
SKU: {sku}
Brand: {brand or "N/A"}
Category: {category or "N/A"}
Price: {price}
Compare price: {compare_price or "N/A"}
Stock quantity: {stock if stock is not None else "N/A"}
Average rating: {rating}
Sales count: {sales}
Description summary: {description}
""".strip()


def build_history(conversation, limit=10):
    items = conversation.messages.filter(is_private_note=False).order_by("-created_at")[:limit]

    lines = []

    for msg in reversed(list(items)):
        role = {
            SmartChatMessage.SENDER_USER: "Customer",
            SmartChatMessage.SENDER_AI: "Arolana Chat",
            SmartChatMessage.SENDER_ADMIN: "Admin",
            SmartChatMessage.SENDER_SYSTEM: "System",
        }.get(msg.sender_type, msg.sender_type)

        lines.append(f"{role}: {msg.message}")

    return "\n".join(lines)


def fallback_reply(message, product=None, selected_variants=None):
    text = str(message or "").lower()
    product_name = getattr(product, "name", "this product")
    sku = getattr(product, "sku", "")
    price = getattr(product, "price", "")
    stock = getattr(product, "stock_quantity", None)

    if should_handoff(text):
        return (
            "I understand. I have alerted an Arolana admin so a real person can "
            "continue from this chat. Please keep this chat open."
        )

    if any(word in text for word in ["hello", "hi", "good morning", "good afternoon", "good evening"]):
        if product:
            return (
                f"Hello, welcome to Arolana. I can help you compare {product_name}, "
                "confirm variants, explain price, stock, delivery, warranty, reviews, "
                "or help you add it to cart."
            )

        return (
            "Hello, welcome to Arolana. I can help you search products, compare "
            "options, understand delivery and payments, or connect you with an admin."
        )

    if any(word in text for word in ["recommend", "compare", "best", "which one", "difference"]):
        if product:
            return (
                f"For {product_name}, I can compare variants, price, stock, warranty, "
                "delivery, and compatibility. Tell me what matters most: budget, "
                "performance, brand, size, color, or delivery speed."
            )

        return (
            "I can help compare products across Arolana. Tell me the product type, "
            "your budget, preferred brand, and what matters most."
        )

    if any(word in text for word in ["stock", "available", "quantity"]):
        if stock is not None:
            return (
                f"{product_name} currently shows {stock} unit(s) available. "
                "Select a variant to confirm exact variant stock before adding it to cart."
            )

        return "Please check the stock status beside the price. I can also request admin support."

    if any(word in text for word in ["price", "cost", "amount"]):
        return f"The current price for {product_name} is {price}. Variant selection may adjust the displayed price."

    if any(word in text for word in ["variant", "color", "size"]):
        return (
            "Choose your preferred color or size above. The page will update price, "
            "SKU, stock, and images for that selection."
        )

    if any(word in text for word in ["delivery", "shipping", "warranty", "return"]):
        return (
            "Delivery, warranty, and return details are listed on this product page. "
            "For special delivery questions, I can alert an admin."
        )

    if any(word in text for word in ["cart", "buy", "purchase"]):
        return (
            "Select your preferred variant and quantity, then click Add to Cart or Buy Now. "
            "The selected variant will be passed to checkout."
        )

    sku_text = f", SKU {sku}" if sku else ""

    return (
        f"I can help with {product_name}{sku_text}, including variants, price, stock, "
        "delivery, warranty, compatibility, reviews, and cart support. Ask me what you want to know."
    )


def openai_reply(conversation, user_message, product=None, selected_variants=None):
    api_key = getattr(settings, "OPENAI_API_KEY", None) or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return fallback_reply(user_message, product, selected_variants)

    try:
        from openai import OpenAI
    except Exception:
        return fallback_reply(user_message, product, selected_variants)

    model = getattr(settings, "AROLANA_AI_MODEL", "gpt-5.5")
    client = OpenAI(api_key=api_key)

    customer_context = f"""
Customer: {conversation.customer_display}
Customer email: {conversation.customer_email or getattr(conversation.user, "email", "") or "Not provided"}
Signed in: {"Yes" if conversation.user_id else "No"}
Conversation status: {conversation.status}
""".strip()

    instructions = """
You are Arolana Chat, a smart marketplace product expert.
Your job is to help customers make buying decisions and reduce support load.
Be professional, concise, warm, practical, and commercially useful.
Use the product context provided.
Do not invent stock, delivery times, policies, or payment confirmations.
If the customer asks for human/admin support, complains about payment/order/refund,
or needs account-specific help, say you are alerting admin and do not pretend to be human.
For product questions, explain variants, price, stock, compatibility, warranty,
delivery, reviews, and how to add to cart.
For signed-in customers, use current product/page context and chat history naturally.
If details are missing, ask one precise follow-up question and suggest the next action on Arolana.
""".strip()

    input_text = f"""
CUSTOMER CONTEXT:
{customer_context}

PRODUCT CONTEXT:
{product_context(product)}

SELECTED VARIANTS:
{selected_variants or {}}

RECENT CHAT HISTORY:
{build_history(conversation)}

CUSTOMER MESSAGE:
{user_message}
""".strip()

    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
        )

        reply = getattr(response, "output_text", "") or ""
        return reply.strip() or fallback_reply(user_message, product, selected_variants)

    except Exception as exc:
        SmartChatMessage.objects.create(
            conversation=conversation,
            sender_type=SmartChatMessage.SENDER_SYSTEM,
            message="AI provider error. Fallback reply was used.",
            metadata={"error": str(exc)[:500]},
        )

        return fallback_reply(user_message, product, selected_variants)


def make_conversation_title(product, message):
    product_name = getattr(product, "name", "General support")
    message_part = str(message or "").strip()[:60]

    if message_part:
        return f"{product_name} - {message_part}"

    return str(product_name)[:180]


def create_system_message(conversation, message, metadata=None):
    return SmartChatMessage.objects.create(
        conversation=conversation,
        sender_type=SmartChatMessage.SENDER_SYSTEM,
        message=message,
        metadata=metadata or {},
    )
