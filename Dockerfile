FROM python:3.12-slim
WORKDIR /app
COPY hk_card_promo /app
RUN pip install --no-cache-dir -r requirements.txt
# 数据目录可挂载卷：docker run -v hkp-data:/app/data
CMD ["python", "main.py"]
