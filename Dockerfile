# Use an official Python runtime as a parent image.
# Using a 'slim' version keeps the final container size smaller.
FROM python:3.11-slim
# Set the working directory inside the container to /app
WORKDIR /app

# Copy the file with the dependencies first.
# This takes advantage of Docker's layer caching. The dependencies
# will only be re-installed if requirements.txt changes.
COPY requirements.txt .

# Install any needed system-level dependencies (if any)
# RUN apt-get update && apt-get install -y some-package

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container at /app
COPY . .

# Make port 5000 available to the world outside this container.
# This is the port your app runs on inside the container.
EXPOSE 5000

# Define the command to run your app.
# We use Gunicorn to run the Flask app instance 'app' found in the 'run.py' file.
# The 'run:app' refers to the 'app' object created by 'create_app()' in your run.py file.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "run:app"]