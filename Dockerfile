FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY demo_full_pipeline.py demo_real_documents.py ./
COPY data ./data

ENTRYPOINT ["python"]
CMD ["demo_full_pipeline.py"]
