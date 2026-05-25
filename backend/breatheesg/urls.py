from django.contrib import admin
from django.urls import path, include, re_path
from django.http import FileResponse, HttpResponse
from django.conf import settings
from django.conf.urls.static import static
import os

def serve_react(request, *args, **kwargs):
    index_path = os.path.join(settings.BASE_DIR, 'static', 'index.html')
    if os.path.exists(index_path):
        with open(index_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='text/html')
    return HttpResponse('<h1>BreatheESG API running. Frontend not built yet.</h1>')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('core.urls')),
    re_path(r'^(?!api|admin|static|media).*$', serve_react),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
