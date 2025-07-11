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
            self.processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=True)
            self.model = AutoModelForSpeechSeq2Seq.from_pretrained(self.model_name, trust_remote_code=True).to(self.device)
            self.model.eval() # Set model to evaluation mode

            if self.input_sample_rate != self.model_target_sample_rate:
                self.resampler = T.Resample(
                    orig_freq=self.input_sample_rate,
                    new_freq=self.model_target_sample_rate
                ).to(self.device)
                logger.info(f"Resampler configured for input: {self.input_sample_rate}Hz -> {self.model_target_sample_rate}Hz")
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

            if waveform.shape[0] > 1: # Ensure mono
                waveform = torch.mean(waveform, dim=0, keepdim=True)

            current_resampler_to_use = None
            if sr != self.model_target_sample_rate:
                if self.resampler and sr == self.input_sample_rate:
                    current_resampler_to_use = self.resampler
                else:
                    logger.warning(f"Audio SR ({sr}Hz) differs from configured input SR ({self.input_sample_rate}Hz) or target SR. Creating dynamic resampler {sr}Hz -> {self.model_target_sample_rate}Hz.")
                    current_resampler_to_use = T.Resample(orig_freq=sr, new_freq=self.model_target_sample_rate).to(self.device)
            
            if current_resampler_to_use:
                waveform = current_resampler_to_use(waveform)

            chat_prompt_messages = [
                {"role": "system", "content": "You are an ASR system. Transcribe the audio accurately."},
                {"role": "user", "content": "<|audio|>Transcribe the provided audio snippet."},
            ]
            text_input_for_prompt = self.processor.tokenizer.apply_chat_template(
                chat_prompt_messages, tokenize=False, add_generation_prompt=True
            )

            processed_audio_input = waveform.squeeze().cpu().numpy()

            model_inputs = self.processor(
                text=text_input_for_prompt,
                audio=processed_audio_input,
                sampling_rate=self.model_target_sample_rate,
                return_tensors="pt",
            ).to(self.device)

            generated_outputs = self.model.generate(
                **model_inputs,
                max_new_tokens=256,
                num_beams=3,
            )
            
            num_input_tokens = model_inputs["input_ids"].shape[-1]
            output_ids = generated_outputs[0]

            if output_ids.shape[-1] <= num_input_tokens:
                transcription = ""
                logger.warning("Not enough tokens in STT output to decode transcription after prompt.")
            else:
                new_tokens_ids = output_ids[num_input_tokens:]
                new_tokens_ids_batched = torch.unsqueeze(new_tokens_ids, dim=0)

                transcription = self.processor.tokenizer.batch_decode(
                    new_tokens_ids_batched, skip_special_tokens=True, add_special_tokens=False
                )[0].strip()

            processing_time = time.time() - start_time
            logger.info(f"Granite transcription completed in {processing_time:.2f}s: {transcription[:100]}...")
            
            metadata = {
                "processing_time": processing_time,
                "language": "en",
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
