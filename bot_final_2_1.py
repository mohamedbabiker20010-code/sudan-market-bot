"""
🤖 Subscription Bot - Netflix & Spotify
Supports: Gift Cards + Direct Subscriptions
Languages: Arabic & English
Payment: USDT via NOWPayments
"""

import logging
import os
import json
import hmac
import hashlib
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    CallbackQuery
)
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import httpx
from supabase import create_client, Client
import google.generativeai as genai

# ─────────────────────────────────────────────
# ⚙️ CONFIG — ضع مفاتيحك هنا
# ─────────────────────────────────────────────
TELEGRAM_TOKEN     =     "8678781888:AAGLArMFTr9tCjKkcrq3KCIrAag5qGXalU8"   # من @BotFather
NOWPAYMENTS_API_KEY =   "J8PFMTW-QC8467D-HS5XJ1R-K63A1VJ"   # من nowpayments.io
NOWPAYMENTS_IPN_KEY =    "fW2WBORUal0XuZXtGkxWjC/wno2TkZ/J"     # من إعدادات NOWPayments
SUPABASE_URL       =         "https://ktpvksqcpzvzjnbshhfm.supabase.co"     # من supabase.com
SUPABASE_KEY       = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt0cHZrc3FjcHp2empuYnNoaGZtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5NDAwOTgsImV4cCI6MjA5MDUxNjA5OH0.0fk0NMRd_PzYAAZOyZq7KKrrYYabHlw7V0m9m7tD6WM"
ADMIN_CHAT_ID      = 7933955591                       # ID الخاص بك على تليغرام
YOUR_USDT_WALLET   = "TQf1ZNicuCZ4xokLfrZhdc7APcq6XgbpyU"     # محفظة USDT TRC20

# ─────────────────────────────────────────────
# بنكك 
# ─────────────────────────────────────────────
BANK_ACCOUNT_NUMBER = "2173003"
BANK_ACCOUNT_NAME   = "Mohamed Adil Babikir"
BANK_NAME           = "بنكك"

# ─────────────────────────────────────────────
# 🤖 Gemini AI
# ─────────────────────────────────────────────
GEMINI_API_KEY = "AIzaSyBEC0PjS_-Pac0JUJbRTGaZZG2ihjJu0-w"

genai.configure(api_key=GEMINI_API_KEY)

PREFERRED_GEMINI_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0",
    "gemini-1.5",
    "gemini-1.0",
]

def get_available_gemini_models():
    try:
        return [
            m.name
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
            and "gemini" in m.name
        ]
    except Exception as e:
        logging.warning(f"Could not list Gemini models: {e}")
        return []


def init_gemini_model():
    if not GEMINI_API_KEY:
        return None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logging.error(f"Gemini configuration failed: {e}")
        return None

    available_models = get_available_gemini_models()
    for model_name in PREFERRED_GEMINI_MODELS:
        full_name = model_name if model_name.startswith("models/") else f"models/{model_name}"
        if available_models and full_name not in available_models:
            continue
        try:
            model = genai.GenerativeModel(full_name)
            logging.info(f"Using Gemini model: {full_name}")
            return model
        except Exception as e:
            logging.warning(f"Gemini model {full_name} initialization failed: {e}")

    for model_name in available_models:
        try:
            model = genai.GenerativeModel(model_name)
            logging.info(f"Using Gemini model from available list: {model_name}")
            return model
        except Exception as e:
            logging.warning(f"Gemini model {model_name} initialization failed: {e}")

    logging.error("No Gemini model could be initialized.")
    return None


gemini_model = init_gemini_model()

# ─────────────────────────────────────────────
# 🔒 حماية من أخطاء CallbackQuery القديمة (BadRequest)
# ─────────────────────────────────────────────
_original_callback_answer = CallbackQuery.answer
_original_callback_edit_text = CallbackQuery.edit_message_text

async def _safe_callback_answer(self, *args, **kwargs):
    try:
        return await _original_callback_answer(self, *args, **kwargs)
    except BadRequest as e:
        if "Query is too old" in str(e) or "message is not modified" in str(e):
            logging.warning(f"Ignored BadRequest in answer: {e}")
            return
        raise

async def _safe_callback_edit_text(self, *args, **kwargs):
    try:
        return await _original_callback_edit_text(self, *args, **kwargs)
    except BadRequest as e:
        if "Query is too old" in str(e) or "message is not modified" in str(e):
            logging.warning(f"Ignored BadRequest in edit_message_text: {e}")
            return
        raise

CallbackQuery.answer = _safe_callback_answer
CallbackQuery.edit_message_text = _safe_callback_edit_text

BOT_SYSTEM_PROMPT = """أنت مساعد دعم فني لمتجر Sudan Market لبيع اشتراكات Netflix و Spotify.
مهمتك الرد على أسئلة العملاء باللهجة السودانية أو الإنجليزية حسب لغة السؤال.

معلومات المتجر:
- نبيع اشتراكات Netflix و Spotify وبطاقات هدايا
- طرق الدفع: USDT (TRC20) أو بنك الخرطوم
- رقم حساب بنك الخرطوم: 2173003 - Mohamed Adil Babikir
- بعد الدفع هيتم تسليم الطلب خلال دقائق

أسعار Netflix:
- أساسي شهر واحد: 25 ألف
- ستاندرد شهر واحد: 38 ألف
- بريميوم شهر واحد: 50 ألف
- بطاقة $15: $17
- بطاقة $30: $33

أسعار Spotify:
- فردي شهر واحد: 11 ألف
- ثنائي شهر واحد: 15 ألف
- عائلي شهر واحد: 17 ألف
- بطاقة $10: $12

تعليمات:
- رد بإيجاز ووضوح باللهجة السودانية
- إذا السؤال صعب أو خارج نطاق معرفتك، قل: "سأحولك للدعم البشري"
- لا تخترع معلومات غير موجودة أعلاه"""

# ─────────────────────────────────────────────
# 📦 الأسعار والمنتجات
# ─────────────────────────────────────────────
PRODUCTS = {
    # ── Netflix ──
    "nf_1m_basic": {
        "name_ar": "نتفلكس 1 شهر - أساسي",
        "name_en": "Netflix 1 Month - Basic",
        "price": 25000,
        "currency": "SDG",
        "type": "subscription",
        "service": "netflix",
        "emoji": "🎬"
    },
    "nf_1m_standard": {
        "name_ar": "نتفلكس 1 شهر - ستاندرد",
        "name_en": "Netflix 1 Month - Standard",
        "price": 38000,
        "currency": "SDG",
        "type": "subscription",
        "service": "netflix",
        "emoji": "🎬"
    },
    "nf_1m_premium": {
        "name_ar": "نتفلكس 1 شهر - بريميوم",
        "name_en": "Netflix 1 Month - Premium",
        "price": 50000,
        "currency": "SDG",
        "type": "subscription",
        "service": "netflix",
        "emoji": "🎬"
    },
    "nf_gc_15": {
        "name_ar": "بطاقة نتفلكس 15$",
        "name_en": "Netflix Gift Card $15",
        "price": 17.0,
        "currency": "USD",
        "type": "giftcard",
        "service": "netflix",
        "emoji": "🎁"
    },
    "nf_gc_30": {
        "name_ar": "بطاقة نتفلكس 30$",
        "name_en": "Netflix Gift Card $30",
        "price": 33.0,
        "currency": "USD",
        "type": "giftcard",
        "service": "netflix",
        "emoji": "🎁"
    },
    # ── Spotify ──
    "sp_1m_individual": {
        "name_ar": "سبوتيفاي 1 شهر - فردي",
        "name_en": "Spotify 1 Month - Individual",
        "price": 11000,
        "currency": "SDG",
        "type": "subscription",
        "service": "spotify",
        "emoji": "🎵"
    },
    "sp_1m_duo": {
        "name_ar": "سبوتيفاي 1 شهر - ثنائي",
        "name_en": "Spotify 1 Month - Duo",
        "price": 15000,
        "currency": "SDG",
        "type": "subscription",
        "service": "spotify",
        "emoji": "🎵"
    },
    "sp_1m_family": {
        "name_ar": "سبوتيفاي 1 شهر - عائلي (6 حسابات)",
        "name_en": "Spotify 1 Month - Family (6 accounts)",
        "price": 17000,
        "currency": "SDG",
        "type": "subscription",
        "service": "spotify",
        "emoji": "🎵"
    },
    "sp_gc_10": {
        "name_ar": "بطاقة سبوتيفاي 10$",
        "name_en": "Spotify Gift Card $10",
        "price": 12,
        "currency": "USD",
        "type": "giftcard",
        "service": "spotify",
        "emoji": "🎁"
    },
}

# ─────────────────────────────────────────────
# 🗄️ Supabase
# ─────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_order(order: dict):
    try:
        supabase.table("orders").insert(order).execute()
    except Exception as e:
        logging.error(f"Supabase error: {e}")

def get_order_by_payment_id(payment_id: str):
    try:
        result = supabase.table("orders").select("*").eq("payment_id", payment_id).execute()
        return result.data[0] if result.data else None
    except:
        return None

def update_order_status(payment_id: str, status: str):
    try:
        supabase.table("orders").update({"status": status}).eq("payment_id", payment_id).execute()
    except Exception as e:
        logging.error(f"Update order error: {e}")

# ─────────────────────────────────────────────
# 💳 NOWPayments API
# ─────────────────────────────────────────────
async def create_payment(amount: float, order_id: str, description: str) -> dict:
    """إنشاء طلب دفع USDT"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.nowpayments.io/v1/payment",
            headers={
                "x-api-key": NOWPAYMENTS_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "price_amount": amount,
                "price_currency": "usd",
                "pay_currency": "usdttrc20",   # USDT على شبكة Tron
                "order_id": order_id,
                "order_description": description,
                "ipn_callback_url": "https://YOUR_SERVER.com/webhook/nowpayments"
            }
        )
        return response.json()

async def check_payment_status(payment_id: str) -> dict:
    """التحقق من حالة الدفع"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.nowpayments.io/v1/payment/{payment_id}",
            headers={"x-api-key": NOWPAYMENTS_API_KEY}
        )
        return response.json()

# ─────────────────────────────────────────────
# 🌐 المساعد اللغوي
# ─────────────────────────────────────────────
def t(user_lang: str, ar: str, en: str) -> str:
    """إرجاع النص بحسب لغة المستخدم"""
    return ar if user_lang == "ar" else en

def get_user_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "ar")

# ─────────────────────────────────────────────
# 🏠 /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
            InlineKeyboardButton("🇬🇧 English",  callback_data="lang_en"),
        ]
    ]
    await update.message.reply_text(
        "🌍 اختار لغتك / Choose your language:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────
# 🌐 اختيار اللغة
# ─────────────────────────────────────────────
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.split("_")[1]
    context.user_data["lang"] = lang
    await show_main_menu(query, context)

async def show_main_menu(query, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(context)
    keyboard = [
        [
            InlineKeyboardButton("🎬 Netflix", callback_data="service_netflix"),
            InlineKeyboardButton("🎵 Spotify", callback_data="service_spotify"),
        ],
        [InlineKeyboardButton(
            t(lang, "📦 طلباتي", "📦 My Orders"),
            callback_data="my_orders"
        )],
        [InlineKeyboardButton(
            t(lang, "💬 الدعم الفني", "💬 Support"),
            callback_data="support"
        )],
    ]
    text = t(
        lang,
        " حبابك اتفضل  \n\nعندنا اشتراكات وبطاقات هدايا لـ Netflix و Spotify\n\n⚡ شوف طلبك وما تشيل هم -",
        "👋 Welcome to our store!\n\nWe provide subscriptions & gift cards for Netflix and Spotify\n\n⚡ Choose a service:"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ─────────────────────────────────────────────
# 🎬🎵 اختيار الخدمة
# ─────────────────────────────────────────────
async def show_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    service = query.data.split("_")[1]  # netflix or spotify

    keyboard = [
        [
            InlineKeyboardButton(
                t(lang, "📺 اشتراك مباشر", "📺 Direct Subscription"),
                callback_data=f"type_{service}_subscription"
            ),
            InlineKeyboardButton(
                t(lang, "🎁 بطاقة هدية", "🎁 Gift Card"),
                callback_data=f"type_{service}_giftcard"
            ),
        ],
        [InlineKeyboardButton(t(lang, "🔙 رجوع", "🔙 Back"), callback_data="main_menu")],
    ]
    name = "Netflix 🎬" if service == "netflix" else "Spotify 🎵"
    await query.edit_message_text(
        t(lang, f"اختار نوع المنتج لـ {name}:", f"Choose product type for {name}:"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ─────────────────────────────────────────────
# 📋 قائمة المنتجات
# ─────────────────────────────────────────────
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    _, service, ptype = query.data.split("_")

    filtered = {
        k: v for k, v in PRODUCTS.items()
        if v["service"] == service and v["type"] == ptype
    }

    keyboard = []
    for key, product in filtered.items():
        name = product["name_ar"] if lang == "ar" else product["name_en"]
        keyboard.append([
            InlineKeyboardButton(
                f"{product['emoji']} {name} — {product['price']} SDG",
                callback_data=f"buy_{key}"
            )
        ])
    keyboard.append([InlineKeyboardButton(
        t(lang, "🔙 رجوع", "🔙 Back"),
        callback_data=f"service_{service}"
    )])

    title = t(lang, "📋 اختار الباقة:", "📋 Choose a package:")
    await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(keyboard))

# ─────────────────────────────────────────────
# 🛒 تأكيد الشراء
# ─────────────────────────────────────────────
async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    product_key = query.data.split("buy_")[1]
    product = PRODUCTS.get(product_key)

    if not product:
        await query.answer(t(lang, " بتوفر قريب ", "❌ Product not found"), show_alert=True)
        return

    context.user_data["selected_product"] = product_key
    name = product["name_ar"] if lang == "ar" else product["name_en"]
    ptype_text = t(lang, "بطاقة هدية 🎁" if product["type"] == "giftcard" else "اشتراك مباشر 📺",
                         "Gift Card 🎁" if product["type"] == "giftcard" else "Direct Subscription 📺")

    text = t(
        lang,
        f"🛒 *تفاصيل الطلب:*\n\n"
        f"المنتج: {name}\n"
        f"النوع: {ptype_text}\n"
        f"السعر: *{product['price']} جنيه*\n\n"
        f"اختار طريقة الدفع:",
        f"🛒 *Order Details:*\n\n"
        f"Product: {name}\n"
        f"Type: {ptype_text}\n"
        f"Price: *{product['price']} SDG*\n\n"
        f"Choose payment method:"
    )

    keyboard = [
        [
            InlineKeyboardButton(t(lang, "🪙 USDT (TRC20)", "🪙 USDT (TRC20)"), callback_data="proceed_payment"),
            InlineKeyboardButton(t(lang, "🏦 بنك الخرطوم (بنكك)", "🏦 Bank of Khartoum"), callback_data="proceed_bank"),
        ],
        [InlineKeyboardButton(t(lang, "❌ إلغاء", "❌ Cancel"), callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ─────────────────────────────────────────────
# 💰 إنشاء الدفع
# ─────────────────────────────────────────────
async def proceed_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    product_key = context.user_data.get("selected_product")
    product = PRODUCTS.get(product_key)

    if not product:
        await query.edit_message_text(t(lang, "❌ حدث خطأ، حاول تاني  ", "❌ Error occurred, please restart"))
        return

    loading_msg = await query.edit_message_text(
        t(lang, "⏳ دقايق أعمل طلب الدفع...", "⏳ Creating payment request...")
    )

    user_id = query.from_user.id
    order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}"
    name = product["name_ar"] if lang == "ar" else product["name_en"]

    try:
        payment = await create_payment(product["price"], order_id, name)

        if "payment_id" not in payment:
            raise Exception("NOWPayments error")

        # حفظ الطلب في قاعدة البيانات
        save_order({
            "order_id": order_id,
            "payment_id": str(payment["payment_id"]),
            "user_id": str(user_id),
            "username": query.from_user.username or "",
            "product_key": product_key,
            "product_name": name,
            "amount": product["price"],
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        })

        pay_address = payment.get("pay_address", YOUR_USDT_WALLET)
        pay_amount  = payment.get("pay_amount", product["price"])
        payment_id  = payment["payment_id"]

        text = t(
            lang,
            f"💳 *تفاصيل الدفع:*\n\n"
            f"المبلغ: `{pay_amount}` USDT\n"
            f"الشبكة: TRC20 (Tron)\n\n"
            f"📋 *عنوان المحفظة:*\n`{pay_address}`\n\n"
            f"⚠️ أرسل المبلغ بالضبط على نفس العنوان\n"
            f"✅ هيتم تأكيد طلبك تلقائياً بعد الدفع\n\n"
            f"🔑 رقم الطلب: `{order_id}`",
            f"💳 *Payment Details:*\n\n"
            f"Amount: `{pay_amount}` USDT\n"
            f"Network: TRC20 (Tron)\n\n"
            f"📋 *Wallet Address:*\n`{pay_address}`\n\n"
            f"⚠️ Send the exact amount to this address\n"
            f"✅ Your order will be confirmed automatically\n\n"
            f"🔑 Order ID: `{order_id}`"
        )

        keyboard = [[
            InlineKeyboardButton(
                t(lang, "🔄 تحقق من الدفع", "🔄 Check Payment"),
                callback_data=f"check_{payment_id}"
            )
        ]]

        await loading_msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

        # إشعار الأدمن
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"🔔 *طلب جديد!*\n\n"
            f"👤 المستخدم: @{query.from_user.username or user_id}\n"
            f"📦 المنتج: {name}\n"
            f"💰 المبلغ: {product['price']} جنيه\n"
            f"🔑 الطلب: `{order_id}`\n"
            f"🪙 Payment ID: `{payment_id}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Payment error: {e}")
        await loading_msg.edit_text(
            t(lang,
              "❌حدث خطأ ,تواصل معنا .",
              "❌ Payment creation failed. Please contact support.")
        )

# ─────────────────────────────────────────────
# 🔄 التحقق من الدفع
# ─────────────────────────────────────────────
async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(t(get_user_lang(context), "⏳ دقايق أشوف...", "⏳ Checking..."))
    lang = get_user_lang(context)
    payment_id = query.data.split("check_")[1]

    try:
        status_data = await check_payment_status(payment_id)
        status = status_data.get("payment_status", "unknown")

        status_map = {
            "waiting":    t(lang, "⏳ في انتظار الدفع",     "⏳ Waiting for payment"),
            "confirming": t(lang, "🔄 جاري أؤكد",         "🔄 Confirming"),
            "confirmed":  t(lang, "✅ تم التأكيد",            "✅ Confirmed"),
            "sending":    t(lang, "📤 جاري أعالج",         "📤 Processing"),
            "finished":   t(lang, "✅ تم الدفع بنجاح!",       "✅ Payment successful!"),
            "failed":     t(lang, "❌ فشل الدفع",             "❌ Payment failed"),
            "expired":    t(lang, "⌛ انتهت صلاحية الطلب",   "⌛ Payment expired"),
        }

        status_text = status_map.get(status, status)

        if status == "finished":
            update_order_status(payment_id, "paid")
            await query.edit_message_text(
                t(lang,
                  f"🎉 *تم الدفع بنجاح!*\n\nهيتم تسليم طلبك خلال دقائق.\nشكراً على ثقتك فينا! 🙏",
                  f"🎉 *Payment Successful!*\n\nYour order will be delivered in minutes.\nThank you! 🙏"),
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ *دفع مكتمل!*\nPayment ID: `{payment_id}`\nيرجى تنفيذ الطلب فوراً 🚀",
                parse_mode="Markdown"
            )
        else:
            keyboard = [[InlineKeyboardButton(
                t(lang, "🔄 شوف تاني", "🔄 Check Again"),
                callback_data=f"check_{payment_id}"
            )]]
            await query.edit_message_text(
                t(lang, f"الحالة: {status_text}", f"Status: {status_text}"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logging.error(f"Check payment error: {e}")

# ─────────────────────────────────────────────
# 📦 طلباتي
# ─────────────────────────────────────────────
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    user_id = str(query.from_user.id)

    try:
        result = supabase.table("orders").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        orders = result.data

        if not orders:
            await query.edit_message_text(
                t(lang, "📭 ما عندك طلبات", "📭 No orders yet"),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(t(lang, "🔙 رجوع", "🔙 Back"), callback_data="main_menu")
                ]])
            )
            return

        text = t(lang, "📦 *آخر طلباتك:*\n\n", "📦 *Your recent orders:*\n\n")
        status_emoji = {"pending": "⏳", "paid": "✅", "delivered": "🎉", "failed": "❌"}

        for order in orders:
            emoji = status_emoji.get(order["status"], "📋")
            text += f"{emoji} {order['product_name']} — {order['amount']} SDG\n"
            text += f"   `{order['order_id']}`\n\n"

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(t(lang, "🔙 رجوع", "🔙 Back"), callback_data="main_menu")
            ]])
        )
    except Exception as e:
        logging.error(f"My orders error: {e}")

# ─────────────────────────────────────────────
# 💬 الدعم الفني
# ─────────────────────────────────────────────
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)

    text = t(
        lang,
        "💬 *دعم Gemini الذكي*\n\nلو عندك سؤال خش هنا\n\nhttps://t.me/Subakor\n\nفي الخدمة لو عايز مساعدة تانية.",
        "💬 *Gemini Support*\n\nType your question here and Gemini will reply directly.\n\nhttps://t.me/Subakor\n\nIf you need extra help, we will transfer you to human support."
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, "🔙 رجوع", "🔙 Back"), callback_data="main_menu")
        ]])
    )

# ─────────────────────────────────────────────
# 🏦 الدفع عبر بنك الخرطوم
# ─────────────────────────────────────────────
async def proceed_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_lang(context)
    product_key = context.user_data.get("selected_product")
    product = PRODUCTS.get(product_key)

    if not product:
        await query.edit_message_text(t(lang, "❌ حدث خطأ، ابدأ من جديد", "❌ Error occurred, please restart"))
        return

    name = product["name_ar"] if lang == "ar" else product["name_en"]
    user_id = query.from_user.id
    order_id = f"ORD_{user_id}_{int(datetime.now().timestamp())}"
    context.user_data["pending_bank_order"] = {
        "order_id": order_id,
        "product_key": product_key,
        "product_name": name,
        "amount": product["price"],
        "user_id": user_id,
        "username": query.from_user.username or "",
    }

    text = t(
        lang,
        f"🏦 *تفاصيل الدفع عبر بنك الخرطوم:*\n\n"
        f"🏦 البنك: {BANK_NAME}\n"
        f"👤 الاسم: `{BANK_ACCOUNT_NAME}`\n"
        f"🔢 رقم الحساب: `{BANK_ACCOUNT_NUMBER}`\n"
        f"💰 المبلغ: *{product['price']} جنيه*\n\n"
        f"📸 بعد التحويل أرسل الإشعار هنا!\n"
        f"⏳ أراجع الطلب وأرجع لك",
        f"🏦 *Bank of Khartoum Payment Details:*\n\n"
        f"🏦 Bank: Bank of Khartoum\n"
        f"👤 Name: `{BANK_ACCOUNT_NAME}`\n"
        f"🔢 Account: `{BANK_ACCOUNT_NUMBER}`\n"
        f"💰 Amount: *{product['price']} SDG*\n\n"
        f"📸 After transfer, send the receipt photo here\n"
        f"⏳ Your order will be reviewed and confirmed in minutes"
    )

    context.user_data["waiting_bank_receipt"] = True
    await query.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(t(lang, "❌ إلغاء", "❌ Cancel"), callback_data="main_menu")
        ]])
    )

async def handle_bank_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استقبال صورة الإشعار من المستخدم"""
    if not context.user_data.get("waiting_bank_receipt"):
        return

    lang = get_user_lang(context)
    order_info = context.user_data.get("pending_bank_order")

    if not order_info:
        return

    # تأكيد للمستخدم
    await update.message.reply_text(
        t(lang,
          "✅ تم استلام الاشعار!*\n\nأراجع الطلب وأرجع لك. شكراً! 🙏",
          "✅ *Receipt received!*\n\nYour order will be reviewed and confirmed shortly. Thank you! 🙏"),
        parse_mode="Markdown"
    )

    # إرسال الإيصال للأدمن
    caption = (
        f"📸 *إشعار دفع جديد - بنك الخرطوم*\n\n"
        f"👤 المستخدم: @{order_info['username'] or order_info['user_id']}\n"
        f"📦 المنتج: {order_info['product_name']}\n"
        f"💰 المبلغ: {order_info['amount']} جنيه\n"
        f"🔑 الطلب: `{order_info['order_id']}`\n\n"
        f"✅ للتأكيد أرسل: /confirm_{order_info['order_id']}\n"
        f"❌ للرفض أرسل: /reject_{order_info['order_id']}"
    )

    await context.bot.forward_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=update.message.chat_id,
        message_id=update.message.message_id
    )
    await context.bot.send_message(ADMIN_CHAT_ID, caption, parse_mode="Markdown")

    # حفظ الطلب
    save_order({
        "order_id": order_info["order_id"],
        "payment_id": f"BANK_{order_info['order_id']}",
        "user_id": str(order_info["user_id"]),
        "username": order_info["username"],
        "product_key": order_info["product_key"],
        "product_name": order_info["product_name"],
        "amount": order_info["amount"],
        "status": "pending_bank",
        "created_at": datetime.now().isoformat(),
    })

    context.user_data["waiting_bank_receipt"] = False
    context.user_data["pending_bank_order"] = None


# ─────────────────────────────────────────────
# 🤖 Gemini AI - الرد التلقائي على الرسائل
# ─────────────────────────────────────────────
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يرد Gemini على أي رسالة نصية من العميل"""
    logging.info(f"handle_text_message called with chat_id={update.message.chat_id} text={update.message.text!r}")

    # تجاهل رسائل الأدمن
    if update.message.chat_id == ADMIN_CHAT_ID:
        logging.info("Message from admin ignored")
        return

    # تجاهل إذا كان ينتظر إيصال بنكي
    if context.user_data.get("waiting_bank_receipt"):
        logging.info("Waiting bank receipt; ignoring text message")
        return

    user_message = update.message.text
    lang = get_user_lang(context)

    thinking_msg = await update.message.reply_text(
        "⏳ جاري أرد..." if lang == "ar" else "⏳ Thinking..."
    )

    try:
        global gemini_model
        if gemini_model is None:
            gemini_model = init_gemini_model()

        if gemini_model is None:
            logging.error("gemini_model is None inside handle_text_message")
            raise RuntimeError("Gemini model is not available")

        prompt = f"{BOT_SYSTEM_PROMPT}\n\nرسالة العميل: {user_message}"
        logging.info(f"Sending prompt to Gemini: {prompt[:500]}...")
        response = gemini_model.generate_content(prompt)
        logging.info(f"Gemini response: {response}")

        # دعم توافقية مخرجات نموذج Gemini (text أو candidates)
        reply = None
        if hasattr(response, 'text') and response.text:
            reply = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            first_candidate = response.candidates[0]
            reply = getattr(first_candidate, 'content', None) or getattr(first_candidate, 'text', None)

        if not reply:
            logging.warning("Gemini returned an empty response; falling back to human support message")
            reply = t(lang,
                      "❌ عذراً، Gemini ما قادر يرد حاليا. في الخدمة لو عايز مساعدة تانية.",
                      "❌ Sorry, Gemini cannot respond right now. Please contact support.")

        # إذا قال Gemini يحول للدعم البشري
        if "سأحولك للدعم البشري" in reply or "human support" in reply.lower():
            await thinking_msg.edit_text(
                t(lang,
                  "🔄 هيتم تحويلك لفريق الدعم البشري...\n\n📩 تواصل معنا: @YourSupportUsername",
                  "🔄 Transferring you to human support...\n\n📩 Contact us: @YourSupportUsername")
            )
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                f"🆘 *عميل يحتاج دعم بشري!*\n\n"
                f"👤 @{update.message.from_user.username or update.message.from_user.id}\n"
                f"💬 سؤاله: {user_message}",
                parse_mode="Markdown"
            )
        else:
            await thinking_msg.edit_text(reply)

    except Exception as e:
        logging.error(f"Gemini error: {e}")
        if gemini_model is None:
            await thinking_msg.edit_text(
                t(lang,
                  "❌ خدمة الذكاء الاصطناعي مش متاحة دلوقتي. تواصل مع الدعم الفني.",
                  "❌ AI service is unavailable now. Please contact support.")
            )
            return
        await thinking_msg.edit_text(
            t(lang,
              "❌ معليش، حدث خطأ. تواصل مع الدعم الفني.",
              "❌ Sorry, an error occurred. Please contact support.")
        )


# ─────────────────────────────────────────────
# 🔔 رجوع للقائمة الرئيسية
# ─────────────────────────────────────────────
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_main_menu(query, context)

# ─────────────────────────────────────────────
# 🧪 Ping test
# ─────────────────────────────────────────────
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# ─────────────────────────────────────────────
# 🚀 تشغيل البوت
# ─────────────────────────────────────────────
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CallbackQueryHandler(set_language,       pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(show_service,       pattern="^service_"))
    app.add_handler(CallbackQueryHandler(show_products,      pattern="^type_"))
    app.add_handler(CallbackQueryHandler(confirm_purchase,   pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(proceed_payment,    pattern="^proceed_payment$"))
    app.add_handler(CallbackQueryHandler(check_payment,      pattern="^check_"))
    app.add_handler(CallbackQueryHandler(my_orders,          pattern="^my_orders$"))
    app.add_handler(CallbackQueryHandler(support,            pattern="^support$"))
    app.add_handler(CallbackQueryHandler(proceed_bank,       pattern="^proceed_bank$"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_bank_receipt))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("🤖 Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
