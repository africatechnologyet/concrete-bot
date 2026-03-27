"""
CoBuilt Solutions — Concrete Quote Bot
Telegram bot that generates professional concrete quote PDFs.

Environment variables required:
  BOT_TOKEN — Telegram bot token
"""

import os
import json
import logging
from datetime import datetime
from io import BytesIO

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, Image, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Logging ──
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.WARNING)
log = logging.getLogger(__name__)

# ── Config ──
BOT_TOKEN  = os.environ.get("BOT_TOKEN")
ADMIN_IDS  = [5613539602]
DATA_FILE  = 'bot_data.json'

GRADES_LIST = ['C-15', 'C-20', 'C-25', 'C-30', 'C-35', 'C-37', 'C-40', 'C-45', 'C-50']
EXTRAS_LIST = ['Elephant pump', 'Vibrator', 'Skip', 'None']

# Conversation states
(CUSTOMER, LOCATION_INPUT, GRADES, PRICE, QUANTITY,
 PUMP_COST, EXTRAS, CONFIRM) = range(8)


# ── Data persistence ──
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


# ── Helpers ──

def grade_keyboard(selected: list) -> ReplyKeyboardMarkup:
    """Build a grade-selection keyboard that shows which grades are selected."""
    rows = []
    for i in range(0, len(GRADES_LIST), 4):
        row = []
        for g in GRADES_LIST[i:i + 4]:
            row.append(f"{'✅' if g in selected else '🔲'} {g}")
        rows.append(row)
    rows.append(['✅ Done', '❌ Cancel'])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def step_header(step: int, total: int, label: str) -> str:
    filled  = '█' * step
    empty   = '░' * (total - step)
    bar     = filled + empty
    return f"┌─── Step {step}/{total} ───┐\n│  {bar}  │\n└────────────────────┘\n\n{label}"


# ── PDF Generation ──

# Brand palette
NAVY       = colors.HexColor('#1a3a6b')
NAVY_LIGHT = colors.HexColor('#2a5298')
ORANGE     = colors.HexColor('#d2691e')
PUMP_BLUE  = colors.HexColor('#ddeeff')
GOLD       = colors.HexColor('#c9a84c')
GREY_DARK  = colors.HexColor('#333333')
GREY_MID   = colors.HexColor('#666666')
GREY_LIGHT = colors.HexColor('#dddddd')
CREAM      = colors.HexColor('#f9f6f0')
SUBTOTAL_BG= colors.HexColor('#eef2f8')
GRAND_BG   = colors.HexColor('#1a3a6b')


def generate_pdf(pi_data: dict) -> BytesIO:
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=36, leftMargin=36,
        topMargin=22, bottomMargin=22)
    elements = []
    styles = getSampleStyleSheet()

    # ── Styles ──
    def S(name, **kw):
        return ParagraphStyle(name, parent=styles['Normal'], **kw)

    title_s    = S('Title',    fontSize=20, textColor=colors.white,
                   fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=0)
    sub_s      = S('Sub',      fontSize=8,  textColor=colors.HexColor('#aec6f0'),
                   fontName='Helvetica',     alignment=TA_CENTER)
    hdr_s      = S('Hdr',      fontSize=7.5,textColor=GREY_DARK,
                   fontName='Helvetica',     leading=12)
    hdr_bold_s = S('HdrBold',  fontSize=8,  textColor=NAVY,
                   fontName='Helvetica-Bold',leading=13)
    label_s    = S('Label',    fontSize=7,  textColor=GREY_MID,
                   fontName='Helvetica-Bold')
    value_s    = S('Value',    fontSize=7.5,textColor=GREY_DARK,
                   fontName='Helvetica')
    note_s     = S('Note',     fontSize=6,  textColor=GREY_MID,
                   fontName='Helvetica-Oblique')
    terms_s    = S('Terms',    fontSize=7,  textColor=GREY_DARK,
                   fontName='Helvetica',     leading=11)
    contact_s  = S('Contact',  fontSize=7,  textColor=GREY_DARK,
                   fontName='Helvetica',     leading=12)
    approved_s = S('Approved', fontSize=7,  textColor=GREY_DARK,
                   fontName='Helvetica-Bold',alignment=TA_RIGHT)
    footer_s   = S('Footer',   fontSize=6,  textColor=GREY_MID,
                   fontName='Helvetica-Oblique', alignment=TA_CENTER)

    # ── Banner header ──
    company_block = (
        "<b>CoBuilt Solutions</b><br/>"
        "Addis Ababa, Ethiopia<br/>"
        "📞 +251 911 246 502 | +251 911 246 820<br/>"
        "✉ CoBuilt@CoBuilt.com  |  www.CoBuilt.com"
    )

    try:
        logo = Image('logo.png', width=0.9 * inch, height=0.9 * inch)
        logo.hAlign = 'RIGHT'
        banner_inner = Table(
            [[Paragraph(company_block, hdr_s), logo]],
            colWidths=[4.5 * inch, 1.1 * inch])
        banner_inner.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN',  (1, 0), (1, 0),  'RIGHT'),
        ]))
    except Exception:
        banner_inner = Paragraph(company_block, hdr_s)

    # Wrap banner in a navy box
    banner_wrapper = Table([[banner_inner]], colWidths=[pdf.width])
    banner_wrapper.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), CREAM),
        ('ROUNDEDCORNERS',(0, 0), (-1, -1), [4, 4, 4, 4]),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('BOX',           (0, 0), (-1, -1), 0.5, GREY_LIGHT),
    ]))
    elements.append(banner_wrapper)
    elements.append(Spacer(1, 8))

    # ── Navy title banner ──
    title_banner_data = [[
        Paragraph("CONCRETE QUOTE", title_s),
        Paragraph(
            f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}<br/>"
            f"<b>Quote No:</b> {pi_data['quote_number']}",
            S('TitleRight', fontSize=8, textColor=colors.white,
              fontName='Helvetica', alignment=TA_RIGHT))
    ]]
    title_banner = Table(title_banner_data, colWidths=[pdf.width * 0.6, pdf.width * 0.4])
    title_banner.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), NAVY),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
    ]))
    elements.append(title_banner)
    elements.append(Spacer(1, 10))

    # ── Customer info cards ──
    total_quantity = sum(pi_data['quantity'][g] for g in pi_data['grades'])

    def info_cell(label, value):
        return [Paragraph(label, label_s), Paragraph(str(value), value_s)]

    pump_cost_total = pi_data.get('pump_cost_per_m3', 0) * total_quantity
    has_pump = pi_data.get('pump_cost_per_m3', 0) > 0

    customer_rows = [
        [Paragraph("🏢  CUSTOMER", label_s),  Paragraph(pi_data['customer'],            value_s),
         Paragraph("📍  LOCATION", label_s),  Paragraph(pi_data['location'],            value_s)],
        [Paragraph("🧱  GRADE(S)", label_s),  Paragraph(', '.join(pi_data['grades']),   value_s),
         Paragraph("🧰  EXTRAS",   label_s),  Paragraph(pi_data['extras'],              value_s)],
        [Paragraph("📦  QUANTITY", label_s),  Paragraph(f"{total_quantity:,.2f} m³",    value_s),
         Paragraph("💳  PAYMENT",  label_s),  Paragraph("100% Advance",                value_s)],
        [Paragraph("📅  VALIDITY", label_s),  Paragraph("Valid for 3 days",             value_s),
         Paragraph("",             label_s),  Paragraph("",                             value_s)],
    ]

    cw = pdf.width / 4
    customer_table = Table(customer_rows, colWidths=[cw * 0.7, cw * 1.3, cw * 0.7, cw * 1.3])
    customer_table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), CREAM),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW',     (0, 0), (-1, -2), 0.4, GREY_LIGHT),
        ('BOX',           (0, 0), (-1, -1), 0.5, GREY_LIGHT),
        ('LINEBEFORE',    (2, 0), (2, -1),  0.4, GREY_LIGHT),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 10))

    # ── Pricing table ──
    col_w = [0.38 * inch, 2.1 * inch, 0.65 * inch, 0.9 * inch, 1.05 * inch, 1.4 * inch]

    # Header row
    def th(txt):
        return Paragraph(txt, S('TH', fontSize=8, textColor=colors.white,
                                 fontName='Helvetica-Bold', alignment=TA_CENTER))

    table_data = [[th('No.'), th('Description'), th('Grade'),
                   th('Qty (m³)'), th('Unit Price'), th('Total')]]

    total_amount = 0
    row_styles   = []
    data_row_count = 0

    for idx, grade in enumerate(pi_data['grades'], 1):
        unit_price = pi_data['unit_price'][grade]
        quantity   = pi_data['quantity'][grade]
        line_total = unit_price * quantity
        total_amount += line_total
        data_row_count += 1

        def tc(t, align=TA_CENTER):
            return Paragraph(t, S('TC', fontSize=7.5, textColor=GREY_DARK,
                                   fontName='Helvetica', alignment=align))

        table_data.append([
            tc(str(idx)),
            tc('Ready Mix Concrete (OPC)', TA_LEFT),
            tc(grade),
            tc(f"{quantity:,.2f}"),
            tc(f"{unit_price:,.2f}"),
            tc(f"{line_total:,.2f}"),
        ])

    # Pump cost row (if applicable)
    pump_row_index = None
    if has_pump:
        pump_unit  = pi_data['pump_cost_per_m3']
        pump_total = pump_unit * total_quantity
        pump_row_index = len(table_data)
        data_row_count += 1
        table_data.append([
            tc(str(len(pi_data['grades']) + 1)),
            tc('Elephant Pump Service', TA_LEFT),
            tc('—'),
            tc(f"{total_quantity:,.2f}"),
            tc(f"{pump_unit:,.2f}"),
            tc(f"{pump_total:,.2f}"),
        ])
        total_amount += pump_total

    # Subtotal / VAT / Grand Total rows
    def summary_row(label, value, bold=False):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        fs = 9 if bold else 7.5
        return ['', '', '', '',
                Paragraph(label, S('SL', fontSize=fs, fontName=fn,
                                   textColor=NAVY, alignment=TA_RIGHT)),
                Paragraph(value, S('SV', fontSize=fs, fontName=fn,
                                   textColor=GREY_DARK, alignment=TA_RIGHT))]

    vat_amount  = total_amount * 0.15
    grand_total = total_amount + vat_amount

    subtotal_row_idx    = len(table_data)
    vat_row_idx         = subtotal_row_idx + 1
    grand_total_row_idx = subtotal_row_idx + 2

    table_data.append(summary_row('Subtotal:', f"{total_amount:,.2f}"))
    table_data.append(summary_row('VAT (15%):', f"{vat_amount:,.2f}"))
    table_data.append(summary_row('GRAND TOTAL:', f"{grand_total:,.2f}", bold=True))

    pricing_table = Table(table_data, colWidths=col_w)

    ts = [
        # Header
        ('BACKGROUND',    (0, 0),  (-1, 0),               NAVY),
        ('TOPPADDING',    (0, 0),  (-1, 0),                9),
        ('BOTTOMPADDING', (0, 0),  (-1, 0),                9),
        # Data rows alternating
        ('ROWBACKGROUNDS',(0, 1),  (-1, subtotal_row_idx - 1), [colors.white, CREAM]),
        ('GRID',          (0, 0),  (-1, subtotal_row_idx - 1), 0.4, GREY_LIGHT),
        ('VALIGN',        (0, 0),  (-1, -1),               'MIDDLE'),
        ('TOPPADDING',    (0, 1),  (-1, subtotal_row_idx - 1), 5),
        ('BOTTOMPADDING', (0, 1),  (-1, subtotal_row_idx - 1), 5),
        # Subtotal row
        ('SPAN',          (0, subtotal_row_idx), (3, subtotal_row_idx)),
        ('BACKGROUND',    (0, subtotal_row_idx), (-1, subtotal_row_idx), SUBTOTAL_BG),
        ('LINEABOVE',     (0, subtotal_row_idx), (-1, subtotal_row_idx), 1, NAVY_LIGHT),
        ('TOPPADDING',    (0, subtotal_row_idx), (-1, subtotal_row_idx), 6),
        ('BOTTOMPADDING', (0, subtotal_row_idx), (-1, subtotal_row_idx), 6),
        # VAT row
        ('SPAN',          (0, vat_row_idx), (3, vat_row_idx)),
        ('BACKGROUND',    (0, vat_row_idx), (-1, vat_row_idx), SUBTOTAL_BG),
        ('TOPPADDING',    (0, vat_row_idx), (-1, vat_row_idx), 5),
        ('BOTTOMPADDING', (0, vat_row_idx), (-1, vat_row_idx), 5),
        # Grand Total row
        ('SPAN',          (0, grand_total_row_idx), (3, grand_total_row_idx)),
        ('BACKGROUND',    (0, grand_total_row_idx), (-1, grand_total_row_idx), GRAND_BG),
        ('LINEABOVE',     (0, grand_total_row_idx), (-1, grand_total_row_idx), 1.5, ORANGE),
        ('TOPPADDING',    (0, grand_total_row_idx), (-1, grand_total_row_idx), 8),
        ('BOTTOMPADDING', (0, grand_total_row_idx), (-1, grand_total_row_idx), 8),
    ]

    # Grand total text override to white
    grand_p_label = Paragraph('GRAND TOTAL:',
        S('GL', fontSize=9, fontName='Helvetica-Bold',
          textColor=colors.white, alignment=TA_RIGHT))
    grand_p_value = Paragraph(f"{grand_total:,.2f}",
        S('GV', fontSize=9, fontName='Helvetica-Bold',
          textColor=GOLD, alignment=TA_RIGHT))
    table_data[grand_total_row_idx][4] = grand_p_label
    table_data[grand_total_row_idx][5] = grand_p_value

    # Pump row highlight
    if pump_row_index is not None:
        ts.append(('BACKGROUND', (0, pump_row_index), (-1, pump_row_index), PUMP_BLUE))
        ts.append(('LINEABOVE',  (0, pump_row_index), (-1, pump_row_index), 0.6, NAVY_LIGHT))
        ts.append(('LINEBELOW',  (0, pump_row_index), (-1, pump_row_index), 0.6, NAVY_LIGHT))

    pricing_table.setStyle(TableStyle(ts))
    elements.append(pricing_table)
    elements.append(Spacer(1, 5))

    # ── Notes ──
    elements.append(Paragraph(
        "★  VAT (15%) is included in the Grand Total shown above.", note_s))
    if has_pump:
        elements.append(Paragraph(
            "★  Pump cost is charged per m³ of total poured volume.", note_s))
    elements.append(Spacer(1, 2))
    elements.append(Paragraph(
        "—  Volume discounts are available for larger orders. Please inquire.", note_s))
    elements.append(Spacer(1, 8))

    # ── Terms ──
    elements.append(HRFlowable(width="100%", thickness=0.5,
                               color=GREY_LIGHT, spaceAfter=5))
    elements.append(Paragraph("<b>Terms &amp; Conditions</b>", terms_s))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(
        "• <b>Delivery:</b> Within 7–10 working days from order confirmation.<br/>"
        "• <b>Payment:</b> 100% advance payment required before delivery.<br/>"
        "• <b>Validity:</b> This quote is valid for 3 days from the date of issue.<br/>"
        "• <b>Exclusions:</b> Does not include site preparation, road access complications, "
        "or waiting time exceeding 1 hour per truck.",
        terms_s))
    elements.append(Spacer(1, 10))

    # ── Contact + Signature ──
    contact_info = (
        "<b>For clarifications, please contact:</b><br/>"
        "Biruk Endale — <i>Chief Operations Officer</i><br/>"
        "CoBuilt Solutions<br/>"
        "📞 +251 911 246 502  |  +251 911 246 520"
    )
    try:
        sig = Image('signature.png', width=2.2 * inch, height=1.3 * inch)
        right_block = Table(
            [[Paragraph("<b>Approved By:</b>", approved_s)], [sig]],
            colWidths=[2.5 * inch])
        right_block.setStyle(TableStyle([
            ('ALIGN',  (0, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ]))
        sig_table = Table(
            [[Paragraph(contact_info, contact_s), right_block]],
            colWidths=[3.8 * inch, 2.7 * inch])
        sig_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('ALIGN',  (0, 0), (0, 0),  'LEFT'),
            ('ALIGN',  (1, 0), (1, 0),  'RIGHT'),
        ]))
        elements.append(sig_table)
    except Exception:
        elements.append(Paragraph(contact_info, contact_s))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("<b>Approved By:</b> _______________________", approved_s))

    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=0.4,
                               color=GREY_LIGHT, spaceAfter=4))
    elements.append(Paragraph(
        "CoBuilt Solutions  ·  A Branch of SSara Group  ·  www.CoBuilt.com", footer_s))

    pdf.build(elements)
    buffer.seek(0)
    return buffer


# ── Conversation Handlers ──

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏗 *Welcome to CoBuilt Solutions Quote Bot!*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📄 /createpi  — New concrete quote\n"
        "📋 /myquotes — View your quotes\n"
        "❓ /help       — Help & info\n"
        "━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *CoBuilt Quote Bot — Help*\n\n"
        "/createpi — Start a new concrete quote\n"
        "/myquotes — View your last 10 quotes\n"
        "/cancel    — Cancel current operation\n\n"
        "_Quotes are reviewed by admin before the PDF is issued._",
        parse_mode="Markdown")

async def create_pi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['pi_data'] = {
        'user_id':    update.effective_user.id,
        'username':   update.effective_user.username or update.effective_user.first_name,
        'created_at': datetime.now().isoformat()
    }
    context.user_data['selected_grades'] = []

    await update.message.reply_text(
        step_header(1, 6, "👤 *Enter customer / company name:*"),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
    return CUSTOMER

async def customer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel':
        return await cancel(update, context)
    context.user_data['pi_data']['customer'] = update.message.text
    await update.message.reply_text(
        step_header(2, 6, "📍 *Enter delivery location:*"),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([['⬅️ Back', '❌ Cancel']], resize_keyboard=True))
    return LOCATION_INPUT

async def location_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    if update.message.text == '⬅️ Back':  return await create_pi(update, context)
    context.user_data['pi_data']['location'] = update.message.text
    context.user_data['selected_grades'] = []
    await update.message.reply_text(
        step_header(3, 6,
            "🧱 *Select concrete grade(s):*\n\n"
            "Tap grades to toggle ✅/🔲, then press *✅ Done* when finished.\n"
            "_Selected: none yet_"),
        parse_mode="Markdown",
        reply_markup=grade_keyboard([]))
    return GRADES

async def grades_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == '❌ Cancel': return await cancel(update, context)

    if text == '✅ Done':
        selected = context.user_data.get('selected_grades', [])
        if not selected:
            await update.message.reply_text(
                "⚠️ Please select at least one grade before pressing Done.",
                reply_markup=grade_keyboard([]))
            return GRADES
        context.user_data['pi_data']['grades']     = selected
        context.user_data['pi_data']['unit_price'] = {}
        context.user_data['pi_data']['quantity']   = {}
        context.user_data['current_grade_index']   = 0
        first_grade = selected[0]
        await update.message.reply_text(
            step_header(4, 6,
                f"💵 *Grade: {first_grade}*\n\nEnter unit price per m³ (Birr):"),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
        return PRICE

    # Toggle grade selection
    # Strip the emoji prefix added by grade_keyboard
    raw = text.replace('✅ ', '').replace('🔲 ', '').strip()
    selected = context.user_data.get('selected_grades', [])

    if raw in GRADES_LIST:
        if raw in selected:
            selected.remove(raw)
        else:
            selected.append(raw)
        context.user_data['selected_grades'] = selected
        sel_display = ', '.join(selected) if selected else 'none yet'
        await update.message.reply_text(
            step_header(3, 6,
                f"🧱 *Select concrete grade(s):*\n\n"
                f"Tap grades to toggle ✅/🔲, then press *✅ Done* when finished.\n"
                f"_Selected: {sel_display}_"),
            parse_mode="Markdown",
            reply_markup=grade_keyboard(selected))
    else:
        await update.message.reply_text(
            "⚠️ Please use the buttons to select grades.",
            reply_markup=grade_keyboard(selected))

    return GRADES

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    idx   = context.user_data['current_grade_index']
    grade = context.user_data['pi_data']['grades'][idx]
    try:
        context.user_data['pi_data']['unit_price'][grade] = float(
            update.message.text.replace(',', ''))
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g. 13700).")
        return PRICE
    await update.message.reply_text(
        f"📏 *Grade: {grade}*\n\nEnter quantity in m³:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
    return QUANTITY

async def quantity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    idx   = context.user_data['current_grade_index']
    grade = context.user_data['pi_data']['grades'][idx]
    try:
        context.user_data['pi_data']['quantity'][grade] = float(
            update.message.text.replace(',', ''))
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g. 250).")
        return QUANTITY

    context.user_data['current_grade_index'] += 1
    grades = context.user_data['pi_data']['grades']

    if context.user_data['current_grade_index'] < len(grades):
        next_grade = grades[context.user_data['current_grade_index']]
        await update.message.reply_text(
            step_header(4, 6, f"💵 *Grade: {next_grade}*\n\nEnter unit price per m³ (Birr):"),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([['❌ Cancel']], resize_keyboard=True))
        return PRICE

    # All grades done — ask for extras
    await update.message.reply_text(
        step_header(5, 6, "🧰 *Select additional service:*"),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [EXTRAS_LIST[:2], EXTRAS_LIST[2:], ['❌ Cancel']],
            resize_keyboard=True))
    return EXTRAS

async def extras_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel': return await cancel(update, context)
    if update.message.text not in EXTRAS_LIST:
        await update.message.reply_text(
            "⚠️ Please choose an option from the keyboard.",
            reply_markup=ReplyKeyboardMarkup(
                [EXTRAS_LIST[:2], EXTRAS_LIST[2:], ['❌ Cancel']],
                resize_keyboard=True))
        return EXTRAS

    context.user_data['pi_data']['extras'] = update.message.text

    # If elephant pump selected, ask for pump cost per m³
    if update.message.text == 'Elephant pump':
        await update.message.reply_text(
            step_header(5, 6,
                "🐘 *Elephant Pump — Pump Cost*\n\n"
                "Enter the pump cost per m³ (Birr):\n"
                "_Type 0 or 'skip' to skip pump cost._"),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([['Skip', '❌ Cancel']], resize_keyboard=True))
        return PUMP_COST

    # No pump cost
    context.user_data['pi_data']['pump_cost_per_m3'] = 0
    return await show_summary(update, context)

async def pump_cost_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '❌ Cancel': return await cancel(update, context)

    if update.message.text.lower() in ('skip', '0'):
        context.user_data['pi_data']['pump_cost_per_m3'] = 0
    else:
        try:
            cost = float(update.message.text.replace(',', ''))
            context.user_data['pi_data']['pump_cost_per_m3'] = cost
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a valid number or type *Skip*.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup([['Skip', '❌ Cancel']], resize_keyboard=True))
            return PUMP_COST

    return await show_summary(update, context)

async def show_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pi = context.user_data['pi_data']
    total_quantity = sum(pi['quantity'][g] for g in pi['grades'])

    concrete_total = sum(pi['unit_price'][g] * pi['quantity'][g] for g in pi['grades'])
    pump_cost_per  = pi.get('pump_cost_per_m3', 0)
    pump_total     = pump_cost_per * total_quantity
    subtotal       = concrete_total + pump_total
    vat            = subtotal * 0.15
    total          = subtotal + vat

    grades_lines = "\n".join(
        f"  › {g}: {pi['unit_price'][g]:,.0f} × {pi['quantity'][g]:,.0f}m³"
        f" = {pi['unit_price'][g]*pi['quantity'][g]:,.0f} Birr"
        for g in pi['grades'])

    pump_line = (
        f"\n🐘 *Pump:*  {pump_cost_per:,.0f} × {total_quantity:,.0f}m³"
        f" = {pump_total:,.0f} Birr"
        if pump_cost_per > 0 else ""
    )

    summary = (
        f"┌─── 📋 Quote Summary ───┐\n\n"
        f"🏢 *Customer:*   {pi['customer']}\n"
        f"📍 *Location:*   {pi['location']}\n"
        f"🧰 *Extras:*     {pi['extras']}\n\n"
        f"🧱 *Concrete:*\n{grades_lines}{pump_line}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Subtotal:      {subtotal:,.2f} Birr\n"
        f"VAT (15%):     {vat:,.2f} Birr\n"
        f"*Grand Total:  {total:,.2f} Birr*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Submit this quote?"
    )
    await update.message.reply_text(
        summary, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Submit Quote", callback_data='confirm_yes')],
            [InlineKeyboardButton("❌ Cancel",        callback_data='confirm_no')]]))
    return CONFIRM

async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'confirm_yes':
        global bot_data
        bot_data['quote_counter'] += 1
        q_num = f"RMX-{bot_data['quote_counter']:04d}"
        pi    = context.user_data['pi_data']
        pi['quote_number'] = q_num
        pi['status']       = 'pending'
        bot_data['quotes'][q_num] = pi
        save_data(bot_data)

        total_quantity = sum(pi['quantity'][g] for g in pi['grades'])
        concrete_total = sum(pi['unit_price'][g] * pi['quantity'][g] for g in pi['grades'])
        pump_total     = pi.get('pump_cost_per_m3', 0) * total_quantity
        subtotal       = concrete_total + pump_total
        vat            = subtotal * 0.15
        total          = subtotal + vat

        await query.edit_message_text(
            f"✅ *Quote Submitted Successfully!*\n\n"
            f"📄 Quote No: `{q_num}`\n"
            f"🏢 Customer: {pi['customer']}\n"
            f"💰 Subtotal: {subtotal:,.2f} Birr\n"
            f"🧾 VAT (15%): {vat:,.2f} Birr\n"
            f"💵 *Grand Total: {total:,.2f} Birr*\n\n"
            f"⏳ _Awaiting admin approval. You'll receive the PDF once approved._",
            parse_mode="Markdown")

        grades_summary = "\n".join(
            f"• {g}: {pi['unit_price'][g]:,.0f} × {pi['quantity'][g]:,.0f}m³"
            for g in pi['grades'])
        pump_line = (f"\n🐘 Pump: {pi.get('pump_cost_per_m3',0):,.0f}/m³ "
                     f"× {total_quantity:,.0f}m³ = {pump_total:,.0f} Birr"
                     if pi.get('pump_cost_per_m3', 0) > 0 else "")

        admin_msg = (
            f"🔔 *New Quote Request: {q_num}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏢 Customer: {pi['customer']}\n"
            f"📍 Location: {pi['location']}\n"
            f"🧱 Grades:\n{grades_summary}{pump_line}\n"
            f"🧰 Extras: {pi['extras']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Subtotal:  {subtotal:,.2f} Birr\n"
            f"VAT:       {vat:,.2f} Birr\n"
            f"*Total:    {total:,.2f} Birr*"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id, admin_msg, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{q_num}"),
                        InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{q_num}")]]))
            except Exception as e:
                log.warning(f"Failed to notify admin {admin_id}: {e}")
    else:
        await query.edit_message_text("❌ Quote cancelled. Use /createpi to start again.")

    return ConversationHandler.END

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in ADMIN_IDS:
        await query.answer("⛔ Not authorized.", show_alert=True)
        return

    action, q_num = query.data.split('_', 1)
    pi = bot_data['quotes'].get(q_num)
    if not pi:
        await query.edit_message_text("❌ Quote not found.")
        return

    if action == 'approve':
        pi['status']      = 'approved'
        pi['approved_by'] = update.effective_user.username or update.effective_user.first_name
        pi['approved_at'] = datetime.now().isoformat()
        save_data(bot_data)
        await query.edit_message_text(
            f"{query.message.text}\n\n✅ APPROVED by @{pi['approved_by']}")
        pdf = generate_pdf(pi)
        safe_name = "".join(c for c in pi['customer'].title() if c.isalnum())[:30]
        try:
            await context.bot.send_document(
                chat_id=pi['user_id'],
                document=pdf,
                filename=f"{safe_name}_Quote_{q_num}.pdf",
                caption=(
                    f"✅ *Quote Approved!*\n"
                    f"Quote No: `{q_num}`\n\n"
                    f"Thank you for choosing CoBuilt Solutions.\n"
                    f"Use /createpi to create another quote."),
                parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Failed to send PDF to user: {e}")

    elif action == 'reject':
        pi['status']      = 'rejected'
        pi['rejected_by'] = update.effective_user.username or update.effective_user.first_name
        pi['rejected_at'] = datetime.now().isoformat()
        save_data(bot_data)
        await query.edit_message_text(
            f"{query.message.text}\n\n❌ REJECTED by @{pi['rejected_by']}")
        try:
            await context.bot.send_message(
                chat_id=pi['user_id'],
                text=(
                    f"❌ Your quote *{q_num}* has been rejected.\n\n"
                    f"Please contact us for more information or use /createpi to submit a new quote."),
                parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Failed to notify user of rejection: {e}")

async def myquotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_quotes = [q for q in bot_data['quotes'].values() if q['user_id'] == uid]
    if not user_quotes:
        await update.message.reply_text(
            "📭 You have no quotes yet.\n\nUse /createpi to create your first quote.")
        return
    await update.message.reply_text(
        f"📋 *Your Quotes* ({min(len(user_quotes),10)} shown):",
        parse_mode="Markdown")
    for pi in sorted(user_quotes, key=lambda x: x['quote_number'], reverse=True)[:10]:
        total_qty      = sum(pi['quantity'][g] for g in pi['grades'])
        concrete_total = sum(pi['unit_price'][g] * pi['quantity'][g] for g in pi['grades'])
        pump_total     = pi.get('pump_cost_per_m3', 0) * total_qty
        subtotal       = concrete_total + pump_total
        total          = subtotal * 1.15
        status_icon    = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(pi['status'], "❓")
        await update.message.reply_text(
            f"{status_icon} *{pi['quote_number']}*\n"
            f"🏢 {pi['customer']}  |  📍 {pi['location']}\n"
            f"🧱 {', '.join(pi['grades'])}\n"
            f"💵 Grand Total: *{total:,.2f} Birr*\n"
            f"Status: _{pi['status'].title()}_",
            parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operation cancelled.\n\nUse /createpi to start a new quote.",
        reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Main ──
def kill_existing_connections():
    import requests, time
    for attempt in range(5):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True}, timeout=10)
            if r.json().get("ok"):
                log.warning("Webhook cleared.")
                break
        except Exception as e:
            log.warning(f"deleteWebhook attempt {attempt+1} failed: {e}")
        time.sleep(2)
    time.sleep(3)

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")

    kill_existing_connections()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler('createpi', create_pi)],
        states={
            CUSTOMER:       [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_name)],
            LOCATION_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, location_input)],
            GRADES:         [MessageHandler(filters.TEXT & ~filters.COMMAND, grades_handler)],
            PRICE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, price_handler)],
            QUANTITY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_handler)],
            EXTRAS:         [MessageHandler(filters.TEXT & ~filters.COMMAND, extras_handler)],
            PUMP_COST:      [MessageHandler(filters.TEXT & ~filters.COMMAND, pump_cost_handler)],
            CONFIRM:        [CallbackQueryHandler(confirm_handler, pattern='^confirm_')],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler('start',    start))
    app.add_handler(CommandHandler('help',     help_command))
    app.add_handler(CommandHandler('myquotes', myquotes))
    app.add_handler(CallbackQueryHandler(handle_approval, pattern='^(approve|reject)_'))

    log.warning("CoBuilt Quote Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
