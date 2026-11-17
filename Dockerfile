FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Build the station table + geocode at image build time so a container starts ready.
# `--no-census` uses the city-centroid fallback for all stations so the build is
# offline-safe. After the container is running, `python manage.py geocode_stations`
# (its default --retry-fallback is on) will re-send those city-centroid stations
# to the US Census batch geocoder and upgrade the ones it can match to real
# street-level coordinates. Non-matches keep their existing centroid.
RUN python manage.py migrate --noinput \
 && python manage.py load_stations \
 && python manage.py geocode_stations --no-census

EXPOSE 8000
# One worker + several threads keeps the file-based trip cache internally consistent;
# scale horizontally by giving the stack REDIS_URL and raising --workers.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "1", "--threads", "4"]
