# TriageQ

Hospital OPD triage and queue management backend.

Deterministic ESI-style triage rules, Redis priority queues with aging,
Postgres as the source of truth. An optional LLM module turns free-text
symptoms into structured fields, but triage never depends on it.

> Decision support for hospital staff, not a diagnostic tool.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Then open http://localhost:8000/health and http://localhost:8000/docs.

## Roadmap

- [x] 1. Project skeleton
- [x] 2. Data model + migrations
- [x] 3. Auth (JWT, roles)
- [x] 4. Triage rules engine
- [x] 5. Redis queues with aging
- [ ] 6. Realtime dashboard, overrides, audit log
- [ ] 7. LLM symptom extractor (optional module)
- [ ] 8. Load test, eval, architecture diagram

## Schema (v1)

`users` (roles) · `departments` · `patients` (UHID) · `visits` (status lifecycle) ·
`triage_assessments` (append-only, ESI 1-5, source = rules / llm_assisted / staff_override) ·
`audit_log`. A visit's current priority is its latest assessment, so overrides never
destroy history.

## Migrations & tests

```bash
docker compose exec api alembic upgrade head      # also runs automatically on startup
docker compose exec api alembic revision --autogenerate -m "change"
docker compose exec api pytest -q
```

## Auth

- Staff accounts are created by an admin (`POST /users`); there is no open self-registration.
  The first admin is seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD` on startup.
- Login: `POST /auth/login` (OAuth2 password form) returns a short-lived JWT. Try it in `/docs`.
- Passwords hashed with argon2. Unknown email and wrong password return the same 401.
- The user is re-loaded from the DB on every request, so deactivating an account cuts access
  immediately, and the role comes from the DB, never from the token.
- `require_role(Role.NURSE, Role.DOCTOR)` protects any endpoint.
- Known gaps (planned): login rate limiting / lockout, refresh tokens, MFA.

## Triage engine (`app/triage`)

Pure Python, no DB/web/LLM. Input: age, symptom codes, optional vitals, optional pain score.
Output: ESI level 1-5, department, every rule that fired, red flags, missing info, a plain-language explanation.

- **Most urgent rule wins.** Every matching rule proposes a level; the final level is the minimum.
  So adding information can never make a patient look *less* urgent (property-tested).
- **Safety floors.** No info or an unrecognised symptom caps the result at ESI 3, never 4 or 5.
- **Vitals are optional**, and what was not recorded is listed in `missing_info`.
- Age-aware thresholds (infant vs child vs adult) for danger-zone vitals and hypotension.
- Impossible input (heart rate 900) raises `TriageInputError` instead of being triaged.

> The symptom catalogue and thresholds are an educational ESI-style approximation, not
> clinically validated. Decision support for staff, never a diagnosis.

```bash
python -c "from app.triage import *; print(triage(PatientInput(50, ('chest_pain',))).explanation)"
```

## Queues (`app/queue.py`, `app/visit_service.py`)

Postgres is the source of truth. Redis holds only the ordering, one sorted set per department.

**Aging with no background job.** `score = checked_in_time - head_start[esi]` (lowest score first).
Head starts: ESI 1 / 2 are years (strict, never overtaken), ESI 3 = 120 min, ESI 4 = 60 min, ESI 5 = 0.
So an ESI 4 patient overtakes a fresh ESI 3 after waiting 60 minutes longer. Scores never change over
time, so there is no re-ranking worker and no race with one. An override keeps the original arrival time.

**No double-calling.** `ZPOPMIN` is one atomic Redis command, so two nurses can never get the same visit.
A conditional `UPDATE ... WHERE status='waiting'` guards against stale entries, and if the DB write
fails the patient is put back with the original score.

**Survives Redis loss.** Check-in commits to Postgres first, then enqueues. If Redis is down the visit
is still saved. `reconcile` (run on startup and at `POST /queues/admin/reconcile`) rebuilds Redis from
Postgres: idempotent and safe while live.

**Login brute-force protection.** Redis counters per (email, IP), per IP and per email, so an attacker
cannot lock a victim out of their own account from elsewhere. Fails open if Redis is down.

| Endpoint | Who | What |
|---|---|---|
| `POST /visits/check-in` | nurse, doctor, admin | triage + enqueue |
| `GET /queues/{dept}` | nurse, doctor, admin | live ordered queue |
| `POST /queues/{dept}/call-next` | nurse, doctor | atomically take the next patient (204 if empty) |
| `POST /queues/admin/reconcile` | admin | rebuild Redis from Postgres |

Verified end to end on real Postgres + Redis: 40 simultaneous `call-next` calls on 25 waiting
patients served 25 unique patients with 0 errors; a wiped Redis was rebuilt in the identical order.
Run the tests against real Redis with `REDIS_TEST_URL=redis://localhost:6379/15 pytest`.
