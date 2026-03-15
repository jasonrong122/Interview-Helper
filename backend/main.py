import asyncio
import os
import json
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

@app.websocket("/ws/system-design")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Local client connected!")

    # Configure the persona and response speed
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        # generation_config handles the VAD (Voice Activity Detection) speed
        generation_config={
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": "Aoede"}},
            },
            # This makes the agent respond faster after you stop talking
            "candidate_count": 1,
        },
        system_instruction=types.Content(
            parts=[types.Part.from_text(
                text="""You are a Senior Software Engineer at a top tech company conducting a technical data structures and algorithms interview. 
                The user is writing code on screen and explaining their thought process out loud. Watch their code closely.
                If they start writing a brute-force O(n^2) solution when a more optimal O(n) approach (like a sliding window, two-pointer, or hash map) exists, 
                gently interrupt them and ask if they can optimize the time complexity. Remind them to consider edge cases 
                (like empty arrays or null pointers). If they stay silent for too long, prompt them to explain what they are thinking. 
                Finally, ask them to verbally dry-run their code with a simple example before they run it."""
            )]
        )
    )

    try:
        # Connect to Gemini Live API
        async with client.aio.live.connect(model="gemini-2.5-flash-native-audio-preview-12-2025", config=config) as session:
            print("Successfully connected to Gemini Live API!")
            
            # --- NEW LINE: Trigger the agent to speak first ---
            await session.send(input="Hi, I just joined the call. Please introduce yourself and give me the first problem.")

            # Event to signal all tasks to stop
            stop_event = asyncio.Event()

            async def receive_from_client():
                """Receive audio/screen data from client and forward to Gemini."""
                try:
                    while not stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(
                                websocket.receive_text(), timeout=0.1
                            )
                        except asyncio.TimeoutError:
                            continue

                        data = json.loads(message)
                        raw_bytes = base64.b64decode(data["data"])

                        if data["mime_type"].startswith("audio/"):
                            # Use realtime input for audio (low-latency streaming)
                            await session.send_realtime_input(
                                audio={"data": raw_bytes, "mime_type": data["mime_type"]}
                            )
                        else:
                            # Use realtime input for images too (lower latency than session.send)
                            await session.send_realtime_input(
                                video={"data": raw_bytes, "mime_type": data["mime_type"]}
                            )

                except WebSocketDisconnect:
                    print("Local client disconnected.")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Error receiving from client: {e}")
                finally:
                    stop_event.set()

            async def receive_from_gemini():
                """Receive responses from Gemini and forward audio to client."""
                try:
                    while not stop_event.is_set():
                        try:
                            turn = session.receive()
                            async for response in turn:
                                if stop_event.is_set():
                                    break
                                server_content = response.server_content
                                if server_content is not None and server_content.model_turn is not None:
                                    for part in server_content.model_turn.parts:
                                        if part.inline_data:
                                            try:
                                                await websocket.send_bytes(part.inline_data.data)
                                            except Exception:
                                                stop_event.set()
                                                return
                        except Exception as e:
                            if stop_event.is_set():
                                break
                            print(f"Error in Gemini receive loop: {e}")
                            break
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Error receiving from Gemini: {e}")
                finally:
                    stop_event.set()

            # Run both tasks; when one stops, cancel the other
            tasks = [
                asyncio.create_task(receive_from_client()),
                asyncio.create_task(receive_from_gemini()),
            ]

            # Wait for the stop event, then clean up
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                print("Session ended.")

    except Exception as e:
        print(f"Failed to connect to Gemini: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass