import uuid
from django.db import models
from django.utils import timezone


class Client(models.Model):
    """
    Top-level tenant. Every record, batch, and log belongs to exactly one Client.
    Isolation is enforced at the queryset level in every view — no cross-client
    data is ever returned in a single API call.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class IngestionBatch(models.Model):
    """
    One batch = one file upload. Stores provenance: who uploaded what, when,
    from which system, and how well it parsed. The raw_file field preserves
    the original bytes so we can always re-parse if the logic changes.

    file_hash (SHA-256) enables duplicate-upload detection before we commit
    any ActivityRecords to the database.
    """
    SOURCE_TYPES = [
        ('SAP_FUEL', 'SAP Fuel & Procurement'),
        ('UTILITY_ELECTRICITY', 'Utility Electricity'),
        ('TRAVEL', 'Corporate Travel'),
    ]
    STATUS_CHOICES = [
        ('PROCESSING', 'Processing'),
        ('COMPLETE', 'Complete'),
        ('PARTIAL', 'Partial — some rows failed'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='batches')
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES)
    filename = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64)
    raw_file = models.FileField(upload_to='raw_uploads/%Y/%m/', null=True, blank=True)

    row_count = models.IntegerField(default=0)
    success_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    parse_errors = models.JSONField(default=list)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PROCESSING')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=255, default='analyst')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source_type} — {self.filename} ({self.created_at.date()})'


class ActivityRecord(models.Model):
    """
    The canonical normalized record. One row = one discrete activity that
    contributes to a GHG inventory.

    Design principles:
    - raw_* fields preserve exactly what the source said (unit, quantity, ID).
      They never change after creation.
    - quantity_normalized / unit_normalized are the analyst-facing values in
      a canonical unit per category (liters for liquid fuels, kWh for electricity,
      km for travel distances, nights for hotels).
    - co2e_kg is computed from quantity_normalized × emission_factor at parse
      time using the best available factor. Analysts can see which factor was
      used and its provenance.
    - is_edited tracks whether any field was changed after initial parse, which
      triggers a recalculation and an AuditLog entry.
    - locked_at is set when the record is approved for audit export; locked
      records become read-only.
    """

    SOURCE_TYPES = [
        ('SAP_FUEL', 'SAP — Fuel Combustion'),
        ('SAP_PROCUREMENT', 'SAP — Procurement (non-fuel)'),
        ('UTILITY_ELECTRICITY', 'Utility — Electricity'),
        ('TRAVEL_AIR', 'Travel — Air'),
        ('TRAVEL_HOTEL', 'Travel — Hotel'),
        ('TRAVEL_GROUND', 'Travel — Ground Transport'),
        ('TRAVEL_RAIL', 'Travel — Rail'),
    ]
    SCOPE_CHOICES = [
        ('1', 'Scope 1 — Direct'),
        ('2', 'Scope 2 — Indirect Energy'),
        ('3', 'Scope 3 — Value Chain'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('FLAGGED', 'Flagged — Needs Attention'),
        ('REJECTED', 'Rejected'),
        ('LOCKED', 'Locked for Audit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='records')
    batch = models.ForeignKey(IngestionBatch, on_delete=models.PROTECT, related_name='records')

    # --- GHG classification ---
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES)
    scope = models.CharField(max_length=1, choices=SCOPE_CHOICES)
    # GHG Protocol category name, e.g. 'mobile_combustion', 'purchased_electricity',
    # 'business_travel_air', 'business_travel_hotel'
    category = models.CharField(max_length=100)

    # --- Temporal ---
    activity_date = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    # --- Raw source values (immutable after create) ---
    raw_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    raw_unit = models.CharField(max_length=50)
    raw_location = models.CharField(max_length=255, blank=True)
    source_record_id = models.CharField(max_length=255, blank=True, db_index=True)
    raw_data = models.JSONField()

    # --- Normalized values ---
    quantity_normalized = models.DecimalField(max_digits=20, decimal_places=6)
    unit_normalized = models.CharField(max_length=20)

    # --- Descriptive metadata ---
    description = models.CharField(max_length=500, blank=True)
    vendor_supplier = models.CharField(max_length=255, blank=True)
    location_label = models.CharField(max_length=255, blank=True)

    # --- Emission calculation ---
    emission_factor = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    emission_factor_source = models.CharField(max_length=100, blank=True)
    emission_factor_unit = models.CharField(max_length=50, blank=True)
    co2e_kg = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)

    # --- Review workflow ---
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    flag_reason = models.TextField(blank=True)
    confidence_score = models.FloatField(default=1.0)
    auto_flagged = models.BooleanField(default=False)

    # --- Audit trail ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)
    approved_by = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-activity_date', '-created_at']
        indexes = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['client', 'scope']),
            models.Index(fields=['client', 'source_type']),
            models.Index(fields=['batch', 'status']),
        ]

    def __str__(self):
        return f'{self.source_type} | {self.activity_date} | {self.quantity_normalized} {self.unit_normalized}'

    def approve(self, by: str):
        self.status = 'APPROVED'
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save()
        AuditLog.objects.create(
            record=self, action='APPROVED', actor=by,
            new_values={'status': 'APPROVED', 'approved_by': by}
        )

    def flag(self, by: str, reason: str):
        self.status = 'FLAGGED'
        self.flag_reason = reason
        self.save()
        AuditLog.objects.create(
            record=self, action='FLAGGED', actor=by,
            new_values={'status': 'FLAGGED', 'flag_reason': reason}
        )

    def reject(self, by: str, reason: str = ''):
        self.status = 'REJECTED'
        self.flag_reason = reason
        self.save()
        AuditLog.objects.create(
            record=self, action='REJECTED', actor=by,
            new_values={'status': 'REJECTED', 'flag_reason': reason}
        )

    def lock(self, by: str):
        self.status = 'LOCKED'
        self.locked_at = timezone.now()
        self.save()
        AuditLog.objects.create(
            record=self, action='LOCKED', actor=by,
            new_values={'status': 'LOCKED', 'locked_at': str(self.locked_at)}
        )


class AuditLog(models.Model):
    """
    Append-only log of every state change to an ActivityRecord or batch.
    Never update or delete rows in this table — it is the source of truth
    for the audit trail that goes to external verifiers.
    """
    ACTIONS = [
        ('CREATED', 'Record Created'),
        ('EDITED', 'Record Edited'),
        ('APPROVED', 'Approved'),
        ('FLAGGED', 'Flagged'),
        ('REJECTED', 'Rejected'),
        ('LOCKED', 'Locked for Audit'),
        ('BATCH_UPLOADED', 'Batch Uploaded'),
        ('BATCH_FAILED', 'Batch Parse Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(
        ActivityRecord, on_delete=models.CASCADE,
        related_name='audit_logs', null=True, blank=True
    )
    batch = models.ForeignKey(
        IngestionBatch, on_delete=models.CASCADE,
        related_name='audit_logs', null=True, blank=True
    )
    action = models.CharField(max_length=30, choices=ACTIONS)
    actor = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.action} by {self.actor} at {self.timestamp}'
