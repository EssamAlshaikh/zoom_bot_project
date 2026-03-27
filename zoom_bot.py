# zoom_bot.py
import time, subprocess, sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from bot_config import TELEGRAM_TOKEN, CHAT_ID, MAX_RETRIES, CHUNK_DURATION
from telegram import Bot
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

bot = Bot("8689618689:AAH6gYeeZkf-JbeEcE9gHIcL73-YR74fLvo")
scheduler = BackgroundScheduler()
scheduler.start()

# ---------- قاعدة البيانات ----------
conn = sqlite3.connect("lectures.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS lectures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    time TEXT,
    duration INTEGER,
    name TEXT,
    status TEXT,
    retries INTEGER DEFAULT 0
)
""")
conn.commit()

# ---------- Google Drive ----------
def upload_drive(filename):
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)
    file = drive.CreateFile({'title': filename})
    file.SetContentFile(filename)
    file.Upload()
    return file['id']

# ---------- تسجيل chunk مع retry ----------
def record_chunk_with_retry(filename, duration, retries=MAX_RETRIES):
    attempt = 0
    while attempt < retries:
        try:
            cmd = [
                "ffmpeg","-y",
                "-video_size","1280x720",
                "-framerate","25",
                "-f","x11grab","-i",":0",  # استخدم display الصحيح
                "-f","pulse","-i","default",
                "-t", str(duration),
                filename
            ]
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError:
            attempt += 1
            time.sleep(5)
    return False

# ---------- تسجيل المحاضرة بالكامل ----------
def record_chunks(filename_base, total_duration):
    files = []
    for i in range(total_duration // CHUNK_DURATION + 1):
        fname = f"{filename_base}_{i}.mp4"
        success = record_chunk_with_retry(fname, CHUNK_DURATION)
        if not success:
            bot.send_message(CHAT_ID, f"❌ فشل تسجيل chunk {i}, استكمال باقي المحاضرة...")
        files.append(fname)
    return files

# ---------- دمج الملفات ----------
def merge_chunks(files, output_file):
    with open("list.txt", "w") as f:
        for file in files:
            f.write(f"file '{file}'\n")
    subprocess.run([
        "ffmpeg","-f","concat","-safe","0",
        "-i","list.txt","-c","copy",output_file
    ], check=True)

# ---------- إعادة المحاولة ----------
def retry_job(job):
    if job["retries"] < MAX_RETRIES:
        job["retries"] += 1
        bot.send_message(CHAT_ID, f"🔁 إعادة المحاولة {job['retries']}...")
        run_job(job)
    else:
        bot.send_message(CHAT_ID, "❌ فشل نهائي")

# ---------- تشغيل الوظيفة ----------
def run_job(job):
    try:
        filename = f"zoom_{job['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        bot.send_message(CHAT_ID, f"🚀 بدء المحاضرة: {job['name']}")
        
        # هنا مكان فتح Zoom، يمكن استخدام subprocess مع url إذا كان متاح
        time.sleep(5)  # Simulate open Zoom
        
        bot.send_message(CHAT_ID, "🎥 بدء التسجيل...")
        cursor.execute("UPDATE lectures SET status=? WHERE id=?", ("running", job["id"]))
        conn.commit()
        
        files = record_chunks(filename, job["duration"])
        final_file = f"{filename}_final.mp4"
        merge_chunks(files, final_file)
        
        bot.send_message(CHAT_ID, "☁️ رفع إلى Google Drive...")
        file_id = upload_drive(final_file)
        
        cursor.execute("UPDATE lectures SET status=? WHERE id=?", ("done", job["id"]))
        conn.commit()
        bot.send_message(CHAT_ID, f"✅ تم! 📎 ID: {file_id}")
    except Exception as e:
        bot.send_message(CHAT_ID, f"❌ خطأ: {e}")
        retry_job(job)

# ---------- جدولة تنبيه قبل المحاضرة ----------
def schedule_lecture(url, time_str, duration, name):
    run_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    job = {"id": None, "url": url, "duration": duration, "name": name, "retries": 0, "chat_id": CHAT_ID}
    
    # حفظ في DB
    cursor.execute("INSERT INTO lectures (url, time, duration, name, status) VALUES (?,?,?,?,'pending')", 
                   (url, time_str, duration, name))
    job["id"] = cursor.lastrowid
    conn.commit()
    
    # تنبيه 5 دقائق قبل
    scheduler.add_job(
        lambda: bot.send_message(CHAT_ID, f"⏰ بعد 5 دقائق تبدأ المحاضرة: {name}"),
        'date',
        run_date=run_time - timedelta(minutes=5)
    )
    
    # جدولة تسجيل
    scheduler.add_job(
        lambda: run_job(job),
        'date',
        run_date=run_time
    )
    bot.send_message(CHAT_ID, f"🗓 تم جدولة المحاضرة: {name} في {time_str}")

# ---------- أمر تجريبي ----------
schedule_lecture("https://zoom.us/j/1234567890", "2026-03-26 15:00", 15, "اختبار Zoom")

# ---------- تشغيل البوت ----------
bot.send_message(CHAT_ID, "🤖 بوت Zoom جاهز!")
scheduler.start()
while True:
    time.sleep(10)