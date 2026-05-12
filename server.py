import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

load_dotenv()

app = FastAPI(title="School Voice AI Agent — Token Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/token")
async def get_token(room_name: str = "school-voice-room", participant_name: str | None = None):
    """Generate a LiveKit access token for the frontend to join a room."""
    if participant_name is None:
        participant_name = f"user-{uuid.uuid4().hex[:8]}"

    token = api.AccessToken(
        api_key=os.environ["LIVEKIT_API_KEY"],
        api_secret=os.environ["LIVEKIT_API_SECRET"],
    ).with_identity(participant_name).with_name(participant_name).with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
        )
    )

    return {
        "token": token.to_jwt(),
        "url": os.environ["LIVEKIT_URL"],
        "participant_name": participant_name,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
