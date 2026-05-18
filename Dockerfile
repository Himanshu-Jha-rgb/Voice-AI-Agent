# Use a multi-stage build to keep the final image slim
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Final image
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Install system dependencies for audio and LiveKit
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Copy project files
COPY . .

# Copy built frontend from the first stage
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Expose the port FastAPI will run on (Hugging Face default is 7860)
EXPOSE 7860

# Create a startup script to run both the server and the agent
RUN echo '#!/bin/bash\n\
uv run python agent.py start & \n\
uv run uvicorn server:app --host 0.0.0.0 --port 7860\n\
' > start.sh && chmod +x start.sh

# Set environment variables (should be configured in HF Space secrets)
# LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, SARVAM_API_KEY, etc.

CMD ["./start.sh"]
