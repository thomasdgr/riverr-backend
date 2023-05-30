# Riverr - Backend 

Backend for Riverr.

## Description of the project

Authors:
- Thomas Dagier
- Antoine Blancy
- Dorian Bernasconi

We used uvicorn and fastapi for the development of the backend. You may use an own
Python virtual environment installing the python modules from `/requirements.txt`.

- Tools should work with python3.They were used with **python 3.7**, **python 3.8** and **python 3.9**.
- Clone the repository, create virtualenv, activate the virtual env, install required packages and test.

```sh
  python3.8 -m venv venv
  source ./venv/bin/activate
  pip install --upgrade pip
  pip3 install --trusted-host pypi.python.org -r requirements.txt
  uvicorn main:app --reload --port 3000
```
The OpenAPI specifications are available under the route `/specification` and the Swagger interface to test the API under the route `/docs`.

### Note for the API Keys

In order to use the API, you need to have several valid API keys. Use your own or ask for the script `export-keys.sh` to get the keys we used for our specific implementation.

## Build and run the project with docker

- Build the docker image:

```sh
  docker build -t riverr-backend .
```

- Run the docker image:

```sh
  docker run -d -p 3000:3000 riverr-backend
```