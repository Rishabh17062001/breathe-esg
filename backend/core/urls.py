from django.urls import path
from . import views

urlpatterns = [
    path('clients/', views.ClientListView.as_view()),
    path('dashboard/', views.DashboardView.as_view()),
    path('ingest/<str:source_type>/', views.IngestView.as_view()),
    path('records/', views.ActivityRecordListView.as_view()),
    path('records/<uuid:pk>/', views.ActivityRecordDetailView.as_view()),
    path('records/bulk/', views.BulkActionView.as_view()),
    path('batches/', views.BatchListView.as_view()),
    path('batches/<uuid:pk>/', views.BatchDetailView.as_view()),
]
