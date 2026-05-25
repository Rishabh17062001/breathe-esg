# Tradeoffs — Three Things I Deliberately Did Not Build

---

## 1. Async file processing (no Celery / background tasks)

**What I did instead:** File parsing runs synchronously inside the upload HTTP request. The Django view calls the parser, bulk-creates records, and returns the result in a single request-response cycle.

**Why I skipped it:**
- Celery requires a message broker (Redis or RabbitMQ), a worker process, and a results backend. On Render's free tier, that's two extra services and significant configuration complexity.
- For the prototype's file sizes (30–100 rows), synchronous parsing takes under 500ms. The timeout risk is low.
- Adding async without it being needed would complicate the codebase without demonstrating any product judgment — a PM asking "why is there a task queue?" should get a better answer than "best practice."

**What breaks in production:**
- A client with a 50,000-row SAP export would hit the 30-second Gunicorn/Render request timeout before parsing finishes.
- Production fix: Move parsing to a Celery task, return a `batch_id` immediately, poll `/api/v1/batches/<id>/` for status. The `IngestionBatch.status` field is already designed for this pattern.

---

## 2. Authentication and per-user access control

**What I did instead:** The app uses the analyst's name as a plain string (`created_by`, `approved_by`, `actor` fields). There is no login wall; any request can claim any analyst name. Django admin access (`admin/breatheesg2024`) is the only authenticated surface.

**Why I skipped it:**
- JWT or session-based auth requires a login UI, token refresh logic, protected route guards in React, and CSRF handling. That's 2–3 days of work that does not demonstrate anything about data modeling or source handling — the actual evaluation criteria.
- The audit trail fields (`approved_by`, `actor`) are already designed to accept a User FK in production. The string placeholder makes the interface clear without blocking implementation of the rest of the system.
- In a real deployment, an analyst who approves a record should be the authenticated user, not a text field.

**What breaks in production:**
- Any user can approve or lock any record by claiming any name in the request body.
- Any user can see any client's data by changing the `?client=` query parameter.
- Production fix: Add `djangorestframework-simplejwt`, a `Profile` model with client permissions, and per-request client validation against the authenticated user's profile.

---

## 3. Emission factor versioning and a factor management UI

**What I did instead:** Emission factors are hardcoded in the parser files (`parsers/sap.py`, `parsers/utility.py`, `parsers/travel.py`). Updating a factor requires a code change and a redeploy.

**Why I skipped it:**
- A factor management UI (add factor, set effective date, choose source document, trigger recalculation of affected records) is a significant product feature in its own right — not incidental to the ingestion prototype.
- The current design stores `emission_factor`, `emission_factor_source`, and `emission_factor_unit` on every `ActivityRecord`. This is the right schema for production: it means the factor used for each record is always visible, even after the system-wide factor is updated.
- Recalculating `co2e_kg` for thousands of records when a factor changes requires either a background job or a careful migration — both outside the prototype scope.

**What breaks in production:**
- When DEFRA publishes 2024 factors (typically August), an analyst cannot update them without a developer.
- When CEA publishes new state-level grid factors, the same applies.
- Production fix: Add an `EmissionFactor` table with `fuel_type`, `factor`, `unit`, `source`, `effective_from`, `effective_to`. Parsers look up the active factor at ingestion time. A recalculation endpoint re-runs the factor lookup for all records in a batch and logs the change in `AuditLog`.
