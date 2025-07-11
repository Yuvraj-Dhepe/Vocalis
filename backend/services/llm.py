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
        num_predict: int = 2048,
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
            self.client = ollama.Client(host=self.host)
            self.client.list()
            logger.info(f"Initialized Ollama Client with host={self.host}. Connection successful. Default model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Ollama Client or connect to host {self.host}: {e}", exc_info=True)
            self.client = None

    def add_to_history(self, role: str, content: str) -> None:
        """
        Add a message to the conversation history.
        """
        self.conversation_history.append({"role": role, "content": content})
        
        max_history_len = 50
        if len(self.conversation_history) > max_history_len:
            preserved_prefix = []
            if self.conversation_history[0]["role"] == "system":
                preserved_prefix.append(self.conversation_history[0])
                if len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                    preserved_prefix.append(self.conversation_history[1])

            num_to_keep_from_end = max_history_len - len(preserved_prefix)
            self.conversation_history = preserved_prefix + self.conversation_history[-num_to_keep_from_end:]

    def set_user_context(self, user_name: str) -> bool:
        """
        Initialize or update the conversation context with user information.
        """
        if not user_name:
            return False

        context_message = {
            "role": "system",
            "content": f"USER CONTEXT: The user's name is {user_name}."
        }

        # Find if a user context message already exists
        user_context_index = -1
        for i, msg in enumerate(self.conversation_history):
            if msg.get("role") == "system" and "USER CONTEXT:" in msg.get("content", ""):
                user_context_index = i
                break
        
        if user_context_index != -1:
            # Replace existing context message
            self.conversation_history[user_context_index] = context_message
            logger.info(f"Updated user context in conversation history for user: {user_name}")
        else:
            # Insert after the main system prompt if it exists
            insertion_point = 0
            if self.conversation_history and self.conversation_history[0]["role"] == "system":
                insertion_point = 1
            self.conversation_history.insert(insertion_point, context_message)
            logger.info(f"Added user context to conversation history for user: {user_name}")
            
        return True

    def get_response(self, user_input: str, system_prompt: Optional[str] = None,
                    add_to_history: bool = True, temperature: Optional[float] = None) -> Dict[str, Any]:
        """
        Get a response from the Ollama LLM for the given user_input.
        This is a synchronous (blocking) call.
        """
        if not self.client:
            logger.error("Ollama client is not initialized or connection failed. Cannot get response.")
            return {
                "text": "Ollama service is currently unavailable.",
                "error": "Ollama client not initialized or connection failed.",
                "processing_time": 0, "model": self.model, "finish_reason": "error"
            }

        self.is_processing = True
        request_start_time = time.time()

        messages_for_api: List[Dict[str, str]] = []

        current_system_messages = []
        history_without_initial_system = list(self.conversation_history)

        if self.conversation_history and self.conversation_history[0]["role"] == "system":
            current_system_messages.append(self.conversation_history[0])
            history_without_initial_system.pop(0)
            if self.conversation_history and len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                 current_system_messages.append(self.conversation_history[1])
                 history_without_initial_system.pop(0)

        if system_prompt:
            messages_for_api.append({"role": "system", "content": system_prompt})
        elif current_system_messages:
            messages_for_api.extend(current_system_messages)

        messages_for_api.extend(history_without_initial_system)

        if user_input.strip():
            messages_for_api.append({"role": "user", "content": user_input})

        current_temperature = temperature if temperature is not None else self.default_temperature
        options = {
            "temperature": current_temperature,
            "num_predict": self.default_num_predict,
            **self.default_llm_options
        }
        
        try:
            logger.info(f"Sending request to Ollama model '{self.model}' with {len(messages_for_api)} messages. Options: {options}")
            
            api_response = self.client.chat(
                model=self.model, messages=messages_for_api, stream=False, options=options
            )
            
            assistant_message_content = api_response['message']['content']
            
            if add_to_history:
                if user_input.strip():
                    self.add_to_history("user", user_input)
                if assistant_message_content:
                    self.add_to_history("assistant", assistant_message_content)

            processing_time = time.time() - request_start_time
            logger.info(f"Received response from Ollama model '{api_response.get('model', self.model)}' in {processing_time:.2f}s.")
            
            return {
                "text": assistant_message_content, "processing_time": processing_time,
                "model": api_response.get('model', self.model),
                "finish_reason": api_response.get('done_reason', api_response.get('done_reason_details', {}).get('reason'))
            }

        except ollama.ResponseError as e:
            logger.error(f"Ollama API ResponseError: {e.status_code} - {e.error}", exc_info=True)
            error_text = f"Ollama error: {e.error}"
            return {"text": error_text, "error": str(e), "processing_time": time.time() - request_start_time}
        except Exception as e:
            logger.error(f"Ollama client general error: {e}", exc_info=True)
            error_text = "Sorry, I encountered an unexpected error while communicating with the Ollama language model."
            return {"text": error_text, "error": str(e), "processing_time": time.time() - request_start_time}
        finally:
            self.is_processing = False

    def clear_history(self, keep_system_prompt: bool = True) -> None:
        preserved_messages = []
        if keep_system_prompt and self.conversation_history:
            if self.conversation_history[0]["role"] == "system":
                preserved_messages.append(self.conversation_history[0])
                if len(self.conversation_history) > 1 and self.conversation_history[1]["role"] == "system":
                    preserved_messages.append(self.conversation_history[1])

        self.conversation_history = preserved_messages
        logger.info(f"Ollama conversation history cleared. Current length: {len(self.conversation_history)}")
    
    def get_config(self) -> Dict[str, Any]:
        return {
            "host": self.host, "model": self.model,
            "default_temperature": self.default_temperature,
            "default_num_predict": self.default_num_predict,
            "default_llm_options": self.default_llm_options,
            "is_processing": self.is_processing,
            "history_length": len(self.conversation_history),
            "client_initialized": self.client is not None
        }
