import hashlib
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination

from .models import Client, IngestionBatch, ActivityRecord, AuditLog
from .serializers import (
    ClientSerializer, BatchSerializer,
    ActivityRecordListSerializer, ActivityRecordDetailSerializer,
    DashboardStatsSerializer,
)
from .parsers.sap import parse_sap_csv
from .parsers.utility import parse_utility_csv
from .parsers.travel import parse_travel_csv


def get_or_default_client(request) -> Client:
    client_id = request.query_params.get('client_id') or request.data.get('client_id')
    if client_id:
        return Client.objects.get(id=client_id)
    return Client.objects.first()


class ClientListView(APIView):
    def get(self, request):
        clients = Client.objects.all()
        return Response(ClientSerializer(clients, many=True).data)


class DashboardView(APIView):
    def get(self, request):
        client = get_or_default_client(request)
        if not client:
            return Response({'error': 'No client found. Run seed_demo first.'}, status=400)

        qs = ActivityRecord.objects.filter(client=client)

        def safe_sum(queryset, field):
            result = queryset.aggregate(total=Sum(field))['total']
            return float(result) / 1000 if result else 0.0

        scope1 = safe_sum(qs.filter(scope='1'), 'co2e_kg')
        scope2 = safe_sum(qs.filter(scope='2'), 'co2e_kg')
        scope3 = safe_sum(qs.filter(scope='3'), 'co2e_kg')

        scope_breakdown = [
            {'scope': '1', 'label': 'Scope 1 — Direct', 'co2e_tonnes': scope1,
             'count': qs.filter(scope='1').count()},
            {'scope': '2', 'label': 'Scope 2 — Electricity', 'co2e_tonnes': scope2,
             'count': qs.filter(scope='2').count()},
            {'scope': '3', 'label': 'Scope 3 — Value Chain', 'co2e_tonnes': scope3,
             'count': qs.filter(scope='3').count()},
        ]

        source_breakdown = []
        for st, label in ActivityRecord.SOURCE_TYPES:
            st_qs = qs.filter(source_type=st)
            co2e = safe_sum(st_qs, 'co2e_kg')
            if st_qs.exists():
                source_breakdown.append({'source_type': st, 'label': label,
                                          'co2e_tonnes': co2e, 'count': st_qs.count()})

        recent_batches = IngestionBatch.objects.filter(client=client)[:5]

        data = {
            'total_records': qs.count(),
            'pending_count': qs.filter(status='PENDING').count(),
            'approved_count': qs.filter(status='APPROVED').count(),
            'flagged_count': qs.filter(status='FLAGGED').count(),
            'rejected_count': qs.filter(status='REJECTED').count(),
            'scope1_co2e_tonnes': scope1,
            'scope2_co2e_tonnes': scope2,
            'scope3_co2e_tonnes': scope3,
            'total_co2e_tonnes': scope1 + scope2 + scope3,
            'recent_batches': BatchSerializer(recent_batches, many=True).data,
            'scope_breakdown': scope_breakdown,
            'source_breakdown': source_breakdown,
        }
        return Response(data)


class IngestView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    SOURCE_PARSERS = {
        'SAP_FUEL': parse_sap_csv,
        'UTILITY_ELECTRICITY': parse_utility_csv,
        'TRAVEL': parse_travel_csv,
    }

    def post(self, request, source_type):
        source_type = source_type.upper()
        if source_type not in self.SOURCE_PARSERS:
            return Response({'error': f'Unknown source type: {source_type}'}, status=400)

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=400)

        client = get_or_default_client(request)
        if not client:
            return Response({'error': 'No client found. Run seed_demo first.'}, status=400)

        created_by = request.data.get('created_by', 'analyst')
        file_bytes = file_obj.read()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        # Duplicate upload detection
        existing = IngestionBatch.objects.filter(client=client, file_hash=file_hash).first()
        if existing:
            return Response({
                'warning': 'This exact file was already uploaded.',
                'existing_batch': BatchSerializer(existing).data,
            }, status=200)

        batch = IngestionBatch.objects.create(
            client=client,
            source_type=source_type,
            filename=file_obj.name,
            file_hash=file_hash,
            status='PROCESSING',
            created_by=created_by,
        )

        AuditLog.objects.create(
            batch=batch, action='BATCH_UPLOADED', actor=created_by,
            new_values={'filename': file_obj.name, 'source_type': source_type}
        )

        try:
            parse_fn = self.SOURCE_PARSERS[source_type]
            result = parse_fn(file_bytes)
        except Exception as e:
            batch.status = 'FAILED'
            batch.parse_errors = [{'error': str(e)}]
            batch.save()
            AuditLog.objects.create(batch=batch, action='BATCH_FAILED', actor='system',
                                     new_values={'error': str(e)})
            return Response({'error': f'Parse failed: {e}'}, status=500)

        records_to_create = []
        for rec in result['records']:
            records_to_create.append(ActivityRecord(
                client=client,
                batch=batch,
                **rec,
            ))

        created = ActivityRecord.objects.bulk_create(records_to_create)

        for rec_obj in created:
            AuditLog.objects.create(
                record=rec_obj, batch=batch,
                action='CREATED', actor='system',
                new_values={'status': rec_obj.status, 'source_type': rec_obj.source_type}
            )

        batch.row_count = result['row_count']
        batch.success_count = len(created)
        batch.error_count = len(result['errors'])
        batch.parse_errors = result['errors']
        batch.status = 'COMPLETE' if not result['errors'] else (
            'PARTIAL' if created else 'FAILED'
        )
        batch.save()

        return Response({
            'batch': BatchSerializer(batch).data,
            'records_created': len(created),
            'errors': result['errors'],
        }, status=201)


class RecordPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class ActivityRecordListView(APIView):
    pagination_class = RecordPagination

    def get(self, request):
        client = get_or_default_client(request)
        if not client:
            return Response({'results': [], 'count': 0})

        qs = ActivityRecord.objects.filter(client=client).select_related('batch')

        # Filters
        scope = request.query_params.get('scope')
        source_type = request.query_params.get('source_type')
        rec_status = request.query_params.get('status')
        search = request.query_params.get('search')
        batch_id = request.query_params.get('batch_id')

        if scope:
            qs = qs.filter(scope=scope)
        if source_type:
            qs = qs.filter(source_type=source_type)
        if rec_status:
            qs = qs.filter(status=rec_status)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        if search:
            qs = qs.filter(
                Q(description__icontains=search) |
                Q(vendor_supplier__icontains=search) |
                Q(location_label__icontains=search) |
                Q(source_record_id__icontains=search)
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = ActivityRecordListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ActivityRecordDetailView(APIView):
    def get(self, request, pk):
        try:
            record = ActivityRecord.objects.get(id=pk)
        except ActivityRecord.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)
        return Response(ActivityRecordDetailSerializer(record).data)

    def patch(self, request, pk):
        try:
            record = ActivityRecord.objects.get(id=pk)
        except ActivityRecord.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

        if record.locked_at:
            return Response({'error': 'Record is locked for audit and cannot be modified'}, status=403)

        actor = request.data.get('actor', 'analyst')
        action = request.data.get('action')

        if action == 'approve':
            record.approve(actor)
        elif action == 'flag':
            reason = request.data.get('reason', '')
            record.flag(actor, reason)
        elif action == 'reject':
            reason = request.data.get('reason', '')
            record.reject(actor, reason)
        elif action == 'lock':
            if record.status != 'APPROVED':
                return Response({'error': 'Only approved records can be locked'}, status=400)
            record.lock(actor)
        else:
            return Response({'error': f'Unknown action: {action}'}, status=400)

        return Response(ActivityRecordDetailSerializer(record).data)


class BulkActionView(APIView):
    parser_classes = [JSONParser]

    def post(self, request):
        ids = request.data.get('ids', [])
        action = request.data.get('action')
        actor = request.data.get('actor', 'analyst')
        reason = request.data.get('reason', '')

        if not ids or not action:
            return Response({'error': 'ids and action are required'}, status=400)

        records = ActivityRecord.objects.filter(id__in=ids, locked_at__isnull=True)
        updated = 0

        for record in records:
            if action == 'approve':
                record.approve(actor)
            elif action == 'flag':
                record.flag(actor, reason)
            elif action == 'reject':
                record.reject(actor, reason)
            updated += 1

        return Response({'updated': updated})


class BatchListView(APIView):
    def get(self, request):
        client = get_or_default_client(request)
        if not client:
            return Response([])
        batches = IngestionBatch.objects.filter(client=client)
        return Response(BatchSerializer(batches, many=True).data)


class BatchDetailView(APIView):
    def get(self, request, pk):
        try:
            batch = IngestionBatch.objects.get(id=pk)
        except IngestionBatch.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)
        data = BatchSerializer(batch).data
        data['record_stats'] = {
            'PENDING': batch.records.filter(status='PENDING').count(),
            'APPROVED': batch.records.filter(status='APPROVED').count(),
            'FLAGGED': batch.records.filter(status='FLAGGED').count(),
            'REJECTED': batch.records.filter(status='REJECTED').count(),
        }
        return Response(data)
