import os
import re
from django.conf import settings

from .models import SmartChatMessage


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


def should_handoff(message):
    text = str(message or "").lower()
    return any(word in text for word in HANDOFF_WORDS) or any(
        word in text for word in URGENT_WORDS
    )


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
            SmartChatMessage.SENDER_AI: "Arolana AI",
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
You are Arolana AI Assistant, a smart marketplace product expert.
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