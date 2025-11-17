# --- STAGE 1: The Builder ---
# This stage installs dependencies in a clean environment.
FROM python:3.11-slim as builder
 
# Set the working directory
WORKDIR /app
 
# Install uv, our fast package installer
RUN pip install uv
 
# Copy only the requirements file to leverage Docker's layer caching.
# If this file doesn't change, Docker won't reinstall everything on every build.
COPY requirements.txt .
 
# Install the Python dependencies into a specific directory within the image.
# We use --system to install them into the standard site-packages.
RUN uv pip install --no-cache --system -r requirements.txt
 
 
# --- STAGE 2: The Final Production Image ---
# This stage creates the small, final image that will be deployed.
#FROM python:3.11-slim
 
# Create a non-root user for better security.
#RUN useradd --create-home appuser
#WORKDIR /home/appuser/app
#USER appuser
 
# Copy the installed dependencies from the builder stage.
# This copies the entire site-packages directory into the final image.
#COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
 
# Copy your backend application code.
COPY . .
 
# Expose the port that your application will run on.
EXPOSE 8000
 
# Define the command to run your application.
# --reload is removed as it's for development, not production containers.
# --host 0.0.0.0 is CRITICAL to allow the container to accept connections from outside.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
 