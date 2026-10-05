FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
# Бот работает не от root: так безопаснее, если в зависимостях найдётся уязвимость
RUN useradd --create-home --uid 1000 bot && mkdir -p /app/data && chown bot /app/data
USER bot
CMD ["python", "-m", "bot.main"]
