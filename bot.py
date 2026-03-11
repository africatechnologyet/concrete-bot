"""
CoBuilt Ready Mix Telegram Bot
Built with python-telegram-bot library
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
import logging
from datetime import datetime, timedelta

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
(AWAITING_NAME, AWAITING_COMPANY, AWAITING_PHONE,
 SELECTING_CONCRETE_TYPE, SELECTING_GRADE, ENTERING_QUANTITY,
 ENTERING_ADDRESS, SELECTING_DATE, SELECTING_TIME,
 ENTERING_INSTRUCTIONS) = range(10)

# User data storage (use database in production)
user_profiles = {}
orders = {}
order_counter = 1


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user_id = update.effective_user.id
    
    # Check if user profile exists
    if user_id not in user_profiles:
        await update.message.reply_text(
            "👋 Welcome to CoBuilt Ready Mix PI!\n\n"
            "We provide premium ready-mix concrete solutions for all your construction needs.\n\n"
            "🏗️ What we offer:\n"
            "• Fresh ready-mix concrete delivery\n"
            "• Multiple concrete grades & mixes\n"
            "• Flexible delivery scheduling\n"
            "• Expert technical support\n\n"
            "Before we start, let me get your details.\n\n"
            "What's your name?"
        )
        return AWAITING_NAME
    
    # Existing user - show main menu
    await show_main_menu(update, context)
    return ConversationHandler.END


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display main menu"""
    keyboard = [
        [InlineKeyboardButton("🏗️ Order Concrete", callback_data='order_concrete')],
        [InlineKeyboardButton("💰 Get Quote", callback_data='get_quote')],
        [InlineKeyboardButton("📋 My Orders", callback_data='my_orders')],
        [InlineKeyboardButton("📞 Contact Us", callback_data='contact'),
         InlineKeyboardButton("❓ Help", callback_data='help')],
        [InlineKeyboardButton("ℹ️ About Us", callback_data='about')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "How can we help you today?\n\nChoose an option below:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)


# ONBOARDING FLOW
async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive user's name"""
    context.user_data['name'] = update.message.text
    await update.message.reply_text(
        f"Thanks {update.message.text}!\n\n"
        "What's your company name?\n"
        "(or type 'Individual' if personal use)"
    )
    return AWAITING_COMPANY


async def receive_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive company name"""
    context.user_data['company'] = update.message.text
    await update.message.reply_text(
        "Great! Last thing - your phone number?\n"
        "(We'll use this for delivery coordination)"
    )
    return AWAITING_PHONE


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number and complete profile"""
    user_id = update.effective_user.id
    context.user_data['phone'] = update.message.text
    
    # Save profile
    user_profiles[user_id] = {
        'name': context.user_data['name'],
        'company': context.user_data['company'],
        'phone': context.user_data['phone']
    }
    
    keyboard = [
        [InlineKeyboardButton("✏️ Edit Details", callback_data='edit_profile')],
        [InlineKeyboardButton("✅ Continue", callback_data='continue_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✅ Profile created!\n\n"
        f"Name: {context.user_data['name']}\n"
        f"Company: {context.user_data['company']}\n"
        f"Phone: {context.user_data['phone']}",
        reply_markup=reply_markup
    )
    return ConversationHandler.END


# ORDER FLOW
async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start concrete order process"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Standard Mix (M15/M20)", callback_data='type_standard')],
        [InlineKeyboardButton("Premium Mix (M25/M30)", callback_data='type_premium')],
        [InlineKeyboardButton("High Strength (M35/M40)", callback_data='type_highstrength')],
        [InlineKeyboardButton("Special Mix (Custom)", callback_data='type_special')],
        [InlineKeyboardButton("❓ Not Sure? Help Me Choose", callback_data='help_choose')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🏗️ NEW CONCRETE ORDER\n\n"
        "Let's get your order details. I'll ask you a few quick questions.\n\n"
        "First, what type of concrete do you need?",
        reply_markup=reply_markup
    )
    return SELECTING_CONCRETE_TYPE


async def select_concrete_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle concrete type selection"""
    query = update.callback_query
    await query.answer()
    
    type_map = {
        'type_standard': ('Standard Mix', ['M15 - General Purpose', 'M20 - Foundation & Slabs']),
        'type_premium': ('Premium Mix', ['M25 - Beams & Columns', 'M30 - Heavy Load']),
        'type_highstrength': ('High Strength', ['M35 - Specialized', 'M40 - High-Rise']),
    }
    
    selected = query.data
    if selected in type_map:
        context.user_data['concrete_type'] = type_map[selected][0]
        grades = type_map[selected][1]
        
        keyboard = [[InlineKeyboardButton(grade, callback_data=f'grade_{grade.split()[0]}')] 
                   for grade in grades]
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data='order_concrete')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ {type_map[selected][0]} selected\n\n"
            "Which grade exactly?",
            reply_markup=reply_markup
        )
        return SELECTING_GRADE
    
    return SELECTING_CONCRETE_TYPE


async def select_grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle grade selection"""
    query = update.callback_query
    await query.answer()
    
    grade = query.data.replace('grade_', '')
    context.user_data['grade'] = grade
    
    await query.edit_message_text(
        f"✅ {grade} Concrete selected\n\n"
        "How many cubic meters do you need?\n\n"
        "Type the quantity (e.g., 5 or 7.5)"
    )
    return ENTERING_QUANTITY


async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive concrete quantity"""
    try:
        quantity = float(update.message.text)
        context.user_data['quantity'] = quantity
        
        await update.message.reply_text(
            f"✅ Quantity: {quantity} cubic meters\n\n"
            "What's your delivery address?\n\n"
            "(Include street, city, postal code)"
        )
        return ENTERING_ADDRESS
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number (e.g., 5 or 7.5)"
        )
        return ENTERING_QUANTITY


async def receive_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive delivery address"""
    context.user_data['address'] = update.message.text
    
    # Generate next 4 days
    keyboard = []
    for i in range(1, 5):
        date = datetime.now() + timedelta(days=i)
        label = "Tomorrow" if i == 1 else date.strftime("%b %d")
        keyboard.append([InlineKeyboardButton(
            f"📅 {label}",
            callback_data=f'date_{date.strftime("%Y-%m-%d")}'
        )])
    keyboard.append([InlineKeyboardButton("📅 Choose Different Date", callback_data='custom_date')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "✅ Address saved\n\n"
        "When do you need delivery?\n\n"
        "Choose preferred date:",
        reply_markup=reply_markup
    )
    return SELECTING_DATE


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle date selection"""
    query = update.callback_query
    await query.answer()
    
    date_str = query.data.replace('date_', '')
    context.user_data['delivery_date'] = date_str
    
    keyboard = [
        [InlineKeyboardButton("🌅 Morning (6 AM - 10 AM)", callback_data='time_morning')],
        [InlineKeyboardButton("☀️ Mid-Day (10 AM - 2 PM)", callback_data='time_midday')],
        [InlineKeyboardButton("🌤️ Afternoon (2 PM - 6 PM)", callback_data='time_afternoon')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    formatted_date = date_obj.strftime("%B %d, %Y")
    
    await query.edit_message_text(
        f"✅ Date: {formatted_date}\n\n"
        "What time slot works best?",
        reply_markup=reply_markup
    )
    return SELECTING_TIME


async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle time slot selection"""
    query = update.callback_query
    await query.answer()
    
    time_map = {
        'time_morning': 'Morning (6 AM - 10 AM)',
        'time_midday': 'Mid-Day (10 AM - 2 PM)',
        'time_afternoon': 'Afternoon (2 PM - 6 PM)'
    }
    
    context.user_data['delivery_time'] = time_map[query.data]
    
    keyboard = [
        [InlineKeyboardButton("⏭️ Skip - No Special Instructions", callback_data='skip_instructions')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Time: {time_map[query.data]}\n\n"
        "Any special instructions?\n"
        "(Site access, pouring requirements, contact person, etc.)\n\n"
        "Type your notes or press Skip",
        reply_markup=reply_markup
    )
    return ENTERING_INSTRUCTIONS


async def finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show order summary and confirmation"""
    # Handle both text input and skip button
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        instructions = "None"
    else:
        instructions = update.message.text
    
    context.user_data['instructions'] = instructions
    
    user_id = update.effective_user.id
    profile = user_profiles[user_id]
    
    # Calculate estimated price
    quantity = context.user_data['quantity']
    base_price = quantity * 3000  # ₹3000 per cubic meter
    
    date_obj = datetime.strptime(context.user_data['delivery_date'], "%Y-%m-%d")
    formatted_date = date_obj.strftime("%B %d, %Y")
    
    summary = (
        "📋 ORDER SUMMARY\n\n"
        f"Customer: {profile['name']} ({profile['company']})\n"
        f"Phone: {profile['phone']}\n\n"
        f"🏗️ Product: {context.user_data['grade']} {context.user_data['concrete_type']}\n"
        f"📦 Quantity: {context.user_data['quantity']} cubic meters\n"
        f"📍 Address: {context.user_data['address']}\n"
        f"📅 Date: {formatted_date}\n"
        f"⏰ Time: {context.user_data['delivery_time']}\n"
        f"📝 Notes: {instructions}\n\n"
        f"💰 Estimated Price: ₹{base_price:,.0f}\n"
        "(Final price may vary based on site conditions)\n\n"
        "Confirm this order?"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Order", callback_data='confirm_order')],
        [InlineKeyboardButton("✏️ Edit Details", callback_data='order_concrete')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_order')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await query.edit_message_text(summary, reply_markup=reply_markup)
    else:
        await update.message.reply_text(summary, reply_markup=reply_markup)
    
    return ConversationHandler.END


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and save the order"""
    global order_counter
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    order_id = f"ORD-2024-{order_counter:06d}"
    order_counter += 1
    
    # Save order
    orders[order_id] = {
        'user_id': user_id,
        'order_data': context.user_data.copy(),
        'status': 'Pending Confirmation',
        'created_at': datetime.now()
    }
    
    keyboard = [
        [InlineKeyboardButton("📋 View My Orders", callback_data='my_orders')],
        [InlineKeyboardButton("🏗️ Order More", callback_data='order_concrete')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎉 ORDER CONFIRMED!\n\n"
        f"Order ID: #{order_id}\n"
        "Status: Pending Confirmation\n\n"
        "What happens next:\n"
        "1️⃣ Our team will review your order (5-10 mins)\n"
        "2️⃣ You'll receive final price confirmation\n"
        "3️⃣ You'll get delivery tracking details\n"
        "4️⃣ Driver will call 30 mins before arrival\n\n"
        f"📧 Confirmation sent to: {user_profiles[user_id]['phone']}\n\n"
        f"You can track your order anytime using:\n"
        f"/track {order_id}\n\n"
        "Need help? /contact",
        reply_markup=reply_markup
    )


# MY ORDERS
async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display user's orders"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user_orders = {oid: data for oid, data in orders.items() 
                  if data['user_id'] == user_id}
    
    if not user_orders:
        keyboard = [[InlineKeyboardButton("🏗️ Place First Order", callback_data='order_concrete')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📋 YOUR ORDERS\n\n"
            "You haven't placed any orders yet.\n\n"
            "Ready to order?",
            reply_markup=reply_markup
        )
        return
    
    message = "📋 YOUR ORDERS\n\n"
    
    # Show active orders
    active = [o for o in user_orders.items() if o[1]['status'] != 'Delivered']
    if active:
        message += "Active Orders:\n━━━━━━━━━━━━━━━━\n"
        for oid, odata in active[:3]:
            data = odata['order_data']
            message += (
                f"🟢 Order #{oid}\n"
                f"{data['grade']} Concrete - {data['quantity']} m³\n"
                f"Status: {odata['status']}\n\n"
            )
    
    keyboard = [
        [InlineKeyboardButton("🏗️ Order Again", callback_data='order_concrete')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message, reply_markup=reply_markup)


# CONTACT & HELP
async def show_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show contact information"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("💬 Chat with Support", callback_data='chat_support')],
        [InlineKeyboardButton("📞 Request Callback", callback_data='request_callback')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📞 CONTACT COBUILT READY MIX\n\n"
        "📱 Phone: +91-1800-XXX-XXXX\n"
        "📧 Email: orders@cobuiltreadymix.com\n"
        "🌐 Website: www.cobuiltreadymix.com\n\n"
        "🏢 Head Office:\n"
        "Industrial Area, Sector 5\n"
        "Mumbai, Maharashtra 400001\n\n"
        "⏰ Business Hours:\n"
        "Mon-Sat: 6:00 AM - 8:00 PM\n"
        "Sunday: 8:00 AM - 4:00 PM\n"
        "24/7 Emergency: +91-9999-XXX-XXX",
        reply_markup=reply_markup
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help menu"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🏗️ How to Order", callback_data='help_order')],
        [InlineKeyboardButton("💰 Pricing Information", callback_data='help_pricing')],
        [InlineKeyboardButton("🚚 Delivery Details", callback_data='help_delivery')],
        [InlineKeyboardButton("🏠 Main Menu", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "❓ HOW CAN I HELP YOU?\n\n"
        "Choose a topic:",
        reply_markup=reply_markup
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    
    handlers = {
        'main_menu': show_main_menu,
        'continue_to_menu': show_main_menu,
        'contact': show_contact,
        'help': show_help,
        'my_orders': show_orders,
        'skip_instructions': finalize_order,
        'confirm_order': confirm_order,
    }
    
    if query.data in handlers:
        await handlers[query.data](update, context)
    else:
        await query.answer()


def main():
    """Start the bot"""
    # Your bot token
    TOKEN = "8513160001:AAGF-ZeUTV9iqWiLWZE_tLYjSF3dn_bIIuk"
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Onboarding conversation handler
    onboarding_conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            AWAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
            AWAITING_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_company)],
            AWAITING_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    
    # Order conversation handler
    order_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_order, pattern='^order_concrete$')],
        states={
            SELECTING_CONCRETE_TYPE: [CallbackQueryHandler(select_concrete_type, pattern='^type_')],
            SELECTING_GRADE: [CallbackQueryHandler(select_grade, pattern='^grade_')],
            ENTERING_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity)],
            ENTERING_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_address)],
            SELECTING_DATE: [CallbackQueryHandler(select_date, pattern='^date_')],
            SELECTING_TIME: [CallbackQueryHandler(select_time, pattern='^time_')],
            ENTERING_INSTRUCTIONS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_order),
                CallbackQueryHandler(finalize_order, pattern='^skip_instructions$')
            ],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    
    # Add handlers
    application.add_handler(onboarding_conv)
    application.add_handler(order_conv)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    print("🤖 CoBuilt Ready Mix Bot is starting...")
    print("📱 Bot is ready to receive messages!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
