"""
Speech-to-Text Transcription Service

Uses IBM Granite via Hugging Face Transformers to transcribe speech audio.
"""

import numpy as np
import logging
import io
from typing import Dict, Any, Tuple
import time
import torch
import torchaudio
from torchaudio import transforms as T
from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GraniteTranscriber:
    """
    Speech-to-Text service using IBM Granite model.
    """
    
    def __init__(
        self,
        model_name: str = "ibm-granite/granite-speech-3.3-2b",
        input_sample_rate: int = 44100, # Sample rate of audio from frontend
        device: str = None
    ):
        """
        Initialize the transcription service.
        
        Args:
            model_name: Hugging Face model name for Granite STT.
            input_sample_rate: The sample rate of the incoming audio.
            device: Device to run model on ('cpu' or 'cuda'), if None will auto-detect.
        """
        self.model_name = model_name
        self.input_sample_rate = input_sample_rate
        self.model_target_sample_rate = 16000  # Granite models typically expect 16kHz

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        logger.info(f"Initializing Granite Transcriber with model={self.model_name}, device={self.device}")
        
        self._initialize_model()
        
        self.is_processing = False

    def _initialize_model(self):
        """Initialize Granite model and processor."""
        try:
            self.processor = AutoProcessor.from_pretrained(self.model_name)
            self.model = AutoModelForSpeechSeq2Seq.from_pretrained(self.model_name).to(self.device)
            self.model.eval() # Set model to evaluation mode

            # Pre-build resampler if input and target sample rates differ
            if self.input_sample_rate != self.model_target_sample_rate:
                self.resampler = T.Resample(
                    orig_freq=self.input_sample_rate,
                    new_freq=self.model_target_sample_rate
                ).to(self.device)
                logger.info(f"Resampler configured: {self.input_sample_rate}Hz -> {self.model_target_sample_rate}Hz")
            else:
                self.resampler = None

            logger.info(f"Successfully loaded Granite model and processor: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to load Granite model or processor: {e}")
            raise

    def transcribe(self, audio_bytes: bytes) -> Tuple[str, Dict[str, Any]]:
        """
        Transcribe audio data to text.
        
        Args:
            audio_bytes: Raw audio data as bytes (expected to be WAV format).
            
        Returns:
            Tuple[str, Dict[str, Any]]: 
                - Transcribed text
                - Dictionary with additional information (processing_time)
        """
        start_time = time.time()
        self.is_processing = True
        
        try:
            audio_file = io.BytesIO(audio_bytes)
            waveform, sr = torchaudio.load(audio_file)
            waveform = waveform.to(self.device)

            # Ensure mono
            if waveform.shape[0] > 1:
                waveform = torch.mean(waveform, dim=0, keepdim=True)
            
            # Resample if necessary
            if self.resampler and sr != self.model_target_sample_rate:
                if sr != self.input_sample_rate: # If loaded SR is not what we configured for resampler
                    # This case might happen if WAV file has different SR than expected
                    # Re-create resampler on the fly or log warning
                    logger.warning(f"Audio SR ({sr}Hz) differs from expected input SR ({self.input_sample_rate}Hz). Re-initializing resampler.")
                    current_resampler = T.Resample(orig_freq=sr, new_freq=self.model_target_sample_rate).to(self.device)
                    waveform = current_resampler(waveform)
                else: # SR matches expected input for resampler
                    waveform = self.resampler(waveform)
            elif sr != self.model_target_sample_rate:
                 # No pre-built resampler, but SR mismatch exists
                logger.warning(f"Audio SR ({sr}Hz) differs from model target SR ({self.model_target_sample_rate}Hz) and no pre-built resampler. Attempting dynamic resampling.")
                current_resampler = T.Resample(orig_freq=sr, new_freq=self.model_target_sample_rate).to(self.device)
                waveform = current_resampler(waveform)


            # Prepare text prompt for Granite model (as per Hugging Face example)
            # Using a simplified system prompt for transcription purposes.
            chat_prompt = [
                {"role": "system", "content": "You are an ASR system. Transcribe the audio accurately."},
                {"role": "user", "content": "<|audio|>Transcribe the provided audio snippet."},
            ]
            text_input_for_prompt = self.processor.tokenizer.apply_chat_template(
                chat_prompt, tokenize=False, add_generation_prompt=True
            )

            # Process audio and text prompt
            # The processor expects a 1D numpy array or list of floats for audio.
            # Waveform is currently a 2D tensor [1, num_samples], so squeeze and convert.
            processed_audio = waveform.squeeze().cpu().numpy()

            model_inputs = self.processor(
                text=text_input_for_prompt,
                audio=processed_audio,
                sampling_rate=self.model_target_sample_rate, # Pass the sample rate of the audio given to processor
                return_tensors="pt",
            ).to(self.device)

            # Generate transcription
            # Adjust generation parameters as needed, e.g., num_beams for quality vs. speed
            generated_outputs = self.model.generate(
                **model_inputs,
                max_new_tokens=256, # Max length of the transcription
                num_beams=3,        # Beam search can improve quality
                # temperature=1.0,    # Default, for less random transcription
                # do_sample=False,    # Default for generate if num_beams > 1
            )
            
            # Decode the generated tokens, removing the prompt part
            # This logic is specific to how Granite models with text prompts return outputs.
            num_input_tokens = model_inputs["input_ids"].shape[-1]
            # Ensure generated_outputs is correctly indexed if it's a sequence/tuple
            output_ids = generated_outputs[0] if isinstance(generated_outputs, (list, tuple)) else generated_outputs
            
            # Check if output_ids has enough tokens
            if output_ids.shape[-1] <= num_input_tokens:
                transcription = "" # Or handle as an error/empty transcription
                logger.warning("Not enough tokens in output to decode transcription after prompt.")
            else:
                new_tokens = torch.unsqueeze(output_ids[num_input_tokens:], dim=0)
                transcription = self.processor.tokenizer.batch_decode(
                    new_tokens, skip_special_tokens=True, add_special_tokens=False
                )[0].strip()

            processing_time = time.time() - start_time
            logger.info(f"Granite transcription completed in {processing_time:.2f}s: {transcription[:100]}...")
            
            metadata = {
                "processing_time": processing_time,
                "language": "en", # Assuming English for now as per typical Granite use
                # Granite generate doesn't directly give segment confidence like faster-whisper
            }
            
            return transcription, metadata
            
        except Exception as e:
            logger.error(f"Granite transcription error: {e}", exc_info=True)
            return "", {"error": str(e), "processing_time": time.time() - start_time}
        finally:
            self.is_processing = False
            
    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration.
        """
        return {
            "model_name": self.model_name,
            "device": self.device,
            "input_sample_rate": self.input_sample_rate,
            "model_target_sample_rate": self.model_target_sample_rate,
            "is_processing": self.is_processing,
        }

```
A few notes on the implementation:
- The `audio_bytes` input is assumed to be loadable by `torchaudio.load` (e.g. WAV format). The existing code in `websocket.py` decodes base64 audio and passes bytes, which should be fine.
- Resampling is handled. I added a check in case the loaded audio's SR doesn't match the `input_sample_rate` used to initialize the pre-built resampler.
- The Granite model uses a chat-like prompt structure that includes an `<|audio|>` tag. I've adapted this from the Hugging Face example.
- Decoding the output requires stripping the input prompt tokens, which is also adapted from the example.
- Error handling for `generated_outputs` shape is added.
- Basic metadata (processing time, language) is returned. Detailed confidence scores per segment are not standard with this `generate` approach.

Next, I need to update `backend/main.py` to use this new `GraniteTranscriber` and the new config values.
