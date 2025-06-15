# Use a Python 3.11 slim image as the base
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app
COPY templates/ templates/
# Copy the requirements.txt file and install dependencies first.
# This leverages Docker's layer caching: if requirements.txt doesn't change,
# this step won't re-run, speeding up builds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application directory into the container.
# The '.' means copy everything from the current build context (your project root)
# into the WORKDIR (/app) inside the container. This includes 'main.py', 'core/',
# 'templates/', and 'static/'.
COPY . .

# Expose the port FastAPI will run on
EXPOSE 8888

# Command to run the application using uvicorn
# Ensure 'main:app' matches your FastAPI app instance
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8888"]