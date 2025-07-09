"""
LLM Service

Handles communication with an Ollama server using the official ollama client.
"""

import ollama # Official Ollama client
import logging
import time
from typing import Dict, Any, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OllamaClient:
    """
    Client for communicating with an Ollama server.
    """
    
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "llama3",
        temperature: float = 0.7,
        num_predict: int = 2048, # Max tokens to generate, ollama calls it num_predict. Default from old client.
                                 # Ollama default is 128. Let's use a more generous default or make it configurable.
                                 # For now, using a higher default like the old client.
        default_llm_options: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the Ollama client.
        
        Args:
            host: URL of the Ollama server.
            model: Default model name to use for chat.
            temperature: Default sampling temperature.
            num_predict: Default maximum number of tokens to generate.
            default_llm_options: Other Ollama options if needed.
        """
        self.host = host
        self.model = model
        self.default_temperature = temperature
        self.default_num_predict = num_predict
        self.default_llm_options = default_llm_options if default_llm_options is not None else {}

        self.is_processing = False
        self.conversation_history: List[Dict[str, str]] = []

        try:
            # Initialize the synchronous client
            self.client = ollama.Client(host=self.host)
            # Perform a quick check to ensure the client can connect and list models
            self.client.list()
            logger.info(f"Initialized Ollama Client with host={self.host}. Connection successful. Default model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama Client or connect to host {self.host}: {e}", exc_info=True)
            self.client = None # Indicate that the client is not usable

    def add_to_history(self, role: str, content: str) -> None:
        """
        Add a message to the conversation history.
        """
        self.conversation_history.append({"role": role, "content": content})
        
        # Simple history cap
        max_history_len = 50
        if len(self.conversation_history) > max_history_len:
            # If the first message is a system prompt, try to preserve it.
            if self.conversation_history[0]["role"] == "system":
                # Check for a potential second system message (e.g. user context)
                if len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                    self.conversation_history = [
                        self.conversation_history[0],
                        self.conversation_history[1]
                    ] + self.conversation_history[-(max_history_len-2):]
                else:
                    self.conversation_history = [self.conversation_history[0]] + self.conversation_history[-(max_history_len-1):]
            else:
                self.conversation_history = self.conversation_history[-max_history_len:]
    
    def get_response(self, user_input: str, system_prompt: Optional[str] = None, 
                    add_to_history: bool = True, temperature: Optional[float] = None) -> Dict[str, Any]:
        """
        Get a response from the Ollama LLM for the given user input.
        This is a synchronous (blocking) call.
        """
        if not self.client:
            logger.error("Ollama client is not initialized or connection failed. Cannot get response.")
            return {
                "text": "Ollama service is currently unavailable.",
                "error": "Ollama client not initialized or connection failed.",
                "processing_time": 0,
                "model": self.model,
                "finish_reason": "error"
            }

        self.is_processing = True
        request_start_time = time.time()

        # Prepare messages for Ollama API
        messages_for_api: List[Dict[str, str]] = []

        # Handle system prompt:
        # If a system_prompt is provided, it should typically be the first message.
        # The conversation_history might already contain a system prompt.
        # This logic tries to ensure only one effective system prompt is at the start.
        has_history_system_prompt = False
        if self.conversation_history and self.conversation_history[0]["role"] == "system":
            has_history_system_prompt = True

        if system_prompt:
            if not has_history_system_prompt or self.conversation_history[0]["content"] != system_prompt:
                # If new system prompt is different or no system prompt in history, prepend it.
                messages_for_api.append({"role": "system", "content": system_prompt})
        elif has_history_system_prompt:
            # If no new system prompt, but history has one, use it.
             messages_for_api.append(self.conversation_history[0])
             # If history also has a second system message (user context), add it too
             if len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                 messages_for_api.append(self.conversation_history[1])


        # Add relevant conversation history (excluding the system prompt if already added)
        history_to_add = self.conversation_history
        if messages_for_api and messages_for_api[0]["role"] == "system": # if system prompt was added from arg or history[0]
            start_index = 1
            if len(messages_for_api) > 1 and messages_for_api[1]["role"] == "system": # if user_context system prompt was also added
                start_index = 2
            history_to_add = self.conversation_history[start_index:]

        messages_for_api.extend(history_to_add)

        # Add current user input
        if user_input.strip(): # Ensure not empty
            messages_for_api.append({"role": "user", "content": user_input})

        # Determine temperature and other options for this specific call
        current_temperature = temperature if temperature is not None else self.default_temperature
        options = {
            "temperature": current_temperature,
            "num_predict": self.default_num_predict, # Max tokens
            **self.default_llm_options # Merge any other default options
        }
        
        try:
            logger.info(f"Sending request to Ollama model '{self.model}' with {len(messages_for_api)} messages. Options: {options}")
            
            api_response = self.client.chat(
                model=self.model,
                messages=messages_for_api,
                stream=False, # Synchronous client does not stream here by default with .chat
                options=options
            )
            
            assistant_message_content = api_response['message']['content']
            
            # Update conversation history if requested
            if add_to_history:
                if user_input.strip(): # Add the user's input that led to this response
                    self.add_to_history("user", user_input)
                if assistant_message_content: # Add the assistant's response
                    self.add_to_history("assistant", assistant_message_content)
            
            processing_time = time.time() - request_start_time
            logger.info(f"Received response from Ollama model '{api_response.get('model', self.model)}' in {processing_time:.2f}s.")
            
            return {
                "text": assistant_message_content,
                "processing_time": processing_time,
                "model": api_response.get('model', self.model),
                "finish_reason": api_response.get('done_reason', api_response.get('done_reason_details', {}).get('reason'))
            }

        except ollama.ResponseError as e:
            logger.error(f"Ollama API ResponseError: {e.status_code} - {e.error}", exc_info=True)
            error_text = f"Ollama error: {e.error}"
            # Optionally add error to history to inform user, but be cautious with loops
            # if add_to_history: self.add_to_history("assistant", error_text)
            return {"text": error_text, "error": str(e), "processing_time": time.time() - request_start_time}
        except Exception as e: # Catch other potential errors (network, etc.)
            logger.error(f"Ollama client general error: {e}", exc_info=True)
            error_text = "Sorry, I encountered an unexpected error while communicating with the Ollama language model."
            # if add_to_history: self.add_to_history("assistant", error_text)
            return {"text": error_text, "error": str(e), "processing_time": time.time() - request_start_time}
        finally:
            self.is_processing = False

    def clear_history(self, keep_system_prompt: bool = True) -> None:
        """
        Clear conversation history.
        
        Args:
            keep_system_prompt: If True, preserves the initial system message(s) if they exist.
        """
        preserved_messages = []
        if keep_system_prompt and self.conversation_history:
            if self.conversation_history[0]["role"] == "system":
                preserved_messages.append(self.conversation_history[0])
                # Check for a second system message (e.g., user context from websocket.py)
                if len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                    preserved_messages.append(self.conversation_history[1])

        self.conversation_history = preserved_messages
        logger.info(f"Ollama conversation history cleared. Current length: {len(self.conversation_history)}")
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get the current configuration of the Ollama client.
        """
        return {
            "host": self.host,
            "model": self.model,
            "default_temperature": self.default_temperature,
            "default_num_predict": self.default_num_predict,
            "default_llm_options": self.default_llm_options,
            "is_processing": self.is_processing,
            "history_length": len(self.conversation_history),
            "client_initialized": self.client is not None
        }

```

Now, I'll update `backend/main.py` to use this `OllamaClient` and pass the correct configuration from `cfg`.
