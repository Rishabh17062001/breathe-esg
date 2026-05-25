from rest_framework import serializers
from .models import Client, IngestionBatch, ActivityRecord, AuditLog


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['id', 'name', 'slug', 'created_at']


class BatchSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)

    class Meta:
        model = IngestionBatch
        fields = [
            'id', 'client', 'source_type', 'source_type_display',
            'filename', 'row_count', 'success_count', 'error_count',
            'parse_errors', 'status', 'created_at', 'created_by',
        ]
        read_only_fields = fields


class ActivityRecordListSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    scope_display = serializers.CharField(source='get_scope_display', read_only=True)
    co2e_tonnes = serializers.SerializerMethodField()
    batch_filename = serializers.CharField(source='batch.filename', read_only=True)

    class Meta:
        model = ActivityRecord
        fields = [
            'id', 'source_type', 'source_type_display', 'scope', 'scope_display',
            'category', 'activity_date', 'period_start', 'period_end',
            'raw_quantity', 'raw_unit', 'quantity_normalized', 'unit_normalized',
            'description', 'vendor_supplier', 'location_label',
            'emission_factor', 'emission_factor_source', 'emission_factor_unit',
            'co2e_kg', 'co2e_tonnes',
            'status', 'status_display', 'flag_reason', 'confidence_score', 'auto_flagged',
            'is_edited', 'approved_by', 'approved_at', 'locked_at',
            'created_at', 'updated_at', 'batch_filename',
        ]

    def get_co2e_tonnes(self, obj):
        if obj.co2e_kg is None:
            return None
        return float(obj.co2e_kg) / 1000


class ActivityRecordDetailSerializer(ActivityRecordListSerializer):
    audit_logs = serializers.SerializerMethodField()

    class Meta(ActivityRecordListSerializer.Meta):
        fields = ActivityRecordListSerializer.Meta.fields + ['raw_data', 'source_record_id', 'audit_logs']

    def get_audit_logs(self, obj):
        logs = obj.audit_logs.order_by('-timestamp')[:20]
        return AuditLogSerializer(logs, many=True).data


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['id', 'action', 'actor', 'timestamp', 'old_values', 'new_values', 'note']


class DashboardStatsSerializer(serializers.Serializer):
    total_records = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    approved_count = serializers.IntegerField()
    flagged_count = serializers.IntegerField()
    rejected_count = serializers.IntegerField()
    scope1_co2e_tonnes = serializers.FloatField()
    scope2_co2e_tonnes = serializers.FloatField()
    scope3_co2e_tonnes = serializers.FloatField()
    total_co2e_tonnes = serializers.FloatField()
    recent_batches = BatchSerializer(many=True)
    scope_breakdown = serializers.ListField()
    source_breakdown = serializers.ListField()
