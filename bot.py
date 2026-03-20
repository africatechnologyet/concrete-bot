import os
import json
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler,
    filters
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from io import BytesIO

# --- Configuration & Persistence ---
CUSTOMER, LOCATION_INPUT, GRADES, PRICE, QUANTITY, EXTRAS, CONFIRM = range(7)
GRADES_LIST = ['C-15', 'C-20', 'C-25', 'C-30', 'C-35', 'C-37', 'C-40', 'C-45', 'C-50']
EXTRAS_LIST = ['Elephant pump', 'Vibrator', 'Skip', 'None']
ADMIN_IDS = [5613539602]
DATA_FILE = 'bot_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {'quote_counter': 100, 'quotes': {}}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

bot_data = load_data()

# --- PDF Generation Logic ---
def generate_pdf(pi_data):
    buffer = BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=25, bottomMargin=25)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1a3a6b'), spaceAfter=8, alignment=TA_CENTER, fontName='Helvetica-Bold')
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=7, textColor=colors.HexColor('#666666'), alignment=TA_LEFT)
    
    company_info = """
    <b>CoBuilt Solutions</b><br/>
    Addis Ababa, Ethiopia<br/>
    Phone: +251911246502<br/>
    +251911246820<br/>
    Email: CoBuilt@CoBuilt.com<br/>
    Web: www.CoBuilt.com
    """
    
    try:
        logo = Image('logo.png', width=1*inch, height=1*inch)
        logo.hAlign = 'RIGHT'
        header_table = Table([[Paragraph(company_info, header_style), logo]], colWidths=[4*inch, 3*inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        elements.append(header_table)
    except:
        elements.append(Paragraph(company_info, header_style))
    
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1a3a6b'), spaceAfter=6))
    elements.append(Paragraph("CONCRETE QUOTE", title_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cccccc'), spaceBefore=2, spaceAfter=6))
    
    date_quote = f"<para align=right><b>Date:</b> {datetime.now().strftime('%b %d, %Y')}<br/><b>Quote No:</b> {pi_data['quote_number']}</para>"
    elements.append(Paragraph(date_quote, styles['Normal']))
    elements.append(Spacer(1, 6))
    
    total_quantity = sum(pi_data['quantity'][g] for g in pi_data['grades'])
    
    customer_data = [
        ['Company:', pi_data['customer'], 'Additional service:', pi_data['extras']],
        ['Location:', pi_data['location'], 'Payment terms:', '100% advance'],
        ['Quantity:', f"{total_quantity:,.2f}m³", 'Validity of quote:', 'Valid for 3 days'],
        ['Concrete Grade:', ', '.join(pi_data['grades']), '', '']
    ]
    
    customer_table = Table(customer_data, colWidths=[1.3*inch, 2*inch, 1.6*inch, 2*inch])
    customer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#333333')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#dddddd')),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 8))
    
    table_data = [['No.', 'Description', 'Grade', 'Quantity', 'Price', 'Total Price']]
    total_amount = 0
    for idx, grade in enumerate(pi_data['grades'], 1):
        unit_price = pi_data['unit_price'][grade]
        quantity = pi_data['quantity'][grade]
        line_total = unit_price * quantity
        total_amount += line_total
        table_data.append([str(idx), 'Concrete OPC', grade, f"{quantity:,.2f}m³", f"{unit_price:,.2f}", f"{line_total:,.2f}"])
    
    table_data.append(['', '', '', '', 'Subtotal:', f"{total_amount:,.2f}"])
    vat_amount = total_amount * 0.15
    table_data.append(['', '', '', '', 'VAT (15%):', f"{vat_amount:,.2f}"])
    grand_total = total_amount + vat_amount
    table_data.append(['', '', '', '', 'Grand Total:', f"{grand_total:,.2f}"])
    
    pricing_table = Table(table_data, colWidths=[0.4*inch, 2.3*inch, 0.7*inch, 0.9*inch, 1.1*inch, 1.4*inch])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d2691e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -4), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
        ('ALIGN', (0, 1), (-1, -4), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -4), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -4), 7),
        ('GRID', (0, 0), (-1, -4), 0.5, colors.HexColor('#999999')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -4), [colors.beige, colors.white]),
        ('SPAN', (0, -3), (3, -3)),
        ('ALIGN', (4, -3), (-1, -3), 'RIGHT'),
        ('FONTNAME', (4, -3), (-1, -3), 'Helvetica-Bold'),
        ('FONTSIZE', (4, -3), (-1, -3), 8),
        ('LINEABOVE', (0, -3), (-1, -3), 1, colors.HexColor('#999999')),
        ('SPAN', (0, -2), (3, -2)),
        ('ALIGN', (4, -2), (-1, -2), 'RIGHT'),
        ('FONTNAME', (4, -2), (-1, -2), 'Helvetica'),
        ('FONTSIZE', (4, -2), (-1, -2), 7),
        ('SPAN', (0, -1), (3, -1)),
        ('ALIGN', (4, -1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (4, -1), (-1, -1), 9),
        ('LINEABOVE', (0, -1), (-1, -1), 1.5, colors.HexColor('#d2691e')),
        ('BACKGROUND', (4, -1), (-1, -1), colors.HexColor('#f5f5dc')),
    ]))
    elements.append(pricing_table)
    elements.append(Spacer(1, 6))
    
    note_style = ParagraphStyle('Note', parent=styles['Normal'], fontSize=6, textColor=colors.HexColor('#666666'))
    elements.append(Paragraph("Note: VAT (15%) has been included in the Grand Total.", note_style))
    elements.append(Spacer(1, 5))
    
    terms_style = ParagraphStyle('Terms', parent=styles['Normal'], fontSize=7)
    elements.append(Paragraph("<b>Terms & Conditions</b>", terms_style))
    elements.append(Paragraph("• Delivery Schedule: 7–10 working days.<br/>• Payment: 100% advance.<br/>• Validity: 3 days.", terms_style))
    
    try:
        signature = Image('signature.png', width=3*inch, height=1.75*inch)
        signature.hAlign = 'RIGHT'
        elements.append(signature)
    except:
        pass

    pdf.build(elements)
    buffer.seek(0)
    return buffer

# --- Handlers ---

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        f"👋 Welcome to CoBuilt Solutions PI Bot!\n\n/createpi - Create Quote\n/myquotes - View History\n/help - Help"
    )

async def create_pi(update: Update, context: CallbackContext):
    context.user_data.clear()
    context.user_data['pi_data'] = {
        'user_id': update.effective_user.id,
        'username': update.effective_user.username or update.effective_user.first_name,
        'created_at': datetime.now().isoformat()
    }
    await update.message.reply_text("👤 Enter customer/company name:", reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
    return CUSTOMER

async def customer_name(update: Update, context: CallbackContext):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    context.user_data['pi_data']['customer'] = update.message.text
    await update.message.reply_text("📍 Enter delivery location:", reply_markup=ReplyKeyboardMarkup([['⬅️ Back', '❌ Cancel']], resize_keyboard=True))
    return LOCATION_INPUT

async def location_input(update: Update, context: CallbackContext):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    if update.message.text == '⬅️ Back': return await create_pi(update, context)
    context.user_data['pi_data']['location'] = update.message.text
    keyboard = [GRADES_LIST[i:i+4] for i in range(0, len(GRADES_LIST), 4)]
    keyboard.append(['⬅️ Back', '❌ Cancel'])
    await update.message.reply_text("🧱 Select grades (comma separated):", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return GRADES

async def grades(update: Update, context: CallbackContext):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    grades = [g.strip().upper() for g in update.message.text.split(',') if g.strip() in GRADES_LIST]
    if not grades:
        await update.message.reply_text("❌ Please select valid grades.")
        return GRADES
    context.user_data['pi_data']['grades'] = grades
    context.user_data['pi_data']['unit_price'] = {}
    context.user_data['pi_data']['quantity'] = {}
    context.user_data['current_grade_index'] = 0
    grade = grades[0]
    await update.message.reply_text(f"💵 Grade: {grade}\nEnter price per m³:", reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
    return PRICE

async def price(update: Update, context: CallbackContext):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    idx = context.user_data['current_grade_index']
    grade = context.user_data['pi_data']['grades'][idx]
    try:
        context.user_data['pi_data']['unit_price'][grade] = float(update.message.text.replace(',', ''))
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number.")
        return PRICE
    await update.message.reply_text(f"📏 Grade: {grade}\nEnter quantity in m³:")
    return QUANTITY

async def quantity(update: Update, context: CallbackContext):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    idx = context.user_data['current_grade_index']
    grade = context.user_data['pi_data']['grades'][idx]
    try:
        context.user_data['pi_data']['quantity'][grade] = float(update.message.text.replace(',', ''))
    except ValueError:
        await update.message.reply_text("❌ Enter a valid number.")
        return QUANTITY
    
    context.user_data['current_grade_index'] += 1
    if context.user_data['current_grade_index'] < len(context.user_data['pi_data']['grades']):
        next_grade = context.user_data['pi_data']['grades'][context.user_data['current_grade_index']]
        await update.message.reply_text(f"💵 Grade: {next_grade}\nEnter price per m³:")
        return PRICE
    else:
        keyboard = [EXTRAS_LIST, ['❌ Cancel']]
        await update.message.reply_text("🧰 Extras (comma separated):", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return EXTRAS

async def extras(update: Update, context: CallbackContext):
    context.user_data['pi_data']['extras'] = update.message.text
    pi = context.user_data['pi_data']
    summary = f"📋 *DRAFT*\nCustomer: {pi['customer']}\nLocation: {pi['location']}\n"
    keyboard = [[InlineKeyboardButton("✅ Submit", callback_data='confirm_yes')], [InlineKeyboardButton("❌ Cancel", callback_data='confirm_no')]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CONFIRM

async def confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.data == 'confirm_yes':
        global bot_data
        bot_data['quote_counter'] += 1
        q_num = f"RMX-{bot_data['quote_counter']:04d}"
        pi = context.user_data['pi_data']
        pi['quote_number'] = q_num
        pi['status'] = 'pending'
        bot_data['quotes'][q_num] = pi
        save_data(bot_data)
        await query.edit_message_text(f"✅ Submitted! Quote No: {q_num}")
        # Notify Admin
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, f"🔔 New Quote: {q_num}\nCustomer: {pi['customer']}", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"approve_{q_num}")]]) )
    return ConversationHandler.END

async def handle_approval(update: Update, context: CallbackContext):
    query = update.callback_query
    _, q_num = query.data.split('_')
    pi = bot_data['quotes'].get(q_num)
    if pi:
        pi['status'] = 'approved'
        save_data(bot_data)
        pdf = generate_pdf(pi)
        await context.bot.send_document(pi['user_id'], document=pdf, filename=f"{q_num}.pdf", caption="Approved!")
        await query.edit_message_text(f"Quote {q_num} Approved & Sent.")

async def cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def handle_start_over(update: Update, context: CallbackContext):
    return await create_pi(update, context)

def main():
    app = Application.builder().token("8513160001:AAELK8YtZxL34U2tWrNsXLOGooJEVSWqKWI").build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('createpi', create_pi), CallbackQueryHandler(handle_start_over, pattern='^start_over$')],
        states={
            CUSTOMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name)],
            LOCATION_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_input)],
            GRADES: [MessageHandler(filters.TEXT & ~filters.COMMAND, grades)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity)],
            EXTRAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, extras)],
            CONFIRM: [CallbackQueryHandler(confirm)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(conv)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(handle_approval, pattern='^approve_'))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()