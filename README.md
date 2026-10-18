# ANY SENSOR. ANY PROTOCOL. ANY SITE. ONE INTELLIGENT PLATFORM.

Local-first vertical slice for industrial energy and equipment monitoring.

**Product motto:** ANY SENSOR. ANY PROTOCOL. ANY SITE. ONE INTELLIGENT PLATFORM.

The current MVP is the first implementation slice of this broader vendor-neutral platform vision.

Current flow:

`simulator -> canonical telemetry -> SQLite gateway outbox -> backend core -> rules/alerts`

This is a development prototype, not production-ready industrial-control software.

## Run tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider
```

## Current boundaries

- Telemetry is validated through `shared.models.Telemetry`.
- Gateway records are persisted before upload through `gateway.outbox.Outbox`.
- Backend ingestion is idempotent by gateway sequence/idempotency key.
- The first deterministic rule creates one active alert for a sustained simulated high-power condition.
- The reference calibration plugin calculates `reference - observed`, validates a configurable safety limit, and requires explicit approval before application.
- Raw telemetry remains unchanged; corrected values carry the calibration version and original reading.
- Physical Modbus/BLE adapters and physical calibration writes remain disabled; the product slice now includes SQLite persistence, API-key authentication, basic project RBAC, model/profile configuration, exports, webhooks, and an adapter SDK.

## Calibration plugin demo

The browser calibration panel demonstrates a simulated sensor workflow: enter an observed value and a trusted reference in the same unit, create a proposal, approve it, then apply it. The current plugin does not write BLE characteristics, Modbus registers, or gateway configuration.

## Modbus dry-run preview

The Modbus preview uses an explicit, deterministic demo register map only:

- measurement holding register: `100`;
- calibration holding register: `200`;
- signed 16-bit raw measurement;
- scale: `0.1` (`235` decodes to `23.5 degC`);
- unit: `degC`;
- permitted calibration register range: `-500..500`.

The preview reads the simulated measurement and calibration registers, calculates the reference-point offset, and returns a write plan containing the original and proposed raw calibration values. It never opens a serial or TCP connection and never writes a register. The dashboard displays the same plan and the explicit **No hardware write performed** boundary.

A real Modbus RTU/TCP integration requires a vendor-provided register map and verified connection details: RTU serial settings or TCP host/port, slave ID, register addresses, signedness, scaling, permitted range, and documented read-back behavior. Physical writes remain out of scope until the map is validated with hardware-in-the-loop testing, read-back verification, rollback behavior, and separate explicit approval.

The development API endpoint is:

```text
POST /v1/calibrations/modbus/preview
X-Tenant-ID: org_demo
{"device_id": "modbus_sensor_1", "reference_value": 25.0}
```

It returns a calibration proposal and a dry-run write plan; there is intentionally no physical-write endpoint.

## Calibration campaigns for 1,000 sensors

The campaign simulator coordinates up to 1,000 simulated sensors with a bounded worker pool. A campaign follows this lifecycle:

```text
create -> start proposals -> approve batch -> apply approved -> verify/report
```

Campaign endpoints are tenant-scoped:

```text
POST /v1/calibration-campaigns
POST /v1/calibration-campaigns/{id}/start
GET  /v1/calibration-campaigns/{id}
GET  /v1/calibration-campaigns/{id}/attempts
POST /v1/calibration-campaigns/{id}/approve
POST /v1/calibration-campaigns/{id}/apply
GET  /v1/calibration-campaigns/{id}/report
```

Campaign start only creates proposals; it never applies them automatically. Communication failures are isolated to individual sensors and appear as failed attempts. Repeating start, approval, or apply operations is safe for completed lifecycle stages. The simulator uses deterministic sensors and a bounded default worker pool rather than one thread per sensor. Product-scoped campaigns can be persisted in SQLite for a single-instance hosted baseline.

This demonstrates orchestration capacity, not physical capacity. A real 1,000-sensor deployment also requires enough gateways, RS485 buses or BLE radios, reference fixtures, power, network capacity, and site-level scheduling. Production deployment will require durable campaign storage, distributed gateway workers, queue-based scheduling, authentication/RBAC, persistent audit events, retries, and gateway synchronization. Physical calibration writes remain disabled until each sensor model has a verified vendor map, read-back behavior, rollback procedure, and hardware-in-the-loop validation.

The browser campaign panel is explicitly simulation-only and intentionally exposes no physical-write action.

## Campaign simulator example

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 - <<'PY'
from backend.campaigns import CalibrationCampaignManager
from plugins.calibration import ReferencePoint

manager = CalibrationCampaignManager(max_workers=32)
campaign = manager.create("org_demo", 1000, ReferencePoint(25.0, "degC"))
manager.start("org_demo", campaign.campaign_id)
print(manager.summary(campaign))
PY
```

The example produces 1,000 proposals without opening any hardware connection.

## Development limitations

- The legacy `X-Tenant-ID` development routes remain in-memory; use the project-scoped API for persisted product workflows.
- SQLite/Docker is a single-instance hosted baseline, not high availability or industrial-control readiness.
- No physical Modbus, BLE, or other sensor write path is enabled.
- Simulated parallel workers do not replace hardware-in-the-loop throughput testing.

## Product platform slice

The product API adds persistent users, projects, memberships, sensor models, calibration profiles, API keys, project-scoped campaigns, and JSON/CSV exports. Roles are `owner`, `operator`, and `viewer`; API keys are shown only at creation and stored as salted hashes. Webhook endpoints store only a secret hash, while the initial recording transport signs lifecycle events without making network calls.

Run the hosted baseline with `docker compose up --build`; the SQLite database is mounted at `/data/industrial_iot.db`. See [docs/quickstart.md](docs/quickstart.md), [docs/api.md](docs/api.md), and [docs/adapter-sdk.md](docs/adapter-sdk.md). The simulator-to-gateway path is intentionally adapter-compatible: replace the simulator read implementation with a validated gateway adapter while retaining proposal, approval, verification, and reporting boundaries.

Next production-oriented work should add restart rehydration for in-flight campaign workers, real delivery retries, and distributed gateway execution only after the simulator and approval workflow are validated with a pilot.
