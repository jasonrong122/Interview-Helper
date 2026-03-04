import asyncio
import websockets
import sounddevice as sd
import mss
import cv2
import numpy as np
import base64
import json

RATE_IN = 16000
RATE_OUT = 24000
CHANNELS = 1
CHUNK = 512

async def send_audio(ws):
    """Continuously record mic audio and send to the backend."""
    loop = asyncio.get_running_loop()
    audio_queue = asyncio.Queue()

    def audio_callback(indata, frames, time, status):
        # Put the raw bytes into the asyncio queue safely
        loop.call_soon_threadsafe(audio_queue.put_nowait, bytes(indata))

    # Open the raw input stream
    with sd.RawInputStream(samplerate=RATE_IN, channels=CHANNELS, dtype='int16', blocksize=CHUNK, callback=audio_callback):
        while True:
            data = await audio_queue.get()
            payload = {
                "mime_type": "audio/pcm;rate=16000",
                "data": base64.b64encode(data).decode('utf-8')
            }
            await ws.send(json.dumps(payload))

async def send_screen(ws):
    """Continuously capture screen, resize, and send to the backend."""
    sct = mss.mss()
    monitor = sct.monitors[1] # Change to 2 if you have a second monitor
    
    while True:
        sct_img = sct.grab(monitor)
        img = np.array(sct_img)
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        img = cv2.resize(img, (1280, 720))
        
        _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        payload = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(buffer).decode('utf-8')
        }
        await ws.send(json.dumps(payload))
        await asyncio.sleep(1)

async def receive_audio(ws):
    """Listen for Gemini's spoken responses and play them through the speakers."""
    stream = sd.RawOutputStream(samplerate=RATE_OUT, channels=CHANNELS, dtype='int16')
    with stream:
        async for message in ws:
            # message is the raw audio bytes sent from the backend
            stream.write(message)

async def main():
    url = "ws://localhost:8000/ws/system-design"
    async with websockets.connect(url) as ws:
        print("Connected to Cloud Run backend! Start drawing and talking.")
        
        await asyncio.gather(
            send_audio(ws),
            send_screen(ws),
            receive_audio(ws)
        )

if __name__ == "__main__":
    asyncio.run(main())