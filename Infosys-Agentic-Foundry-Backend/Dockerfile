# --- STAGE 1: The Builder ---
# This stage installs dependencies in a clean environment.
#FROM python:3.12-slim
FROM infyartifactory.jfrog.io/infyagenticrepo/python:3.12-slim

# Set the working directory
WORKDIR /app

RUN apt-get update && apt-get install -y git=1:2.39.5-0+deb12u2 \
    && rm -rf /var/lib/apt/lists/*

# Install uv, our fast package installer
RUN pip install uv==0.6.14

# Copy only the requirements file to leverage Docker's layer caching.
# If this file doesn't change, Docker won't reinstall everything on every build.
COPY requirements.txt .

# Install the Python dependencies into a specific directory within the image.
# We use --system to install them into the standard site-packages.
RUN uv pip install --no-cache --system -r requirements.txt

# Create a non-root user to avoid running the container as root
RUN useradd --no-create-home --shell /bin/false appuser


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

# Transfer ownership to non-root user and switch to it
RUN chown -R appuser:appuser /app
USER appuser

# Expose the port that your application will run on.
EXPOSE 8000

# Define the command to run your application.
# --reload is removed as it's for development, not production containers.
# --host 0.0.0.0 is CRITICAL to allow the container to accept connections from outside.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]