# AlphaPassbook

Cyberpunk booking ops dashboard for Passport India appointment slots.

## Features

- Login-protected web UI
- Manual booking (token, app ref, PBO ID, date)
- YAML job import with parallel workers
- Live WebSocket logs
- Kill jobs individually or all at once

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash start_dashboard.sh
```

Open **http://localhost:8080**

**Login:** `AlphaPassbook` / `Alphafx@123`

## YAML job format

See `job.yaml` for an example. Each `(pboId × date)` pair runs as a parallel worker.
