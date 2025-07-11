# Vocalis Backend API Documentation

This document provides details for the REST API endpoints offered by the Vocalis backend.
The primary interaction with the Vocalis assistant is intended through its WebSocket interface used by the frontend. These REST APIs provide direct access to certain backend functionalities.

## Authentication

Previously, REST API endpoints required an API key. However, for the local REST endpoints (`/api/stt`, `/api/tts`), this is currently **not enforced** in the backend code. The `X-API-Key` header might be ignored.

If authentication were active:
The API key would be included in the `X-API-Key` header of your request.
Example Header: `X-API-Key: your_secret_api_key`
The API key can be configured via the `VOCALIS_API_KEY` environment variable in the `backend/.env` file (default is "development_secret_key").

## Endpoints

### 1. Speech-to-Text (STT)

Converts spoken audio into text using the configured STT engine (IBM Granite).

-   **URL:** `/api/stt`
-   **Method:** `POST`
-   **Headers:**
    -   `X-API-Key: <your_api_key>`
-   **Request Body:**
    -   Form-data with a single field:
        -   `audio_file`: The audio file to transcribe (e.g., WAV, MP3). The backend will attempt to process common audio formats.
-   **Success Response (200 OK):**
    -   Content-Type: `application/json`
    -   Body:
        ```json
        {
          "transcription": "This is the transcribed text from the audio.",
          "metadata": {
            "processing_time": 1.234, // seconds
            "language": "en"
            // Other metadata from the STT engine if available
          }
        }
        ```
-   **Error Responses:**
    -   `400 Bad Request`: If no audio file is provided, or the file is empty/corrupt.
        ```json
        {
          "detail": "No audio content provided."
        }
        ```
    -   `401 Unauthorized`: If `X-API-Key` is missing or invalid.
        ```json
        {
          "detail": "Invalid or missing API Key"
        }
        ```
    -   `500 Internal Server Error`: If the STT engine encounters an error during processing.
        ```json
        {
          "detail": "STT engine error: <specific error message>"
        }
        ```
    -   `503 Service Unavailable`: If the transcription service is not initialized.
        ```json
        {
          "detail": "Transcription service not available."
        }
        ```

-   **Example Usage (curl):**
    ```bash
    curl -X POST \
      -H "X-API-Key: development_secret_key" \
      -F "audio_file=@/path/to/your/audio.wav" \
      http://localhost:8000/api/stt
    ```

### 2. Text-to-Speech (TTS)

Converts provided text into synthesized speech audio using the **RealtimeTTS library (defaulting to SystemEngine)**.

-   **URL:** `/api/tts`
-   **Method:** `POST`
-   **Headers:**
    -   `Content-Type: application/json`
    -   `X-API-Key: <your_api_key>` (Currently not enforced for this endpoint)
-   **Request Body (JSON):**
    ```json
    {
      "text": "Hello, this is a test of the text to speech service."
    }
    ```
-   **Success Response (200 OK):**
    -   Content-Type: `audio/wav`
    -   Body: Raw WAV audio bytes.
-   **Error Responses:**
    -   `400 Bad Request`: If the input text is missing or empty.
        ```json
        {
          "detail": "Text for TTS cannot be empty."
        }
        ```
    -   `401 Unauthorized`: If `X-API-Key` were enforced and was missing or invalid.
        ```json
        {
          "detail": "Invalid or missing API Key"
        }
        ```
    -   `500 Internal Server Error`: If the TTS engine fails to produce audio.
        ```json
        {
          "detail": "TTS engine failed to produce audio for the given text."
        }
        ```
        (The exact error message from the server might vary)
    -   `503 Service Unavailable`: If the TTS service is not initialized.
        ```json
        {
          "detail": "TTS service not available."
        }
        ```

-   **Example Usage (curl):**
    ```bash
    curl -X POST \
      -H "Content-Type: application/json" \
      -d '{"text": "Hello world, this is a test."}' \
      --output speech_output.wav \
      http://localhost:8000/api/tts
    ```
    This will save the output WAV audio to `speech_output.wav`.
    (Note: `X-API-Key` header removed from example as it's not currently enforced).
