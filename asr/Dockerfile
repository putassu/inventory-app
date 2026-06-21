# Официальный образ PyTorch с CUDA и cuDNN
FROM pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

# Избегаем интерактивных диалогов при установке пакетов
ENV DEBIAN_FRONTEND=noninteractive

# Устанавливаем системные зависимости для работы с аудио (замена conda install ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Кэшируем слои с питоновскими пакетами
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем скрипт GigaAM
COPY app.py .

EXPOSE 8007

# Запуск Uvicorn внутри контейнера
CMD ["python", "app.py"]