# เลือก base image python version 3.12 slim
FROM python:3.12-slim

# อัพเดต package และติดตั้ง ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# ตั้ง working directory
WORKDIR /app

# คัดลอกไฟล์ requirements.txt และติดตั้ง dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกไฟล์โปรเจคทั้งหมด
COPY . .

# สั่งรัน bot
CMD ["python", "main.py"]
