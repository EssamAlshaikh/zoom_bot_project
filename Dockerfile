FROM python:3.10-slim

# تثبيت الأدوات
RUN apt-get update && apt-get install -y \
    ffmpeg \
    pulseaudio \
    chromium \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# إعداد PulseAudio
RUN useradd -m appuser
USER appuser
WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

# تشغيل الصوت الوهمي + التطبيق
CMD pulseaudio --start && \
    pactl load-module module-null-sink sink_name=virtual_sink && \
    Xvfb :99 -screen 0 1280x720x24 & \
    export DISPLAY=:99 && \
    python bot.py