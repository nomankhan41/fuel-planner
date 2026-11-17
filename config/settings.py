"""Django settings for the Fuel Planner API."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "stations",
    "routing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---------------------------------------------------------------------------
# Cache
#
# Trip responses and the map page both read from this cache; a request that
# comes in on one gunicorn worker may need to be served by another, so we need
# a cache that is shared between processes. FileBasedCache on disk works out of
# the box with any number of workers and survives restarts; Redis is used when
# a REDIS_URL is supplied for production scale.
_CACHE_DIR = BASE_DIR / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)
if os.getenv("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache",
                          "LOCATION": os.getenv("REDIS_URL")}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                          "LOCATION": str(_CACHE_DIR), "TIMEOUT": 86400,
                          "OPTIONS": {"MAX_ENTRIES": 10000}}}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

# ---------------------------------------------------------------------------
# Fuel planner / external APIs
ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "ors" if os.getenv("ORS_API_KEY") else "osrm")
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_URL = os.getenv("ORS_URL", "https://api.openrouteservice.org/v2/directions/driving-car/geojson")
ORS_GEOCODE_URL = os.getenv("ORS_GEOCODE_URL", "https://api.openrouteservice.org/geocode/search")
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org/route/v1/driving")
ROUTING_TIMEOUT_SECONDS = float(os.getenv("ROUTING_TIMEOUT_SECONDS", "20"))

CENSUS_BATCH_URL = os.getenv(
    "CENSUS_BATCH_URL",
    "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
)
CENSUS_TIMEOUT_SECONDS = float(os.getenv("CENSUS_TIMEOUT_SECONDS", "300"))

FUEL_PLANNER = {
    "MAX_RANGE_MILES": float(os.getenv("MAX_RANGE_MILES", "500")),
    "MPG": float(os.getenv("MPG", "10")),
    "CORRIDOR_MILES": float(os.getenv("CORRIDOR_MILES", "10")),
    # Per-stop "hassle" cost used only when choosing stops (not added to the fuel bill).
    "STOP_PENALTY_USD": float(os.getenv("STOP_PENALTY_USD", "5")),
    "CACHE_SECONDS": int(os.getenv("CACHE_SECONDS", str(24 * 3600))),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {"fuel_planner": {"handlers": ["console"], "level": "INFO"}},
}
