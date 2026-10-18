# Quickstart

This repository provides a simulator-first calibration platform. It can persist projects and configuration locally, coordinate campaigns of up to 1,000 simulated sensors, and export reports. It does not write to physical sensors.

## Local run

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
PYTHONPATH=. python -m backend.http_api
```

The API listens on `http://127.0.0.1:8080`. The SQLite database defaults to `industrial_iot.db`; set `IOT_DB_PATH` to move it. Back up the database while the service is stopped.

## Docker baseline

```sh
docker compose up --build
```

The compose file mounts `/data` so the SQLite database survives container replacement. This is a single-instance hosted baseline, not a highly available production deployment.

## First workflow

1. Register a user.
2. Create a project and API key.
3. Configure a sensor model and calibration profile.
4. Create and start a simulator campaign.
5. Review and approve proposals.
6. Apply approved simulated calibrations.
7. Export JSON or CSV.

Physical gateways and writes remain disabled until a vendor-specific adapter is validated.
