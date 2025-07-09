"""
Text-to-Speech Service using Resemble AI's Chatterbox.
"""

import asyncio
import logging
import time
import io
import torch
import torchaudio # For saving tensor to WAV bytes

# Attempt to import ChatterboxTTS, handle if not installed during early dev
try:
    from chatterbox.tts import ChatterboxTTS
except ImportError:
    ChatterboxTTS = None
    logging.error("ChatterboxTTS library not found. Please install chatterbox-tts.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChatterboxTTSClient:
    """
    Text-to-Speech service using Resemble AI's Chatterbox.
    """
    def __init__(self, device_setting: str = "auto"):
        """
        Initialize the ChatterboxTTS client.

        Args:
            device_setting: Preferred device ("auto", "cuda", "cpu").
        """
        self.device_setting = device_setting
        self.actual_device = self._determine_device()
        self.model = None
        self.sample_rate = None # Will be set by the loaded model
        self.is_processing = False
        self.last_processing_time = 0.0

        if ChatterboxTTS is None:
            logger.error("ChatterboxTTS library failed to import. TTS service will be unavailable.")
            return

        try:
            logger.info(f"Initializing ChatterboxTTSClient with device setting: '{self.device_setting}', resolved to: '{self.actual_device}'")
            # from_pretrained will download the model on first run if not cached by chatterbox
            self.model = ChatterboxTTS.from_pretrained(device=self.actual_device)
            
            if not self.model:
                logger.error("ChatterboxTTS.from_pretrained returned None or failed. TTS will not be available.")
                return # Stop initialization if model loading failed

            self.sample_rate = self.model.sr
            logger.info(f"Initialized ChatterboxTTSClient successfully. Model loaded on '{self.actual_device}'. Sample rate: {self.sample_rate}Hz.")
        except Exception as e:
            logger.error(f"Failed to initialize ChatterboxTTS model: {e}", exc_info=True)
            self.model = None # Ensure model is None if init fails

    def _determine_device(self) -> str:
        """Determines the actual device to use based on setting and availability."""
        if self.device_setting.lower() == "cuda":
            if torch.cuda.is_available():
                return "cuda"
            else:
                logger.warning("TTS: CUDA requested but not available. Falling back to CPU.")
                return "cpu"
        elif self.device_setting.lower() == "cpu":
            return "cpu"
        else: # "auto" or any other/default value
            if torch.cuda.is_available():
                logger.info("TTS: Auto-detected CUDA, using GPU.")
                return "cuda"
            else:
                logger.info("TTS: CUDA not available, using CPU.")
                return "cpu"

    def _generate_sync(self, text: str) -> torch.Tensor:
        """Synchronous (blocking) method to generate speech waveform."""
        if not self.model:
            raise RuntimeError("ChatterboxTTS model is not initialized or failed to load.")
        
        # According to Chatterbox documentation, model.generate() is synchronous.
        # It returns a Torch tensor.
        logger.debug(f"Chatterbox sync generate for: '{text[:30]}...'")
        wav_tensor = self.model.generate(text)
        logger.debug("Chatterbox sync generate completed.")
        return wav_tensor

    async def async_text_to_speech(self, text: str) -> bytes:
        """
        Asynchronously convert text to speech audio bytes using Chatterbox.
        The generated audio is in WAV format.
        """
        if not self.model:
            logger.error("Cannot generate speech: ChatterboxTTS model is not available.")
            return b"" # Return empty bytes if model isn't loaded

        self.is_processing = True
        request_start_time = time.time()
        audio_bytes = b""

        try:
            # Run the blocking model.generate call in a separate thread
            wav_tensor = await asyncio.to_thread(self._generate_sync, text)
            
            if wav_tensor is None or (isinstance(wav_tensor, torch.Tensor) and wav_tensor.nelement() == 0):
                logger.error("Chatterbox model generated an empty or None audio tensor.")
                return b""

            # Convert the Torch tensor to WAV audio bytes in memory
            buffer = io.BytesIO()
            
            # Ensure tensor is on CPU for torchaudio.save, and it's 2D [channels, samples]
            wav_tensor_cpu = wav_tensor.cpu()
            if wav_tensor_cpu.ndim == 1:
                wav_tensor_cpu = wav_tensor_cpu.unsqueeze(0) # Add channel dim if it's mono [L] -> [1, L]
            
            torchaudio.save(buffer, wav_tensor_cpu, self.sample_rate, format="wav")
            audio_bytes = buffer.getvalue()
            
            logger.info(f"Chatterbox: Generated speech audio ({len(audio_bytes)} bytes). Processing time: {(time.time() - request_start_time):.2f}s")

        except RuntimeError as e: # Catch errors from _generate_sync if model is bad
            logger.error(f"ChatterboxTTS runtime error in text_to_speech: {e}", exc_info=True)
        except Exception as e: # Catch other unexpected errors
            logger.error(f"Unexpected error during Chatterbox audio generation: {e}", exc_info=True)
        finally:
            self.last_processing_time = time.time() - request_start_time
            self.is_processing = False

        if not audio_bytes:
             logger.warning("ChatterboxTTSClient: async_text_to_speech is returning empty audio bytes. This may indicate an issue with TTS generation.")
        return audio_bytes

    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration and state of the ChatterboxTTSClient.
        """
        return {
            "engine_type": "chatterbox-tts",
            "configured_device_setting": self.device_setting,
            "actual_device_used": self.actual_device,
            "model_loaded_successfully": self.model is not None,
            "model_sample_rate": self.sample_rate if self.model else "N/A",
            "is_processing": self.is_processing,
            "last_processing_time_seconds": f"{self.last_processing_time:.2f}"
        }
