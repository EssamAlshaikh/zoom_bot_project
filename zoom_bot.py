import asyncio
import os
import subprocess
import json
import uuid
import logging
import nest_asyncio
import time
from datetime import datetime
from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# Google Drive imports (التوثيق التلقائي)
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# --- الإعدادات العامة ---
nest_asyncio.apply()
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8689618689:AAGm9xWGAz0ra_kgLL0goVuUvy0S5JhoQn4"
SCHEDULE_FILE = 'schedules.json'
GOOGLE_DRIVE_FOLDER_ID = '15-W5XpLc1MS4Hwi_ieW1K8Wz4tGc_hJV'
TOKEN_FILE = 'token.json'

scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Riyadh"))
active_recordings = {}
application = None

# حالات المحادثة
GET_ZOOM_LINK, GET_USER_NAME, GET_RECORDING_TYPE, GET_RECURRENCE, GET_RECURRENCE_DAYS, GET_LECTURE_TIME = range(6)

DAY_NAMES_MAP = {
    'day_0': 'الأحد', 'day_1': 'الاثنين', 'day_2': 'الثلاثاء',
    'day_3': 'الأربعاء', 'day_4': 'الخميس', 'day_5': 'الجمعة', 'day_6': 'السبت'
}

APS_DAY_TO_INT_MAP = {
    'day_0': 6, 'day_1': 0, 'day_2': 1, 'day_3': 2, 'day_4': 3, 'day_5': 4, 'day_6': 5
}

# --- وظائف المساعدة والنظام ---

def load_schedules():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

def save_schedules(schedules):
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedules, f, indent=4, ensure_ascii=False)

def cleanup_old_files():
    extensions = ('.mp4', '.mp3', '.png', '.webm')
    for file in os.listdir(os.getcwd()):
        if file.endswith(extensions):
            try: os.remove(file)
            except: pass

def setup_virtual_display():
    print("🖥️ Terminal: Setting up virtual display and audio...")
    try: subprocess.run(['pgrep', '-x', 'Xvfb'], check=True)
    except: subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x720x24"])
    os.environ["DISPLAY"] = ":99"
    try: subprocess.run(['pgrep', '-x', 'pulseaudio'], check=True)
    except:
        subprocess.Popen(["pulseaudio", "--start", "--exit-idle-time=-1"])
        time.sleep(2)
    subprocess.run(["pactl", "load-module", "module-null-sink", "sink_name=rtp"], stderr=subprocess.DEVNULL)
    subprocess.run(["pactl", "set-default-sink", "rtp"], stderr=subprocess.DEVNULL)

_gdrive_service = None
def authenticate_google_drive_once():
    global _gdrive_service
    if _gdrive_service is None:
        print("🔑 Terminal: Authenticating Google Drive via token.json...")
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    print("🔄 Terminal: Token expired, refreshing...")
                    creds.refresh(Request())
            _gdrive_service = build('drive', 'v3', credentials=creds)
            print("✅ Terminal: Google Drive Authenticated.")
        except Exception as e:
            print(f"❌ Terminal: Authentication error: {e}")
    return _gdrive_service

async def upload_file_to_drive(drive_service, file_path, folder_id):
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0: return False
        print(f"📤 Terminal: Uploading {file_path} to Drive...")
        file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
        media = MediaFileUpload(file_path, resumable=True, mimetype='video/mp4' if file_path.endswith('.mp4') else 'audio/mpeg')
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"✅ Terminal: Upload complete for {file_path}")
        os.remove(file_path)
        return True
    except Exception as e:
        print(f"❌ Terminal: Upload error: {e}")
        return False

# --- المحرك الرئيسي للتسجيل ---

async def record_zoom_lecture(zoom_url, user_name, rec_type, job_id, chat_id):
    print(f"\n🎬 Terminal: Starting job {job_id} for user {user_name}")

    web_url = zoom_url.replace('/j/', '/wc/join/') + "&prefer=1"
    timestamp = datetime.now(pytz.timezone('Asia/Riyadh')).strftime('%Y%m%d_%H%M')
    ext = "mp4" if rec_type == "record_video" else "mp3"
    filename = f"lecture_{timestamp}.{ext}"

    browser = None
    try:
        async with async_playwright() as p:
            print("🌐 Terminal: Launching browser...")
            browser = await p.chromium.launch(headless=False, args=[
                '--no-sandbox', '--disable-dev-shm-usage',
                '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
                '--autoplay-policy=no-user-gesture-required'
            ])
            context = await browser.new_context(viewport={'width': 1280, 'height': 720}, permissions=[])
            page = await context.new_page()

            print(f"🔗 Terminal: Navigating to Zoom Link...")
            await page.goto(web_url)

            # محاولة الانضمام من المتصفح
            try:
                await page.wait_for_selector('text=Join from Your Browser', timeout=15000)
                await page.click('text=Join from Your Browser')
                print("🔘 Terminal: Clicked 'Join from Browser'")
            except: pass

            await asyncio.sleep(2)
            try:
                await page.fill('input[id="inputname"], input[type="text"]', user_name)
                await page.click('button:has-text("Join"), button[id="joinBtn"]')
                print(f"📝 Terminal: Logged in as '{user_name}'")
            except: pass

            await asyncio.sleep(15)

            # بدء FFmpeg
            ffmpeg_cmd = [
                'ffmpeg', '-y', '-f', 'x11grab', '-framerate', '30', '-video_size', '1280x720', '-i', ':99.0',
                '-f', 'pulse', '-i', 'rtp.monitor', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', filename
            ] if rec_type == "record_video" else [
                'ffmpeg', '-y', '-f', 'pulse', '-i', 'rtp.monitor',
                '-c:a', 'libmp3lame', '-b:a', '192k', filename
            ]

            ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"🔴 Terminal: Recording started -> {filename}")

            active_recordings[job_id] = {'proc': ffmpeg_proc, 'browser': browser, 'filename': filename}
            await application.bot.send_message(chat_id=chat_id, text=f"🔴 بدأ التسجيل: {filename}")

            # --- حلقة المراقبة المحسنة (لمنع الأخطاء) ---
            max_duration = 130 * 60
            start_time = time.time()

            while True:
                await asyncio.sleep(15)
                
                # التحقق من أن الصفحة لا تزال مفتوحة قبل أي عملية
                if page.is_closed():
                    print("⚠️ Terminal: Page closed.")
                    break
                    
                elapsed = time.time() - start_time
                if job_id not in active_recordings:
                    print("⏹️ Terminal: Manual stop detected.")
                    break

                try:
                    # فحص حالة القاعة بصيغة آمنة
                    if await page.is_visible('text=ended', timeout=500) or \
                       await page.is_visible('text=removed', timeout=500):
                        print("⚠️ Terminal: Meeting ended or kicked.")
                        break
                except: break

                if elapsed > max_duration:
                    print("⏰ Terminal: Max duration reached.")
                    break

            # --- الإغلاق والرفع ---
            print("🏁 Terminal: Stopping recording and uploading...")
            ffmpeg_proc.terminate()
            ffmpeg_proc.wait(timeout=5)

            try:
                if not page.is_closed():
                    await page.click('button:has-text("Leave")', timeout=3000)
                    await page.click('button:has-text("Leave Meeting")', timeout=3000)
            except: pass

            await browser.close()
            browser = None
            
            ds = authenticate_google_drive_once()
            if ds and await upload_file_to_drive(ds, filename, GOOGLE_DRIVE_FOLDER_ID):
                await application.bot.send_message(chat_id=chat_id, text=f"✅ اكتمل الرفع: {filename}")
                cleanup_old_files()

    except Exception as e:
        print(f"❌ Terminal: Error in recording: {e}")
    finally:
        if job_id in active_recordings: del active_recordings[job_id]
        if browser: await browser.close()

# --- واجهة التلغرام ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[KeyboardButton("جدولة تسجيل جديد")], [KeyboardButton("إدارة التسجيلات المجدولة")]]
    await update.message.reply_text("مرحباً بك. النظام جاهز للدخول المباشر لزووم.", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ConversationHandler.END

async def manage_schedules(update, context):
    schedules = load_schedules(); chat_id = update.effective_chat.id
    user_schedules = [s for s in schedules if s.get('chat_id') == chat_id]
    if not user_schedules:
        await update.message.reply_text("لا توجد مهام."); return
    keyboard = [[InlineKeyboardButton(f"🗑️ حذف {s['user_name']}", callback_data=f"del_{s['job_ids'][0]}")] for s in user_schedules]
    await update.message.reply_text("إدارة المهام:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback_global(update, context):
    query = update.callback_query; await query.answer()
    if query.data.startswith("del_"):
        jid = query.data.split("_")[1]
        new_scheds = [s for s in load_schedules() if jid not in s.get('job_ids', [])]
        save_schedules(new_scheds)
        try: scheduler.remove_job(jid)
        except: pass
        await query.edit_message_text("✅ تم الحذف.")

# --- خطوات إنشاء المهمة ---
async def new_sched(update, context):
    await update.message.reply_text("أرسل رابط زووم:"); return GET_ZOOM_LINK
async def get_link(update, context):
    context.user_data['link'] = update.message.text
    await update.message.reply_text("الاسم المطلوب داخل زووم:"); return GET_USER_NAME
async def get_name(update, context):
    context.user_data['name'] = update.message.text
    kb = [[InlineKeyboardButton("فيديو", callback_data='record_video'), InlineKeyboardButton("صوت", callback_data='record_audio')]]
    await update.message.reply_text("نوع التسجيل:", reply_markup=InlineKeyboardMarkup(kb)); return GET_RECORDING_TYPE
async def get_type(update, context):
    context.user_data['type'] = update.callback_query.data
    kb = [[InlineKeyboardButton("متكرر", callback_data='yes'), InlineKeyboardButton("مرة واحدة", callback_data='no')]]
    await update.callback_query.edit_message_text("التكرار؟", reply_markup=InlineKeyboardMarkup(kb)); return GET_RECURRENCE
async def get_rec(update, context):
    if update.callback_query.data == 'yes':
        context.user_data['is_rec'] = True; context.user_data['days'] = []
        await send_days_picker(update.callback_query, context); return GET_RECURRENCE_DAYS
    context.user_data['is_rec'] = False; await update.callback_query.edit_message_text("التاريخ والوقت (2026-04-12 14:30):"); return GET_LECTURE_TIME
async def send_days_picker(query, context):
    days = context.user_data['days']
    kb = [[InlineKeyboardButton(f"{'✅' if k in days else ''} {v}", callback_data=f"toggle_{k}")] for k, v in DAY_NAMES_MAP.items()]
    kb.append([InlineKeyboardButton("تأكيد الأيام ✅", callback_data="done_days")])
    await query.edit_message_text("اختر الأيام:", reply_markup=InlineKeyboardMarkup(kb))
async def get_days(update, context):
    query = update.callback_query; await query.answer()
    if query.data == "done_days": await query.edit_message_text("الوقت (08:00):"); return GET_LECTURE_TIME
    day = query.data.replace("toggle_", "")
    if day in context.user_data['days']: context.user_data['days'].remove(day)
    else: context.user_data['days'].append(day)
    await send_days_picker(query, context); return GET_RECURRENCE_DAYS

async def save_sched(update, context):
    time_str = update.message.text; chat_id = update.effective_chat.id; schedules = load_schedules(); job_ids = []
    try:
        if context.user_data.get('is_rec'):
            h, m = map(int, time_str.split(':'))
            for d in context.user_data['days']:
                jid = str(uuid.uuid4()); job_ids.append(jid)
                scheduler.add_job(record_zoom_lecture, 'cron', hour=h, minute=m, day_of_week=APS_DAY_TO_INT_MAP[d], args=[context.user_data['link'], context.user_data['name'], context.user_data['type'], jid, chat_id], id=jid)
        else:
            jid = str(uuid.uuid4()); job_ids.append(jid)
            dt = pytz.timezone("Asia/Riyadh").localize(datetime.strptime(time_str, '%Y-%m-%d %H:%M'))
            scheduler.add_job(record_zoom_lecture, 'date', run_date=dt, args=[context.user_data['link'], context.user_data['name'], context.user_data['type'], jid, chat_id], id=jid)
        schedules.append({"chat_id": chat_id, "user_name": context.user_data['name'], "job_ids": job_ids})
        save_schedules(schedules)
        await update.message.reply_text("✅ تمت الجدولة بنجاح!")
    except Exception as e: await update.message.reply_text(f"❌ خطأ: {e}")
    return ConversationHandler.END

# --- التشغيل ---

def main():
    global application
    setup_virtual_display()
    if os.path.exists(TOKEN_FILE): authenticate_google_drive_once()
    cleanup_old_files()
    if not scheduler.running: scheduler.start()
    
    application = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^جدولة تسجيل جديد$'), new_sched), CommandHandler('start', start)],
        states={
            GET_ZOOM_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_link)],
            GET_USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_RECORDING_TYPE: [CallbackQueryHandler(get_type)],
            GET_RECURRENCE: [CallbackQueryHandler(get_rec)],
            GET_RECURRENCE_DAYS: [CallbackQueryHandler(get_days)],
            GET_LECTURE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_sched)],
        }, fallbacks=[CommandHandler('start', start)], per_message=False
    )
    
    application.add_handler(conv)
    application.add_handler(MessageHandler(filters.Regex('^إدارة التسجيلات المجدولة$'), manage_schedules))
    application.add_handler(CallbackQueryHandler(handle_callback_global))
    
    print("🚀 Terminal: Bot is polling...")
    application.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
