from django.contrib import admin
from .models import Client, IngestionBatch, ActivityRecord, AuditLog


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'created_at']


@admin.register(IngestionBatch)
class IngestionBatchAdmin(admin.ModelAdmin):
    list_display = ['filename', 'source_type', 'status', 'row_count', 'success_count', 'error_count', 'created_at']
    list_filter = ['source_type', 'status']
    readonly_fields = ['file_hash', 'parse_errors']


@admin.register(ActivityRecord)
class ActivityRecordAdmin(admin.ModelAdmin):
    list_display = ['source_type', 'scope', 'activity_date', 'quantity_normalized',
                    'unit_normalized', 'co2e_kg', 'status', 'confidence_score']
    list_filter = ['source_type', 'scope', 'status', 'auto_flagged']
    search_fields = ['description', 'vendor_supplier', 'source_record_id']
    readonly_fields = ['raw_data', 'created_at', 'updated_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'actor', 'timestamp']
    list_filter = ['action']
    readonly_fields = ['id', 'record', 'batch', 'action', 'actor', 'timestamp', 'old_values', 'new_values']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
