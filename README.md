# Emberpath Weight Service

Minimal FastAPI-tjeneste for Emberpath. Foreløpig tilbyr tjenesten kun
`GET /healthz`, som returnerer HTTP 200 og `{"status": "ok"}`.
Endepunktet krever ingen database, konfigurasjon eller eksterne tjenester.

## Installasjon

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/) hvis det
ikke allerede er tilgjengelig. Prosjektet krever Python 3.13 eller nyere.
uv laster ned en kompatibel Python-versjon ved behov.

Kjør kommandoene fra roten av dette repoet:

```powershell
cd C:\Workspace\Repos\Emberpath-weight-service
uv sync --locked
```

Dette oppretter `.venv` og installerer avhengighetene fra `uv.lock`, inkludert
utviklingsverktøyene. `uv run` bruker miljøet automatisk; du trenger ikke å
aktivere det manuelt. Versjoner låses i `uv.lock`, som skal sjekkes inn i Git.

## Lokal oppstart

```powershell
uv run uvicorn src.main:app --reload
```

Tjenesten kjører på `http://127.0.0.1:8000`. `--reload` starter den på nytt når
Python-filene endres. Stopp med `Ctrl+C`.

Kontroller helseruten fra en annen terminal:

```powershell
curl.exe -i http://127.0.0.1:8000/healthz
```

Forventet status er `200 OK` og responsen er `{"status":"ok"}`.
Interaktiv API-dokumentasjon er tilgjengelig på `http://127.0.0.1:8000/docs`.

## Tester

```powershell
uv run pytest
```

Testen kaller appen med FastAPIs testklient og kontrollerer både statuskode og
JSON-respons. Du trenger ikke å starte Uvicorn først.

## Ruff

Kontroller kode og formatering:

```powershell
uv run ruff check .
uv run ruff format --check .
```

Formater kode ved behov:

```powershell
uv run ruff format .
```

## Struktur

- `src/main.py`: oppretter appen og registrerer rutene.
- `src/routers/health.py`: helseruten.
- `tests/test_health.py`: test av helseruten.
