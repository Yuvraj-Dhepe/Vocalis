"""
Text-to-Speech Service using RealtimeTTS.
"""

import asyncio
import logging
import time
import io
from typing import Dict, Any

try:
    from RealtimeTTS import TextToAudioStream, SystemEngine
    # For other engines, you might import them here, e.g.:
    # from RealtimeTTS import CoquiEngine, OpenAIEngine, AzureEngine, ElevenlabsEngine
except ImportError:
    TextToAudioStream = None
    SystemEngine = None
    logging.error("RealtimeTTS library not found. Please install RealtimeTTS (e.g., pip install realtimetts[system]).")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RealtimeTTSClient:
    """
    Text-to-Speech service using RealtimeTTS.
    """
    def __init__(self, device_setting: str = "auto"): # device_setting might be less relevant for SystemEngine
        """
        Initialize the RealtimeTTS client.
        For SystemEngine, device_setting is not directly used but kept for consistency.
        """
        self.engine_name = "SystemEngine" # Defaulting to SystemEngine
        self.engine = None
        self.stream = None
        self.is_processing = False
        self.last_processing_time = 0.0
        self.actual_device = "cpu" # SystemEngine typically uses CPU

        if TextToAudioStream is None or SystemEngine is None:
            logger.error("RealtimeTTS library components failed to import. TTS service will be unavailable.")
            return

        try:
            logger.info(f"Initializing RealtimeTTSClient with {self.engine_name}...")
            # Here you could add logic to select different engines based on config
            # For now, hardcoding SystemEngine
            self.engine = SystemEngine()
            if not self.engine:
                logger.error(f"{self.engine_name} failed to initialize. TTS will not be available.")
                return

            self.stream = TextToAudioStream(self.engine, muted=True, level=logging.WARNING) # Muted as we capture bytes
            logger.info(f"Initialized RealtimeTTSClient with {self.engine_name} successfully.")

        except Exception as e:
            logger.error(f"Failed to initialize RealtimeTTS ({self.engine_name}): {e}", exc_info=True)
            self.engine = None
            self.stream = None

    async def async_text_to_speech(self, text: str) -> bytes:
        """
        Asynchronously convert text to speech audio bytes using RealtimeTTS.
        The generated audio is in WAV format.
        """
        if not self.stream or not self.engine:
            logger.error("Cannot generate speech: RealtimeTTS stream or engine is not available.")
            return b""

        self.is_processing = True
        request_start_time = time.time()
        audio_bytes = b""

        # Using BytesIO to capture WAV output
        wav_buffer = io.BytesIO()

        try:
            logger.debug(f"RealtimeTTS ({self.engine_name}) generating for: '{text[:30]}...'")
            
            # Feed the text to the stream
            self.stream.feed(text)

            # The play_async method can write to a file-like object.
            # We need to run this part in a thread as play() itself can be blocking
            # or manage its own async operations internally that might not align with FastAPI's loop.
            # However, TextToAudioStream's play_async is already designed to be non-blocking.
            # The challenge is capturing the output.
            # Let's try using the output_wavfile parameter with a BytesIO buffer.
            # The play_async method itself doesn't directly return bytes.
            # It plays audio or writes to a file.
            # The `on_audio_chunk` callback or saving to BytesIO are options.

            # According to RealtimeTTS docs, to save to a file (or BytesIO):
            # stream.play_async(output_wavfile="temp.wav") -> this writes to disk
            # To capture bytes, we can try:
            # 1. Use a callback `on_audio_chunk` to accumulate bytes.
            # 2. Use `stream.play(output_wavfile=wav_buffer)` in a thread.

            # Option 2: run play() in a thread and write to BytesIO
            def play_to_buffer():
                self.stream.play(output_wavfile=wav_buffer) # This is blocking

            # Run the blocking play method in a separate thread
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, play_to_buffer)
            
            wav_buffer.seek(0) # Reset buffer position to the beginning for reading
            audio_bytes = wav_buffer.read()

            if not audio_bytes:
                 logger.warning(f"RealtimeTTS ({self.engine_name}) returned empty audio bytes.")
            else:
                logger.info(f"RealtimeTTS ({self.engine_name}): Generated speech audio ({len(audio_bytes)} bytes).")

        except Exception as e:
            logger.error(f"Unexpected error during RealtimeTTS ({self.engine_name}) audio generation: {e}", exc_info=True)
            audio_bytes = b"" # Ensure empty bytes on error
        finally:
            self.last_processing_time = time.time() - request_start_time
            self.is_processing = False
            # Clear the stream queue for the next synthesis
            if self.stream:
                self.stream.stop() # Stop any ongoing playback
                # Reset or re-initialize parts of the stream if necessary.
                # For TextToAudioStream, feeding new text implicitly clears old text.
                # Re-creating stream or engine for each call might be too slow.
                # Ensure stream is ready for next call.
                # The stream.feed() should handle new text, but ensure no leftover state.
                # Let's re-initialize the stream to be safe for now, or ensure stop() clears state.
                # Re-initializing the stream for each call:
                # self.stream = TextToAudioStream(self.engine, muted=True, level=logging.WARNING)
                # This might be inefficient. Let's rely on feed and stop for now.
                # If issues arise, re-evaluate stream re-initialization.
                pass


        if not audio_bytes:
             logger.warning(f"RealtimeTTSClient ({self.engine_name}): async_text_to_speech is returning empty audio bytes. This may indicate an issue with TTS generation.")
        return audio_bytes

    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration and state of the RealtimeTTSClient.
        """
        return {
            "engine_type": "realtimetts",
            "engine_used": self.engine_name,
            "model_loaded_successfully": self.engine is not None and self.stream is not None,
            "actual_device_used": self.actual_device, # Placeholder, SystemEngine specific device might not be exposed
            "is_processing": self.is_processing,
            "last_processing_time_seconds": f"{self.last_processing_time:.2f}"
        }

# Example of how to use a different engine like CoquiEngine (requires GPU and more setup)
# class RealtimeTTSClient_Coqui:
#     def __init__(self, speaker_wav_path: str = None): # speaker_wav_path for voice cloning
#         self.engine_name = "CoquiEngine"
#         self.engine = None
#         self.stream = None
#         # ... (similar init logic) ...
#         try:
#             from RealtimeTTS import CoquiEngine # Import CoquiEngine
#             logger.info(f"Initializing RealtimeTTSClient with {self.engine_name}...")
#             # CoquiEngine might require specific parameters like a speaker WAV for cloning
#             self.engine = CoquiEngine(voice=speaker_wav_path if speaker_wav_path else None)
#             self.stream = TextToAudioStream(self.engine, muted=True)
#             logger.info(f"Initialized RealtimeTTSClient with {self.engine_name} successfully.")
#         except Exception as e:
#             logger.error(f"Failed to initialize RealtimeTTS ({self.engine_name}): {e}", exc_info=True)
#         # ... (async_text_to_speech and get_config would be similar) ...
