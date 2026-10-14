FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY obeval/ obeval/
COPY prompt/ prompt/
# Chạy không phải root. obeval chỉ ghi vào thư mục tạm (service.py dùng TemporaryDirectory), không ghi vào /app;
# file trong /app thuộc root nhưng ai cũng đọc được (644/755 mặc định của COPY).
RUN useradd -m -u 10001 app
USER app
# Kịch bản PDC KHÔNG nằm trong image: Secret Manager mount vào OBEVAL_SCRIPT lúc chạy.
CMD exec uvicorn obeval.app:app --host 0.0.0.0 --port ${PORT:-8080}
