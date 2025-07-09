# Use an official PyTorch image with CUDA and Python 3.10 support
FROM pytorch/pytorch:2.1.2-cuda11.8-cudnn8-runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES compute,utility

# System dependencies for Ubuntu base (pytorch image is Ubuntu based)
# espeak-ng and libespeak-ng1 are for pyttsx3
# ffmpeg is generally useful for audio/video operations
# git is good to have for some pip installs, though not strictly needed by current reqs
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY backend/requirements.txt /app/backend/requirements.txt

# Install any needed packages specified in requirements.txt
# The PyTorch image already has torch and torchaudio, but pip will handle versions if different.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy the backend application code into the container at /app/backend
COPY backend/ /app/backend/

# Copy the prompts directory into the container at /app/prompts
COPY prompts/ /app/prompts/

# Expose port 8000 to the outside world
EXPOSE 8000

# Define the command to run the application
# This runs the main application module located at /app/backend/main.py
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
