# API outline

The development API uses JSON and supports the existing `X-Tenant-ID` header for compatibility. The product-facing API uses API keys in `Authorization: Bearer <key>` or `X-API-Key` and scopes operations to a project.

Core product resources:

- users and projects;
- project members with `owner`, `operator`, and `viewer` roles;
- sensor models and calibration profiles;
- calibration campaigns and per-sensor attempts;
- API keys and webhook endpoints;
- JSON and CSV campaign reports.

Campaign lifecycle:

```text
created -> proposed -> approved -> applied
```

Campaign start never performs a physical write. Every export includes `simulation_only=true` for simulated attempts.
