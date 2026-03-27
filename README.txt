تعليمات التشغيل:

1. رفع المجلد كامل إلى Oracle VM.
2. تثبيت المتطلبات:
   sudo apt update
   sudo apt install -y python3 python3-pip ffmpeg xvfb tmux
   pip3 install -r requirements.txt
3. تشغيل Xvfb:
   Xvfb :0 -screen 0 1280x720x24 &
4. تشغيل البوت:
   tmux new -s zoom_bot
   python3 zoom_bot.py
   # للخروج من الجلسة مع استمرار التشغيل: Ctrl+B ثم D
   # للرجوع للجلسة لاحقًا: tmux attach -t zoom_bot