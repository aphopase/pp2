"""Minimal JSON HTTP API for local development and dashboard integration."""
from __future__ import annotations

import json
import os
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from backend.auth import AuthService
from backend.billing import BillingService
from backend.exports import campaign_csv, campaign_json
from backend.storage import Repository
from backend.webhooks import RecordingWebhookTransport
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from backend.app import IoTCore, Rule
from backend.campaigns import CalibrationCampaignManager
from gateway.simulator import SimulatorAdapter
from plugins.calibration import ReferenceCalibrationPlugin, ReferencePoint
from plugins.modbus_calibration import InMemoryModbusTransport, ModbusCalibrationAdapter, RegisterMap


class ApiHandler(BaseHTTPRequestHandler):
    core = IoTCore()
    core.add_rule(Rule("high-power", "org_demo", "site_demo", "power", ">", 20))
    core.ingest([item.to_dict() for item in SimulatorAdapter().readings(4)], "org_demo")
    calibration = ReferenceCalibrationPlugin()
    proposals: dict[str, object] = {}
    modbus_previews: dict[str, dict[str, object]] = {}
    campaigns = CalibrationCampaignManager()
    repository = Repository(os.environ.get("IOT_DB_PATH", "industrial_iot.db"))
    auth = AuthService(repository)
    billing = BillingService(repository, os.environ.get("IOT_BILLING_SIGNING_SECRET", ""))
    webhook_transport = RecordingWebhookTransport()

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tenant-ID, X-API-Key, Authorization")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proposal(self, tenant_id: str, proposal_id: str):
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.tenant_id != tenant_id:
            raise KeyError("calibration not found")
        return proposal

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be an object")
        return value

    def _product_principal(self, project_id: str | None = None):
        raw = self.headers.get("X-API-Key", "")
        if not raw:
            authorization = self.headers.get("Authorization", "")
            raw = authorization.removeprefix("Bearer ").strip()
        if not raw:
            raise PermissionError("API key is required")
        return self.auth.authenticate(raw, project_id)

    @staticmethod
    def _campaign_parts(path: str) -> tuple[str | None, str | None]:
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[:2] != ["v1", "calibration-campaigns"]:
            return None, None
        return (parts[2] if len(parts) > 2 else ""), (parts[3] if len(parts) > 3 else None)

    def _campaign_summary(self, campaign) -> dict[str, Any]:
        return self.campaigns.summary(campaign)

    def _campaign_get(self, tenant_id: str) -> bool:
        campaign_id, action = self._campaign_parts(self.path)
        if campaign_id is None:
            return False
        if not campaign_id:
            self._send(HTTPStatus.OK, {
                "items": [self._campaign_summary(item) for item in self.campaigns.list(tenant_id)]
            })
            return True
        campaign = self.campaigns.get(tenant_id, campaign_id)
        if action == "attempts":
            payload = {"items": self.campaigns.attempts(tenant_id, campaign_id)}
        elif action == "report":
            payload = self.campaigns.report(tenant_id, campaign_id)
        elif action is None:
            payload = self._campaign_summary(campaign)
        else:
            return False
        self._send(HTTPStatus.OK, payload)
        return True

    def _campaign_post(self, tenant_id: str, body: dict[str, Any]) -> bool:
        campaign_id, action = self._campaign_parts(self.path)
        if campaign_id is None:
            return False
        if not campaign_id:
            reference = ReferencePoint(body["reference_value"], body["unit"])
            campaign = self.campaigns.create(
                tenant_id,
                body["sensor_count"],
                reference,
                body.get("failure_ids"),
            )
            self._send(HTTPStatus.CREATED, self._campaign_summary(campaign))
            return True
        if action == "start":
            campaign = self.campaigns.start(tenant_id, campaign_id)
        elif action == "approve":
            campaign = self.campaigns.approve(tenant_id, campaign_id)
        elif action == "apply":
            campaign = self.campaigns.apply(tenant_id, campaign_id)
        else:
            return False
        self._send(HTTPStatus.OK, self._campaign_summary(campaign))
        return True

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Tenant-ID, X-API-Key, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path.startswith("/v1/projects") or self.path == "/v1/webhook-deliveries":
            try:
                principal = self._product_principal()
                parsed = urlparse(self.path)
                parts = parsed.path.strip("/").split("/")
                if self.path == "/v1/projects":
                    self._send(HTTPStatus.OK, {"items": self.repository.projects_for_user(principal.user_id)})
                    return
                if self.path == "/v1/webhook-deliveries":
                    if not principal.project_id:
                        raise KeyError("project not found")
                    self._send(HTTPStatus.OK, {"items": self.repository.webhook_deliveries(principal.project_id)})
                    return
                project_id = parts[2]
                if project_id != principal.project_id:
                    raise KeyError("project not found")
                if len(parts) == 3:
                    self._send(HTTPStatus.OK, {"project_id": project_id, "role": principal.role})
                elif parts[3] == "sensor-models":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    self._send(HTTPStatus.OK, {"items": self.repository.models(project_id)})
                elif parts[3] == "calibration-profiles":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    self._send(HTTPStatus.OK, {"items": self.repository.profiles(project_id)})
                elif parts[3] == "webhooks":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    self._send(HTTPStatus.OK, {"items": self.repository.webhooks(project_id)})
                elif parts[3] == "subscription":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    self._send(HTTPStatus.OK, self.billing.subscription(project_id))
                elif parts[3] == "usage":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    self._send(HTTPStatus.OK, self.billing.usage(project_id))
                elif parts[3] == "campaigns":
                    self.auth.require(principal, "owner", "operator", "viewer")
                    if len(parts) == 4:
                        self._send(HTTPStatus.OK, {"items": self.repository.campaign_rows(project_id)})
                    else:
                        campaign_id = parts[4]
                        state = self.repository.campaign_state(project_id, campaign_id)
                        if state is None:
                            raise KeyError("campaign not found")
                        if len(parts) > 5 and parts[5] == "export":
                            fmt = parse_qs(parsed.query).get("format", ["json"])[0]
                            if fmt == "csv":
                                body = campaign_csv(state).encode()
                                self.send_response(HTTPStatus.OK)
                                self.send_header("Content-Type", "text/csv")
                                self.send_header("Content-Length", str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                            else:
                                body = campaign_json(state).encode()
                                self.send_response(HTTPStatus.OK)
                                self.send_header("Content-Type", "application/json")
                                self.send_header("Content-Length", str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                        else:
                            self._send(HTTPStatus.OK, state)
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            except PermissionError as error:
                self._send(HTTPStatus.FORBIDDEN, {"error": str(error)})
                return
            except KeyError as error:
                self._send(HTTPStatus.NOT_FOUND, {"error": f"not found: {error}"})
                return
        if self.path == "/v1/projects":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if self.path == "/v1/auth/login":
            self._send(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "use POST"})
            return
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok"})
            return
        tenant_id = self.headers.get("X-Tenant-ID")
        if not tenant_id:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "X-Tenant-ID is required"})
            return
        try:
            if self._campaign_get(tenant_id):
                return
            if self.path == "/v1/telemetry":
                self._send(HTTPStatus.OK, {"items": self.core.query_telemetry(tenant_id)})
            elif self.path == "/v1/alerts":
                self._send(HTTPStatus.OK, {"items": self.core.active_alerts(tenant_id)})
            elif self.path.startswith("/v1/calibrations/"):
                proposal_id = self.path.split("/")[3]
                proposal = self.proposals.get(proposal_id)
                if proposal is None or proposal.tenant_id != tenant_id:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "calibration not found"})
                else:
                    self._send(HTTPStatus.OK, {"proposal": proposal.__dict__})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except KeyError as error:
            self._send(HTTPStatus.NOT_FOUND, {"error": f"not found: {error}"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._json()
            if self.path == "/v1/auth/register":
                user = self.auth.register(body["email"], body["password"])
                self._send(HTTPStatus.CREATED, user)
                return
            if self.path == "/v1/auth/login":
                user = self.auth.login(body["email"], body["password"])
                self._send(HTTPStatus.OK, user)
                return
            if self.path == "/v1/auth/logout":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not token:
                    raise PermissionError("access token is required")
                self.auth.logout(token)
                self._send(HTTPStatus.NO_CONTENT, {})
                return
            product_path = self.path.strip("/").split("/")
            if product_path[:2] == ["v1", "projects"]:
                if self.path == "/v1/projects" and not (self.headers.get("X-API-Key") or self.headers.get("Authorization")):
                    user = self.repository.authenticate_user(body.get("email", ""), body.get("password", ""))
                    if user is None:
                        raise PermissionError("invalid credentials")
                    self._send(HTTPStatus.CREATED, self.repository.create_project(user["id"], body["name"]))
                    return
                project_id = product_path[2] if len(product_path) > 2 else ""
                principal = self._product_principal(project_id or None)
                if self.path == "/v1/projects":
                    self.auth.require(principal, "owner", "operator")
                    self._send(HTTPStatus.CREATED, self.repository.create_project(principal.user_id, body["name"]))
                    return
                if project_id != principal.project_id:
                    raise KeyError("project not found")
                resource = product_path[3] if len(product_path) > 3 else ""
                if resource == "members":
                    self.auth.require(principal, "owner")
                    self._send(HTTPStatus.CREATED, self.repository.add_member(project_id, body["email"], body["role"]))
                elif resource == "sensor-models":
                    self.auth.require(principal, "owner", "operator")
                    self._send(HTTPStatus.CREATED, self.repository.create_model(project_id, body))
                elif resource == "calibration-profiles":
                    self.auth.require(principal, "owner", "operator")
                    self._send(HTTPStatus.CREATED, self.repository.create_profile(project_id, body))
                elif resource == "api-keys":
                    self.auth.require(principal, "owner")
                    info, secret = self.repository.create_api_key(project_id, principal.user_id, body.get("label", "default"))
                    self._send(HTTPStatus.CREATED, {**info, "api_key": secret})
                elif resource == "webhooks":
                    self.auth.require(principal, "owner")
                    endpoint = self.repository.create_webhook(project_id, body["url"], body["secret"])
                    self._send(HTTPStatus.CREATED, endpoint)
                elif resource == "subscription":
                    self.auth.require(principal, "owner")
                    self._send(HTTPStatus.OK, self.billing.subscribe(project_id, body.get("plan", "starter")))
                elif resource == "campaigns" and len(product_path) == 4:
                    self.auth.require(principal, "owner", "operator")
                    self.billing.check_campaign(project_id, body["sensor_count"])
                    campaign = self.campaigns.create(principal.project_id, body["sensor_count"], ReferencePoint(body["reference_value"], body["unit"]), body.get("failure_ids"))
                    self.billing.record_campaign(project_id, body["sensor_count"])
                    self.repository.record_campaign(project_id, campaign.campaign_id, self.campaigns.report(principal.project_id, campaign.campaign_id), body.get("model_id", "simulator"), body.get("profile_id", "default"))
                    self._send(HTTPStatus.CREATED, self.campaigns.summary(campaign))
                elif resource == "campaigns" and len(product_path) == 6:
                    self.auth.require(principal, "owner", "operator")
                    campaign_id, action = product_path[4], product_path[5]
                    campaign = self.campaigns.get(project_id, campaign_id)
                    if action == "start":
                        campaign = self.campaigns.start(project_id, campaign_id)
                    elif action == "approve":
                        campaign = self.campaigns.approve(project_id, campaign_id)
                    elif action == "apply":
                        campaign = self.campaigns.apply(project_id, campaign_id)
                    else:
                        raise KeyError("campaign action not found")
                    self.repository.record_campaign(project_id, campaign_id, self.campaigns.report(project_id, campaign_id), "simulator", "default")
                    self._send(HTTPStatus.OK, self.campaigns.summary(campaign))
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            tenant_id = self.headers.get("X-Tenant-ID")
            if not tenant_id:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "X-Tenant-ID is required"})
                return
            if self._campaign_post(tenant_id, body):
                return
            if self.path == "/v1/telemetry":
                self._send(HTTPStatus.OK, self.core.ingest(body.get("records", []), tenant_id))
            elif self.path == "/v1/rules":
                rule = Rule(tenant_id=tenant_id, **body)
                self.core.add_rule(rule)
                self._send(HTTPStatus.CREATED, {"rule_id": rule.rule_id})
            elif self.path == "/v1/calibrations/modbus/preview":
                transport = InMemoryModbusTransport({(1, 100): 235, (1, 200): 0})
                adapter = ModbusCalibrationAdapter(transport, RegisterMap(1, 100, 200, "degC"))
                proposal, plan = adapter.preview(
                    tenant_id, body["device_id"], ReferencePoint(body["reference_value"], "degC")
                )
                self.proposals[proposal.proposal_id] = proposal
                self.modbus_previews[proposal.proposal_id] = plan.__dict__
                self._send(HTTPStatus.CREATED, {"proposal": proposal.__dict__, "write_plan": plan.__dict__})
            elif self.path == "/v1/calibrations":
                proposal = self.calibration.propose(
                    tenant_id=tenant_id,
                    device_id=body["device_id"],
                    observed_value=body["observed_value"],
                    reference=ReferencePoint(body["reference_value"], body["unit"]),
                    expected_unit=body["unit"],
                    max_offset=body.get("max_offset", 5.0),
                )
                self.proposals[proposal.proposal_id] = proposal
                self._send(HTTPStatus.CREATED, {"proposal": proposal.__dict__})
            elif self.path.startswith("/v1/calibrations/") and self.path.endswith("/approve"):
                proposal = self._proposal(tenant_id, self.path.split("/")[3])
                self.calibration.approve(proposal, body["actor"])
                self._send(HTTPStatus.OK, {"proposal": proposal.__dict__})
            elif self.path.startswith("/v1/calibrations/") and self.path.endswith("/apply"):
                proposal = self._proposal(tenant_id, self.path.split("/")[3])
                self.calibration.apply(proposal)
                self._send(HTTPStatus.OK, {"proposal": proposal.__dict__})
            elif self.path.startswith("/v1/alerts/") and self.path.endswith("/acknowledge"):
                alert_id = self.path.split("/")[3]
                self._send(HTTPStatus.OK, self.core.acknowledge_alert(alert_id, tenant_id))
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except json.JSONDecodeError as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except PermissionError as error:
            self._send(HTTPStatus.FORBIDDEN, {"error": str(error)})
        except KeyError as error:
            self._send(HTTPStatus.NOT_FOUND, {"error": f"not found: {error}"})
        except (TypeError, ValueError, RuntimeError) as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"IoT API listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve()
