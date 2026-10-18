# SaaS operating model

This repository is evolving into a multi-tenant SaaS control plane for industrial sensor calibration and telemetry workflows.

## Tenant model

A customer owns a project. Users are members of projects with one of three roles:

- `owner`: manages members, API keys, webhooks, and subscription settings;
- `operator`: configures models/profiles and runs approval-gated campaigns;
- `viewer`: reads campaigns, telemetry, and exports.

Product requests authenticate with an API key or bearer session token. Project membership is resolved server-side; the legacy `X-Tenant-ID` header is retained only for development compatibility routes.

## Plans and usage

The initial local billing service provides Starter, Growth, Professional, and Enterprise plan entitlements. Campaign creation meters campaign count and sensor operations for the current UTC month. The repository stores subscription and usage state so a hosted billing provider can later synchronize it through signed, idempotent webhook events.

This is entitlement plumbing, not a live payment integration. A production deployment must connect a provider such as Stripe behind a secret-managed billing adapter and must verify provider signatures.

## Local setup

```text
POST /v1/auth/register
POST /v1/auth/login
POST /v1/projects
POST /v1/projects/{project_id}/subscription
GET  /v1/projects/{project_id}/subscription
GET  /v1/projects/{project_id}/usage
```

The login response contains a short-lived development session token. API keys remain the preferred machine-integration credential and are shown only when created.

## Production boundary

The current service is a single-process modular-monolith baseline. Before charging customers, deploy behind HTTPS with PostgreSQL, managed backups, secret management, rate limiting, monitoring, email delivery, and a real billing provider. Physical Modbus/BLE writes remain disabled until each vendor adapter passes register-map, read-back, rollback, and hardware-in-the-loop validation.
