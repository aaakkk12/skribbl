from datetime import timedelta
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"
DEBUG = env_bool("DEBUG", default=not IS_PRODUCTION)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-insecure-change-me-please-replace"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production.")
if IS_PRODUCTION and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 50 chars in production.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set in production.")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "rest_framework",
    "corsheaders",
    "authapp",
    "realtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "backend.middleware.RequestIDMiddleware",
    "backend.middleware.NoStoreAuthMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.urls"

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
    },
]

WSGI_APPLICATION = "backend.wsgi.application"
ASGI_APPLICATION = "backend.asgi.application"

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
USE_INMEMORY_CHANNEL_LAYER = env_bool("USE_INMEMORY_CHANNEL_LAYER", default=False)
if IS_PRODUCTION and USE_INMEMORY_CHANNEL_LAYER:
    raise ImproperlyConfigured("USE_INMEMORY_CHANNEL_LAYER cannot be True in production.")
if USE_INMEMORY_CHANNEL_LAYER:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
                "capacity": int(os.getenv("CHANNEL_CAPACITY", "1500")),
                "expiry": int(os.getenv("CHANNEL_EXPIRY", "60")),
            },
        }
    }

DATABASE_ENGINE = os.getenv("DB_ENGINE", "sqlite").strip().lower()
if DATABASE_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "app"),
            "USER": os.getenv("DB_USER", "app"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

if IS_PRODUCTION and DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    allow_sqlite = env_bool("ALLOW_SQLITE_IN_PRODUCTION", default=False)
    if not allow_sqlite:
        raise ImproperlyConfigured(
            "SQLite is blocked in production. Set DB_ENGINE=postgres (recommended). "
            "For temporary override use ALLOW_SQLITE_IN_PRODUCTION=True."
        )

USE_REDIS_CACHE = env_bool("USE_REDIS_CACHE", default=IS_PRODUCTION)
if USE_REDIS_CACHE:
    cache_url = os.getenv("CACHE_URL", "redis://127.0.0.1:6379/1")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": cache_url,
            "TIMEOUT": int(os.getenv("CACHE_TIMEOUT_SECONDS", "300")),
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "default",
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.db"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# CORS / CSRF
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
if IS_PRODUCTION and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS must be set in production.")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", ",".join(CORS_ALLOWED_ORIGINS))
CORS_PREFLIGHT_MAX_AGE = 86400
WS_ALLOWED_ORIGINS = env_list("WS_ALLOWED_ORIGINS", ",".join(CORS_ALLOWED_ORIGINS))

# Email (SMTP)
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)

# JWT cookie settings
JWT_COOKIE_SECURE = env_bool("JWT_COOKIE_SECURE", default=IS_PRODUCTION)
JWT_COOKIE_SAMESITE = os.getenv("JWT_COOKIE_SAMESITE", "Lax")
JWT_ACCESS_COOKIE = os.getenv("JWT_ACCESS_COOKIE", "access_token")
JWT_REFRESH_COOKIE = os.getenv("JWT_REFRESH_COOKIE", "refresh_token")
if IS_PRODUCTION and not JWT_COOKIE_SECURE:
    raise ImproperlyConfigured("JWT_COOKIE_SECURE must be True in production.")

# Admin API settings (disabled by default)
ENABLE_ADMIN_API = env_bool("ENABLE_ADMIN_API", default=False)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_COOKIE_NAME = os.getenv("ADMIN_COOKIE_NAME", "admin_token")
ADMIN_TOKEN_MAX_AGE = int(os.getenv("ADMIN_TOKEN_MAX_AGE", "43200"))
if ENABLE_ADMIN_API:
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise ImproperlyConfigured("ADMIN_USERNAME and ADMIN_PASSWORD are required.")
    weak_admin = (
        ADMIN_USERNAME.lower() in {"admin", "root"} and ADMIN_PASSWORD in {"123", "admin", "password"}
    )
    if IS_PRODUCTION and weak_admin:
        raise ImproperlyConfigured("Weak admin credentials are not allowed in production.")

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    ),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "authapp.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON", "60/min"),
        "user": os.getenv("THROTTLE_USER", "300/min"),
        "auth_login": os.getenv("THROTTLE_AUTH_LOGIN", "10/min"),
        "auth_register": os.getenv("THROTTLE_AUTH_REGISTER", "5/min"),
        "auth_password_reset": os.getenv("THROTTLE_AUTH_PASSWORD_RESET", "5/hour"),
        "room_join": os.getenv("THROTTLE_ROOM_JOIN", "30/min"),
        "room_create": os.getenv("THROTTLE_ROOM_CREATE", "10/min"),
        "user_search": os.getenv("THROTTLE_USER_SEARCH", "90/min"),
        "friend_action": os.getenv("THROTTLE_FRIEND_ACTION", "60/min"),
        "room_invite": os.getenv("THROTTLE_ROOM_INVITE", "60/min"),
    },
}

# Security headers / transport
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=IS_PRODUCTION)
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000" if IS_PRODUCTION else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=IS_PRODUCTION)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=IS_PRODUCTION)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=IS_PRODUCTION)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=IS_PRODUCTION)
SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "same-origin")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DEBUG must be False in production.")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}

# Maintenance / data retention
INACTIVE_ACCOUNT_DAYS = int(os.getenv("INACTIVE_ACCOUNT_DAYS", "7"))
INACTIVE_ROOM_RETENTION_DAYS = int(os.getenv("INACTIVE_ROOM_RETENTION_DAYS", "14"))
EMPTY_ROOM_DELETE_MINUTES = int(os.getenv("EMPTY_ROOM_DELETE_MINUTES", "10"))
ROOM_HISTORY_TTL_SECONDS = int(os.getenv("ROOM_HISTORY_TTL_SECONDS", str(60 * 60 * 24 * 7)))
ROOM_STATE_TTL_SECONDS = int(os.getenv("ROOM_STATE_TTL_SECONDS", str(60 * 60 * 24)))
STORAGE_MAX_GB = float(os.getenv("STORAGE_MAX_GB", "20"))
STORAGE_TARGET_GB = float(os.getenv("STORAGE_TARGET_GB", "15"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "7"))
