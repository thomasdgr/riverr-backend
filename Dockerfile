# DOCKERFILE TO LAUNCH THE MICRO-SERVICE

FROM python:3.8

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip3 install --upgrade pip
RUN pip3 --version
RUN pip3 install --trusted-host pypi.python.org -r /app/requirements.txt

COPY *.py /app/
COPY export-keys.sh /app/

RUN chmod +x /app/export-keys.sh

EXPOSE 3000

CMD CMD /app/export-keys.sh && uvicorn --host 0.0.0.0 --port 3000 main:app