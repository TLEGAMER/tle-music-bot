FROM python:3.11-slim

# ติดตั้ง ffmpeg และ dependencies
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# ติดตั้งไลบรารี Python
COPY requirements.txt .
RUN pip install -r requirements.txt

# คัดลอกโค้ดบอท
COPY . .

# รันบอท
CMD ["python", "main.py"]
