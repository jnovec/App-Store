FROM python:3.12-alpine
RUN apk add --no-cache git wget
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY server.py .
COPY template_catalog.py .
COPY static ./static
RUN mkdir -p /data
EXPOSE 8788
CMD ["uvicorn","server:api","--host","0.0.0.0","--port","8788"]
