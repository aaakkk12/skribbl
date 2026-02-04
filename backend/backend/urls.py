from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("authapp.urls")),
    path("api/admin/", include("authapp.admin_urls")),
    path("api/rooms/", include("realtime.urls")),
]



