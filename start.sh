#!/bin/bash

echo "Starting PulseAudio..."
pulseaudio --start

echo "Creating virtual audio sink..."
pactl load-module module-null-sink sink_name=virtual_sink

echo "Starting virtual display..."
Xvfb :99 -screen 0 1280x720x24 &
export DISPLAY=:99

echo "Loading environment variables..."
export $(grep -v '^#' .env | xargs)

echo "Starting bot..."
python3 bot.py
