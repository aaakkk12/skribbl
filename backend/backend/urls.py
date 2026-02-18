from django.conf import settings
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("authapp.urls")),
    path("api/rooms/", include("realtime.urls")),
]

if settings.ENABLE_ADMIN_API:
    urlpatterns.append(path("api/admin/", include("authapp.admin_urls")))



