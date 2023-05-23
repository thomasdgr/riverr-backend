# DOCKERFILE TO LAUNCH THE MICRO-SERVICE

# Use an official Python runtime as a parent image
FROM python:3.8

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt /app/requirements.txt

# Upgrade pip if necessary
RUN pip3 install --upgrade pip
RUN pip3 --version

# Install any needed packages specified in requirements.txt
RUN pip3 install --trusted-host pypi.python.org -r /app/requirements.txt

COPY *.py /app/
COPY export-keys.sh /app/

# Copy the script to export the keys to the environment 
RUN chmod +x /app/export-keys.sh

# Make port 3000 available to the world outside this container
EXPOSE 3000

# Export the keys and run main.py when the container launches
CMD CMD /app/export-keys.sh && uvicorn --host 0.0.0.0 --port 3000 main:app