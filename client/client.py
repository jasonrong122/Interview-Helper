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

async def send_audio(ws, stop_event):
    """Continuously record mic audio and send to the backend."""
    loop = asyncio.get_running_loop()
    audio_queue = asyncio.Queue()

    def audio_callback(indata, frames, time, status):
        # Put the raw bytes into the asyncio queue safely
        loop.call_soon_threadsafe(audio_queue.put_nowait, bytes(indata))

    # Open the raw input stream
    with sd.RawInputStream(samplerate=RATE_IN, channels=CHANNELS, dtype='int16', blocksize=CHUNK, callback=audio_callback):
        while not stop_event.is_set():
            try:
                data = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                payload = {
                    "mime_type": "audio/pcm;rate=16000",
                    "data": base64.b64encode(data).decode('utf-8')
                }
                await ws.send(json.dumps(payload))
            except websockets.exceptions.ConnectionClosed:
                break

async def send_screen(ws, stop_event):
    """Continuously capture screen, resize, and send to the backend."""
    sct = mss.mss()
    monitor = sct.monitors[2] # Verify this is the correct monitor index!
    
    while not stop_event.is_set():
        try:
            sct_img = sct.grab(monitor)
            img = np.array(sct_img)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            # Use 1080p for better clarity on diagrams
            img = cv2.resize(img, (1920, 1080)) 
            
            _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
            payload = {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(buffer).decode('utf-8')
            }
            await ws.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed:
            break
        except Exception as e:
            print(f"Screen capture error: {e}")
            
        # Optional: Slightly increase frame rate if your connection handles it well
        await asyncio.sleep(0.5)

async def receive_audio(ws, stop_event):
    """Listen for Gemini's spoken responses and play them through the speakers."""
    stream = sd.RawOutputStream(samplerate=RATE_OUT, channels=CHANNELS, dtype='int16')
    with stream:
        try:
            async for message in ws:
                if stop_event.is_set():
                    break
                if isinstance(message, bytes):
                    stream.write(message)
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"Audio playback error: {e}")

async def main():
    url = "ws://localhost:8000/ws/system-design"
    print("Connecting to backend...")
    
    try:
        async with websockets.connect(url) as ws:
            print("Connected to backend! Start drawing and talking.")
            print("Press Ctrl+C to stop.\n")
            
            stop_event = asyncio.Event()
            
            tasks = [
                asyncio.create_task(send_audio(ws, stop_event)),
                asyncio.create_task(send_screen(ws, stop_event)),
                asyncio.create_task(receive_audio(ws, stop_event)),
            ]
            
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                stop_event.set()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                
    except ConnectionRefusedError:
        print("Could not connect to the backend. Make sure it is running:")
        print("  cd backend && uvicorn main:app --reload")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")