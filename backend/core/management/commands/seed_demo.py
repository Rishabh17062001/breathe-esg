"""
Seed the database with demo client and sample ingestion batches.
Run: python manage.py seed_demo
"""
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Client, IngestionBatch, ActivityRecord, AuditLog
from core.parsers.sap import parse_sap_csv
from core.parsers.utility import parse_utility_csv
from core.parsers.travel import parse_travel_csv
from django.contrib.auth.models import User


PARSERS = {
    'SAP_FUEL': ('sap_fuel_procurement_sample.csv', parse_sap_csv),
    'UTILITY_ELECTRICITY': ('utility_electricity_sample.csv', parse_utility_csv),
    'TRAVEL': ('concur_travel_sample.csv', parse_travel_csv),
}


class Command(BaseCommand):
    help = 'Seed demo client and sample data'

    def handle(self, *args, **options):
        # Create demo client
        client, created = Client.objects.get_or_create(
            slug='acme-industries',
            defaults={'name': 'Acme Industries Ltd'}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created client: {client.name}'))
        else:
            self.stdout.write(f'Client already exists: {client.name}')

        # Create demo superuser if none exists
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser('admin', 'admin@breatheesg.com', 'breatheesg2024')
            self.stdout.write(self.style.SUCCESS('Created admin user: admin / breatheesg2024'))

        sample_dir = Path(settings.SAMPLE_DATA_DIR)

        for source_type, (filename, parse_fn) in PARSERS.items():
            file_path = sample_dir / filename
            if not file_path.exists():
                self.stdout.write(self.style.WARNING(f'Sample file not found: {file_path}'))
                continue

            if IngestionBatch.objects.filter(client=client, source_type=source_type).exists():
                self.stdout.write(f'  Batch already exists for {source_type} — skipping')
                continue

            file_bytes = file_path.read_bytes()
            import hashlib
            file_hash = hashlib.sha256(file_bytes).hexdigest()

            batch = IngestionBatch.objects.create(
                client=client,
                source_type=source_type,
                filename=filename,
                file_hash=file_hash,
                status='PROCESSING',
                created_by='seed_demo',
            )

            result = parse_fn(file_bytes)

            records_to_create = [
                ActivityRecord(client=client, batch=batch, **rec)
                for rec in result['records']
            ]
            created_records = ActivityRecord.objects.bulk_create(records_to_create)

            for rec in created_records:
                AuditLog.objects.create(
                    record=rec, batch=batch,
                    action='CREATED', actor='seed_demo',
                    new_values={'status': rec.status}
                )

            batch.row_count = result['row_count']
            batch.success_count = len(created_records)
            batch.error_count = len(result['errors'])
            batch.parse_errors = result['errors']
            batch.status = 'COMPLETE' if not result['errors'] else (
                'PARTIAL' if created_records else 'FAILED'
            )
            batch.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f'  {source_type}: {len(created_records)} records, '
                    f'{len(result["errors"])} errors'
                )
            )

        self.stdout.write(self.style.SUCCESS('\nSeed complete. Visit /admin with admin/breatheesg2024'))
