"""
Django settings for chatbot_poc.

This file reads configuration from environment variables. For local development you can
create a `.env` file at the project root (see .env.example) and optionally use python-dotenv
to load it automatically (this file will attempt to load it if python-dotenv is installed).

Sensitive keys (SECRET_KEY, OPENAI_API_KEY, etc.) should be provided via environment variables
in production (e.g., via your cloud provider's secrets manager).
"""

import os
from pathlib import Path

# Optionally load environment from a .env file if python-dotenv is available.
# This is convenient during development. In production prefer real environment variables.
try:
    from dotenv import load_dotenv  # type: ignore
    _here = Path(__file__).resolve().parent.parent
    env_path = _here / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path))
except Exception:
    # python-dotenv is optional; ignore if not installed.
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Basic security & debug
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "replace-me-for-dev")
DEBUG = os.environ.get("DEBUG", "True").lower() in ("1", "true", "yes")

# ALLOWED_HOSTS as comma-separated env var
_AL = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _AL.split(",") if h.strip()]

# Application definition
INSTALLED_APPS = [
    # Django contrib
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    # Note: If you want CORS support, install django-cors-headers and uncomment:
    # "corsheaders",

    # Local apps - using AppConfig references
    "chatbot_poc.apps.core.apps.CoreConfig",
    "chatbot_poc.apps.ingest.apps.IngestConfig",
    "chatbot_poc.apps.retrieval.apps.RetrievalConfig",
    "chatbot_poc.apps.api.apps.ApiConfig",
]

MIDDLEWARE = [
    # If using corsheaders, insert "corsheaders.middleware.CorsMiddleware" near the top
    # "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "chatbot_poc.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "chatbot_poc.wsgi.application"
ASGI_APPLICATION = "chatbot_poc.asgi.application"

# Database (sqlite default for skeleton)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Password validation (defaults)
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# Static & media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# REST Framework simple config
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

# CORS configuration (optional)
# If you install django-cors-headers, you can enable permissive CORS for testing:
# CORS_ALLOW_ALL_ORIGINS = True
# Or restrict with:
# CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# Haystack / vector-store related settings (read from env with sensible defaults)
ELASTICSEARCH_HOST = os.environ.get("ELASTICSEARCH_HOST", "localhost")
ELASTICSEARCH_PORT = int(os.environ.get("ELASTICSEARCH_PORT", 9200))
HAYSTACK_INDEX = os.environ.get("HAYSTACK_INDEX", "haystack_document_index")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# Optional: OpenAI API key (if using OpenAI for generation)
# Set OPENAI_API_KEY in the environment (or in your .env for local development).
# Example in .env:
#   OPENAI_API_KEY=sk-...
# The llm_client will check os.environ.get("OPENAI_API_KEY").
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Logging - simple console logging at INFO level
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        # reduce verbosity from some noisy modules if desired
        "urllib3": {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
}