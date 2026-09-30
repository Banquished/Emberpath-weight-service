# Emberpath Weight Service

FastAPI-tjeneste for daglige vektlogger, med PostgreSQL, SQLAlchemy og Alembic.
Én registrering per bruker og dato. Vekten lagres som `NUMERIC(6, 2)` og må være positiv,
maks 9999,99 kg, med inntil to desimaler. API-et returnerer vekten som JSON-tall.

## Installasjon

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.13 eller nyere kreves; uv henter Python ved behov.

```powershell
cd C:\Workspace\Repos\Emberpath-weight-service
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Behold en eksisterende `.env`; fyll inn `DATABASE_URL` og Clerk-innstillingene
i en ny kopi før lokal oppstart. Tjenestens `.env` brukes kun ved lokal kjøring
fra dette repoet og ignoreres av Git. Compose leser bare hubrepoets
`../Emberpath/.env`, ikke denne filen. Miljøvariabler overstyrer verdiene i
filen. `DATABASE_URL` brukes av appen og Alembic. Sett
`TEST_DATABASE_URL` kun som miljøvariabel i terminalen, aldri i `.env`: ukjente
konfigurasjonsnøkler avvises. Testene leser ikke den lokale `.env`-filen. `uv.lock` låser avhengighetsversjonene.

## Kjør hele appen i Docker

Docker Compose ligger i søsterrepoet `Emberpath`. Repoene må ligge
ved siden av hverandre. Dockerfilene ligger i tjenesterepoene.

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose up --build -d --wait
```

Compose starter begge PostgreSQL-databasene, kjører tjenestenes migreringer,
og starter API-ene og web etter vellykket migrering. Standardporter er web `5173`,
vekt-API `8000`, vekt-PostgreSQL `5432` og ernærings-PostgreSQL `5434`;
publiserte porter kan overstyres i hubrepoets `.env`. Compose bruker
`WEIGHT_API_PORT` for vekt-API-et; `API_PORT` er en utfaset fallback for eldre
oppsett. Stopp eventuell
Vite-server først, siden den også bruker port 5173. Web er tilgjengelig på
lokalnettet; API og PostgreSQL er kun bundet til `127.0.0.1`.
Data beholdes i et navngitt Docker-volum når containerne stoppes.

Se [felles oppstartsinstruksjoner](../Emberpath/readme.md).

## Kjør backend lokalt med PostgreSQL i Docker

Hvis hubens Compose-stakk allerede kjører, la den stå. Ellers kan du starte
bare vekt-databasen fra hubrepoet:

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose up -d --wait postgres
```

Kjør deretter fra dette repoet på en ledig port når Compose allerede bruker
vekt-API-porten `8000`:

```powershell
cd C:\Workspace\Repos\Emberpath-weight-service
uv run --locked uvicorn src.main:app --reload --port 8003
```

Sett `DATABASE_URL` i tjenestens `.env` til `postgresql+psycopg` for
vekt-databasen på `127.0.0.1` og hubens publiserte `POSTGRES_PORT` (standard
`5432`). Bruk samme databasenavn, bruker og **faktiske passord** som den
kjørende `postgres`-containeren; bruk `POSTGRES_PASSWORD` fra hubens `.env`
og databasenavn/bruker i hubens `compose.yaml`. URL-kod spesialtegn i
legitimasjonen.
Et nytt passord i en lokal `.env` endrer ikke passordet i et eksisterende
databasevolum. Compose har allerede kjørt migreringene for en kjørende stakk;
kjør `uv run --locked alembic upgrade head` separat bare for en ny, umigrert
database.

`--reload` laster kodeendringer automatisk. På Windows velger denne modusen
også Selector-eventløkken som async Psycopg krever; bruk kommandoen over ved
lokal utvikling, og Linux-containeren for kjøring uten reload. Stopp med `Ctrl+C`.
Swagger UI for denne Uvicorn-prosessen finnes på `http://127.0.0.1:8003/docs`.
Webens `/api`-proxy peker fortsatt på Compose-tjenesten, ikke den separate
Uvicorn-prosessen. Via proxyen kan nettleseren kalle API-et fra samme origin
uten egen CORS-konfigurasjon, også fra telefon på samme Wi-Fi via
`http://<PC-ens LAN-IP>:5173/weight`. For direkte nettleserkall til lokal
Uvicorn må du konfigurere CORS for web-originen i tjenestens `.env`; backend
trenger ikke bindes til alle nettverksgrensesnitt.

## API

| Metode | Endepunkt | Resultat |
| --- | --- | --- |
| GET | `/` | Navn, versjon og dokumentasjonslenke når dokumentasjon er aktivert |
| GET | `/readyz` | 200 når påkrevde databasekall fungerer, ellers 503 |
| GET | `/healthz` | 200 og `{"status":"ok"}`, uten databasekall |
| POST | `/weight-logs` | Opprett logg, 201 |
| GET | `/weight-logs` | Liste, nyeste dato først |
| GET | `/weight-logs/summary` | Oppsummering av innlogget brukers valgte periode |
| GET | `/weight-logs/{id}` | Hent logg, 200 |
| PATCH | `/weight-logs/{id}` | Endre dato og/eller vekt, 200 |
| DELETE | `/weight-logs/{id}` | Slett logg, 204 uten responsinnhold |

Eksempel fra PowerShell, med et kortlevd Clerk-sessiontoken satt i
`CLERK_SESSION_TOKEN` for denne terminalen (ikke lagre token i Git):

```powershell
$headers = @{ Authorization = "Bearer $env:CLERK_SESSION_TOKEN" }
$log = Invoke-RestMethod -Headers $headers -Method Post -Uri http://127.0.0.1:8000/weight-logs `
  -ContentType application/json -Body '{"date":"2026-09-17","weight_kg":82.35}'
$log
Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/weight-logs
Invoke-RestMethod -Headers $headers -Method Patch -Uri "http://127.0.0.1:8000/weight-logs/$($log.id)" `
  -ContentType application/json -Body '{"weight_kg":82.1}'
Invoke-RestMethod -Headers $headers -Method Delete -Uri "http://127.0.0.1:8000/weight-logs/$($log.id)"
```

En logg har feltene `id` (UUID), `date` (`YYYY-MM-DD`) og `weight_kg` (tall).
PATCH krever minst ett felt; eksplisitt `null` avvises. Ukjente felter og
ugyldige verdier gir 422. Ukjent ID gir 404. Dato som allerede er registrert
gir 409 med en `detail`-streng, også ved oppdatering. Databasen håndhever unik
kombinasjon av bruker og dato slik at samtidige kall heller ikke lager duplikater.
POST- og PATCH-svar viser verdiene som ble lagret av akkurat dette kallet.
Et senere kall kan ha endret eller slettet målingen før svaret mottas; bruk GET
for å lese gjeldende tilstand.

## Tester

Testene kjører mot en egen PostgreSQL-container på port 5433. De bruker aldri
`DATABASE_URL`. Testdatabasen er midlertidig og separat fra dine vektlogger.

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose --profile test up -d --wait postgres-test
cd ..\Emberpath-weight-service
$env:TEST_DATABASE_URL = "postgresql+psycopg://emberpath:emberpath_test@127.0.0.1:5433/emberpath_test"
uv run --locked pytest -W error
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
```

Testene migrerer `emberpath_test` før kjøring og ruller hver test tilbake i en
isolert transaksjon. En egendefinert `TEST_DATABASE_URL` må bruke PostgreSQL
og et databasenavn som slutter på `_test`. Testene feiler hvis databasen ikke
kjører. Uvicorn trenger ikke å kjøre. De øvrige testene kan kjøres uten database:

```powershell
uv run --locked pytest -m "not integration" -W error
```

Testdekningen omfatter CRUD, sortering, duplikatdato, delvis oppdatering,
validering, ukjent ID og at avviste endringer bevarer eksisterende data.

## Databaseendringer

Skjemaet opprettes og oppdateres gjennom Alembic, ikke ved appoppstart.
Etter modellendringer oppretter du en migrering og kontrollerer innholdet:

```powershell
uv run alembic revision --autogenerate -m "Describe schema change"
uv run alembic upgrade head
```

## Struktur

- `src/main.py`: FastAPI-app og ruteregistrering.
- `src/core/`: miljøkonfigurasjon og databaseøkter.
- `src/models/`: SQLAlchemy-modeller.
- `src/schemas/`: validering og API-responser.
- `src/routers/`: helse og CRUD.
- `alembic/`: versjonerte databaseendringer.
- `tests/`: drifts-, kontrakt- og PostgreSQL-integrasjonstester.

Tjenesten bruker Clerk-autentisering og isolerer vektlogger per bruker.

## Standard fra FastAPI-service

App-fabrikken `create_app(settings)` gir hver app sin egen late databasepool.
Økter bruker async SQLAlchemy/Psycopg; poolen lukkes ved avslutning. Alembic
bruker fortsatt synkron Psycopg for migreringer. Migrering `0001` er uendret;
`0002` legger til brukeridentitet og eierskap uten database-reset.

`DATABASE_REQUIRED=true` er satt i eksempelkonfigurasjonen og Compose. Da kreves
`DATABASE_URL` ved oppstart, og `/readyz` kontrollerer databasen. `/healthz` og `/`
gjør aldri databasekall. Uten eksplisitt konfigurasjon er databasen valgfri, som i
templaten; den modusen er kun nyttig for isolerte tester og metadata/helse.

Alle svar får `X-Request-ID` og sikkerhetsheadere. Driftsfeil bruker
`{"detail":"...","request_id":"..."}`. For kompatibilitet beholder
`/weight-logs` sine eksisterende feilformater: 404/409 har kun `detail`, og 422
har FastAPIs detaljerte valideringsliste. OpenAPI dokumenterer fortsatt dette.
Ruter er ikke flyttet til `/api/v1`; proxyen er uendret, men frontend sender
Bearer-token for beskyttede kall.

Strukturerte logger beholder exception-type og kildelokasjoner, men skjuler
exception-meldinger og databaseparametre. Ikke logg måledata eller credentials.
Dette gir mindre feilsøkingsinformasjon, med hensikt å beskytte persondata.

Sett `ENVIRONMENT=production` og eksplisitte `ALLOWED_HOSTS` ved produksjonskjøring.
Dokumentasjon er da deaktivert med mindre `DOCS_ENABLED=true` er valgt. Dockerens
helseprobe bruker en tillatt Host-header. Compose bruker `/readyz` for avhengigheter.
Databasepool, tilkoblings-, spørrings-, låse- og transaksjonstimeouts kan justeres
via variablene i `.env.example`. Same-origin-proxyen trenger normalt ikke CORS.

CI installerer låste avhengigheter, kjører Ruff, streng Pyright og alle tester med
PostgreSQL, bygger Docker-image og tester containeren med produksjonsverter og
påkrevd database. Den publiserer eller deployer ingenting.


## Authentication and ownership

All `/weight-logs` operations require `Authorization: Bearer <Clerk session token>`.
Configure `CLERK_ISSUER` with the exact Clerk instance HTTPS origin and
`CLERK_AUTHORIZED_PARTIES` with comma-separated frontend origins (for example
`http://localhost:5173`). For standalone runs use the same development issuer
and origins as in the hub's `.env`, not a Clerk secret or a copied example.
Add the explicit LAN origin when testing over Wi-Fi.
These values are public configuration; this API does not need a Clerk secret key.
Missing authentication returns 401; unavailable/missing verification configuration
returns 503. `/`, `/healthz`, and `/readyz` remain public.

The API accepts RS256 session tokens from the configured issuer, checks expiry,
not-before, issued-at, subject, session ID and authorized party, and rejects pending
sessions. Public signing keys are fetched with a five-second timeout and cached
for five minutes; refresh attempts have a 30-second cooldown. There is no Clerk
API call for user metadata on each request. Token expiry bounds how long a revoked
session can remain usable; immediate revocation checking is not implemented.

`users.id` is an internal UUID. `external_identities` maps issuer + subject to it;
email addresses never establish ownership. Every weight query includes that UUID,
and dates are unique per user. Other users' record IDs return 404.

### Assign existing measurements to your account

Migration `0002` preserves existing measurements with nullable `user_id`. They are
hidden from all accounts until explicitly assigned. New API-created logs always
have an owner. Sign in and open the weight page first to provision your identity.
Then verify your own `user_...` identifier in the Clerk Dashboard and run:

```powershell
uv run python -m src.claim_legacy --subject user_YOUR_VERIFIED_ID
uv run python -m src.claim_legacy --subject user_YOUR_VERIFIED_ID --apply
```

With Compose, run the same module in the configured weight-service container:

```powershell
docker compose exec weight-service python -m src.claim_legacy --subject user_YOUR_VERIFIED_ID
docker compose exec weight-service python -m src.claim_legacy --subject user_YOUR_VERIFIED_ID --apply
```

The first command only reports the count. The second assigns **all unclaimed
measurements** to that already-existing identity in one transaction. The issuer
comes from `CLERK_ISSUER`; the command cannot create an identity or reassign owned
rows. Rerunning after success reports zero. If your new account already has a log
on a legacy date, the unique constraint aborts the whole assignment; resolve the
conflict deliberately before retrying. Never guess the subject or use an email.

Downgrading `0002` restores global date uniqueness and therefore fails atomically
if multiple users now have measurements on the same date. Do not downgrade a
multi-user database without an explicit data migration plan.

### Period summary

`GET /weight-logs/summary?start_date=2026-09-01&end_date=2026-09-30`
accepts optional inclusive ISO dates. Omitted boundaries are unbounded; an inverted
range returns 422. Authentication and ownership rules match the CRUD endpoints.

The response contains `measurement_count`, `mean_weight_kg`, `first`, `latest`,
`change_kg` and `change_percent`. First/latest include the existing measurement
ID, date and weight. The mean uses recorded measurements only; missing days are
not zero or interpolated. Change is latest minus first; percent is that change
divided by the first weight, multiplied by 100. Calculations use decimal arithmetic
and round half up to two decimal places, serialized as JSON numbers.

An empty period returns count 0 and null for every other field. A single measurement
has a mean and first/latest entry, but null changes. Two equal weights give zero
change. All-time is requested by omitting both dates.

### Configurable rolling average

`GET /weight-logs/rolling-average?start_date=2026-09-01&end_date=2026-09-30`
accepts the same optional inclusive date boundaries and ownership rules as the
summary endpoint. Optional `window_days` accepts `7`, `14`, or `30` (default `7`);
unsupported values return 422. The response echoes `window_days` and returns
ascending `points`, each containing
`date`, `mean_weight_kg` and `measurement_count`.

Each point averages recorded measurements on that date and the preceding
`window_days - 1` calendar days (6, 13, or 29). Missing days are ignored; partial windows are included. Points
exist only on recorded dates, never invented dates. The first visible points can
use measurements before the requested start date, preserving the same trend when
changing the selected period. No measurement after a point's date contributes.
Means use decimal arithmetic and round half up to two decimal places. An empty
period returns an empty points array; an inverted range returns 422.

### Personal weight goals

Goals belong to the authenticated user. `GET /weight-goals/active` returns the
active goal or `null`. `PUT /weight-goals/active` accepts `target_weight_kg`,
`start_date` (the user's local calendar date), optional `target_date`, and optional
`baseline_weight_kg`. The target date must be after the start date; weight uses the same positive,
maximum two-decimal constraints as measurements. An identical PUT is idempotent.
Changing the target replaces the active goal while retaining its history.

`PATCH /weight-goals/{id}` accepts `{ "status": "completed" }` or
`{ "status": "cancelled" }`. Completion is explicit, never inferred from one
measurement. Inactive goals return 409; another user's goal returns 404.
Responses include `id`, `target_weight_kg`, `start_date`, `target_date`, `status`,
`created_at` and `ended_at`. Timestamps use UTC. A database constraint and owner
row lock ensure at most one active goal per user. Migration `0003` adds only the
new goals table; measurements are unchanged. Historical goals are retained in
storage; a history endpoint and projections are outside this first version.

PUT and PATCH responses describe the status when that request committed. If
another request replaces the goal before the response arrives, the first PUT
may acknowledge `active` while `GET /weight-goals/active` already shows the
newer goal.

A dated goal requires a starting baseline. When omitted, the service uses the
latest measurement on or before the start date for that user. If none exists,
422 asks for a starting weight. The baseline is saved as a snapshot; later
measurements do not move the plan. Saving a goal with the same start date reuses
its baseline unless an explicit replacement baseline is supplied.

Responses also include `baseline_weight_kg` and `plan`. A dated goal with a
baseline returns `duration_days`, `total_change_kg`, `weekly_change_kg`, and
`fortnightly_change_kg`. Weekly change is `(target - baseline) * 7 / duration_days`;
fortnightly change uses 14. Values round half up to two decimal places. These
values describe the user's plan, not a prediction or recommended rate.

Undated goals and legacy goals without a baseline return `plan: null` and retain
the flat target display. Save an existing goal to establish its baseline.
Migration `0004` adds a nullable baseline without inferring historical values or
changing measurements. Existing same-day goals remain readable without a plan;
new dated goals require a positive duration.

### Delimited measurement transfer

All transfer endpoints require authentication and only access the current user's
measurements. No goals are modified. Import accepts `.csv` or `.txt` text with
an explicit comma, semicolon or tab delimiter. Files use `date,weight,unit`
headers separated by the selected delimiter; header order and case are flexible. Use ISO `YYYY-MM-DD` dates, decimal
points, and `kg` or `lb`. UTF-8 BOM, quoted fields, CRLF, and blank lines are
supported. Duplicate dates within a file must be corrected before importing.

Kilograms follow existing positive-weight validation (0.01-9999.99, at most two
decimal places). Pounds allow up to six decimal places and convert using exactly
0.45359237 kg/lb, rounded half up to two decimal places before validation.
Scientific notation, formulas, and non-finite values are not accepted. Files are
limited to 1 MiB of UTF-8 content and 10000 measurements.

- `GET /weight-logs/export?delimiter=comma|semicolon|tab` downloads all measurements, oldest first,
  with `date,weight,unit` columns and weights in kilograms to two decimal places. The filename uses `.csv` for every delimiter.
- `POST /weight-logs/import/preview` accepts JSON with `content`, `delimiter` (`comma`, `semicolon`, or `tab`), and
  optional `duplicate_policy` (`skip`, the default, or `replace`). It returns
  `rows` with source `row`, parsed `date`, normalized `weight_kg`, `action`, and
  `errors`; counts `imported`, `replaced`, `skipped`, and `errors`; and a
  `preview_token`. Invalid fields appear as row errors; malformed files return
  422. Preview does not write measurements.
- `POST /weight-logs/import` accepts the same input plus `preview_token`. It
  revalidates the entire file and returns `imported`, `replaced`, and `skipped`.
  Any invalid row rejects the whole import with 422. Replacement preserves the
  existing measurement ID. If relevant measurements or input changed since
  preview, 409 requires another preview. A concurrent date conflict also rolls
  back the entire import and returns 409. No partial import is saved.

A preview token detects stale input/state; it is not an authorization credential.
Ownership is enforced separately on every request. Importing historical values
can update summaries and averages but never changes a saved goal baseline.
