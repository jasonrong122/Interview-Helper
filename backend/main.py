import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv() # This safely loads your key into the environment variables

app = FastAPI()

# Initialize the GenAI client (Requires GEMINI_API_KEY environment variable)
client = genai.Client()

@app.websocket("/ws/system-design")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Local client connected!")
    
    # Configure the Gemini Live API session persona
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO], # We only want Gemini to speak back
        system_instruction=types.Content(
            parts=[types.Part.from_text(
                "You are a Senior Engineering Manager conducting a system design interview. "
                "The user is drawing a system architecture on screen and explaining it out loud. "
                "Watch their diagram closely. If they make an architectural mistake, or if they "
                "choose a relational database for a highly scalable read-heavy system without "
                "mentioning caching, gently interrupt them and ask them to justify their choice."
            )]
        )
    )

    try:
        # Connect to the Gemini Live API using the async client
        async with client.aio.live.connect(model="gemini-2.0-flash", config=config) as session:
            print("Connected to Gemini Live API!")

            # Task 1: Receive video/audio from your local PC and send it to Gemini
            async def receive_from_client():
                try:
                    while True:
                        # We will define the exact JSON/binary format for this later
                        message = await websocket.receive_bytes() 
                        await session.send(input=message) 
                except WebSocketDisconnect:
                    print("Local client disconnected.")

            # Task 2: Receive spoken audio from Gemini and send it back to your PC to play
            async def receive_from_gemini():
                try:
                    async for response in session.receive():
                        server_content = response.server_content
                        if server_content is not None and server_content.model_turn is not None:
                            for part in server_content.model_turn.parts:
                                if part.inline_data:
                                    # Send the raw audio bytes back down the WebSocket
                                    await websocket.send_bytes(part.inline_data.data)
                except asyncio.CancelledError:
                    pass

            # Run both streaming tasks at the same time
            client_task = asyncio.create_task(receive_from_client())
            gemini_task = asyncio.create_task(receive_from_gemini())
            
            await asyncio.gather(client_task, gemini_task)

    except Exception as e:
        print(f"Error connecting to Gemini: {e}")
        await websocket.close()