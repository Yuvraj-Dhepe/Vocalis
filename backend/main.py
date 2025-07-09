"""
Vocalis Backend Server

FastAPI application entry point.
"""

import logging
import uvicorn
from fastapi import FastAPI, WebSocket, Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import io
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
# Renaming to avoid conflict with global Depends if it were an issue, using FastAPI_Depends for clarity
from fastapi import Depends as FastAPI_Depends

# Import configuration
from . import config

# Import services
from .services.transcription import GraniteTranscriber
from .services.llm import OllamaClient
from .services.tts import ChatterboxTTSClient # MODIFIED
from .services.vision import vision_service

# Import routes
from .routes.websocket import websocket_endpoint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global service instances
transcription_service = None
llm_service = None
tts_service = None
# Vision service is a singleton already initialized in its module

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown events for the FastAPI application.
    """
    # Load configuration
    cfg = config.get_config()
    
    # Initialize services on startup
    logger.info("Initializing services...")
    
    global transcription_service, llm_service, tts_service
    
    # Initialize transcription service
    transcription_service = GraniteTranscriber( # MODIFIED
        model_name=cfg["stt_model_name"],      # MODIFIED from whisper_model
        input_sample_rate=cfg["audio_sample_rate"] # MODIFIED ensure key exists in cfg
    )
    
    # Initialize LLM service
    llm_service = OllamaClient( # MODIFIED
        host=cfg["ollama_host"],
        model=cfg["ollama_model"]
        # Temperature and num_predict will use OllamaClient defaults for now
        # or can be added to config.py and passed here if needed.
    )
    
    # Initialize TTS service
    tts_service = ChatterboxTTSClient( # MODIFIED
        device_setting=cfg["tts_device"]
    )
    
    # Initialize vision service (will download model if not cached)
    logger.info("Initializing vision service...")
    vision_service.initialize()
    
    logger.info("All services initialized successfully")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down services...")
    
    # No specific cleanup needed for these services,
    # but we could add resource release code here if needed (maybe in a future release lex 31/03/25)
    
    logger.info("Shutdown complete")

# Define request model for TTS
class TTSRequest(BaseModel):
    text: str

# Create FastAPI application
app = FastAPI(
    title="Vocalis Backend",
    description="Speech-to-Speech AI Assistant Backend",
    version="0.1.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service dependency functions
def get_transcription_service():
    return transcription_service

def get_llm_service():
    return llm_service

def get_tts_service():
    return tts_service

# API routes
@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {"status": "ok", "message": "Vocalis backend is running"}


@app.post("/api/stt") # Removed dependencies=[FastAPI_Depends(verify_api_key)]
async def api_speech_to_text(audio_file: UploadFile = File(...)):
    """
    Speech-to-Text REST Endpoint.
    Accepts an audio file and returns the transcription.
    """
    if not transcription_service:
        logger.error("/api/stt: Transcription service not available.")
        raise HTTPException(status_code=503, detail="Transcription service not available.")
    try:
        audio_bytes = await audio_file.read()
        if not audio_bytes:
            logger.warning("/api/stt: No audio content provided in uploaded file.")
            raise HTTPException(status_code=400, detail="No audio content provided.")

        logger.info(f"/api/stt: Received audio file '{audio_file.filename}', size {len(audio_bytes)} bytes for STT.")

        transcript, metadata = transcription_service.transcribe(audio_bytes)

        if "error" in metadata and metadata["error"]:
            logger.error(f"/api/stt: Transcription engine error: {metadata['error']}")
            raise HTTPException(status_code=500, detail=f"STT engine error: {metadata['error']}")

        logger.info(f"/api/stt: Transcription successful for '{audio_file.filename}'.")
        return JSONResponse(content={"transcription": transcript, "metadata": metadata})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in /api/stt endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during STT processing: {str(e)}")

@app.post("/api/tts") # Removed dependencies=[FastAPI_Depends(verify_api_key)]
async def api_text_to_speech(request: TTSRequest):
    """
    Text-to-Speech REST Endpoint.
    Accepts text and returns synthesized speech audio (WAV format).
    """
    if not tts_service:
        logger.error("/api/tts: TTS service not available.")
        raise HTTPException(status_code=503, detail="TTS service not available.")
    try:
        if not request.text.strip():
            logger.warning("/api/tts: Received empty text for synthesis.")
            raise HTTPException(status_code=400, detail="Text for TTS cannot be empty.")

        logger.info(f"/api/tts: Received text for synthesis: '{request.text[:100]}...'")
        audio_bytes = await tts_service.async_text_to_speech(request.text)

        if not audio_bytes:
            logger.error("/api/tts: TTS service returned no audio data for the provided text.")
            raise HTTPException(status_code=500, detail="TTS engine failed to produce audio for the given text.")

        logger.info(f"/api/tts: Synthesized audio successfully ({len(audio_bytes)} bytes).")
        return StreamingResponse(io.BytesIO(audio_bytes), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in /api/tts endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error during TTS processing: {str(e)}")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "services": {
            "transcription": transcription_service is not None,
            "llm": llm_service is not None,
            "tts": tts_service is not None,
            "vision": vision_service.is_ready()
        },
        "config": {
            "stt_model_name": cfg.get("stt_model_name", config.STT_MODEL_NAME),
            "ollama_model": cfg.get("ollama_model", config.OLLAMA_MODEL),
            "tts_device": cfg.get("tts_device", config.TTS_DEVICE), # MODIFIED for Chatterbox
            "websocket_port": cfg.get("websocket_port", config.WEBSOCKET_PORT)
        }
    }

@app.get("/config")
async def get_full_config():
    """Get full configuration."""
    cfg = config.get_config()
    if not all([transcription_service, llm_service, tts_service]) or not vision_service.is_ready(): # check vision_service.is_ready()
        # Check individual services for more granular error reporting if needed
        if not transcription_service: logger.error("Transcription service not initialized for /config")
        if not llm_service: logger.error("LLM service not initialized for /config")
        if not tts_service: logger.error("TTS service not initialized for /config")
        if not vision_service.is_ready(): logger.error("Vision service not ready for /config")
        raise HTTPException(status_code=503, detail="One or more services are not initialized or ready.")
    
    # Ensure services' get_config() methods are called and robust to ongoing changes
    transcription_config = transcription_service.get_config() if hasattr(transcription_service, 'get_config') else {}
    llm_config = llm_service.get_config() if hasattr(llm_service, 'get_config') else {}
    tts_config = tts_service.get_config() if hasattr(tts_service, 'get_config') else {}

    return {
        "transcription": transcription_config,
        "llm": llm_config,
        "tts": tts_config,
        "system": cfg
    }

# WebSocket route
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    """WebSocket endpoint for bidirectional audio streaming."""
    # Ensure services are available (they are global, initialized in lifespan)
    if not all([transcription_service, llm_service, tts_service]):
        logger.error("Services not fully initialized for WebSocket connection.")
        # Optionally, close WebSocket or send an error message
        # await websocket.close(code=1011, reason="Backend services not ready")
        # return
        # For now, proceed, but this indicates an issue if it happens post-startup.
        pass

    await websocket_endpoint(
        websocket, 
        transcription_service, 
        llm_service, 
        tts_service
    )

# Run server directly if executed as script
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=config.WEBSOCKET_HOST,
        port=config.WEBSOCKET_PORT,
        reload=True
    )
