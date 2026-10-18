import json
import threading
import urllib.request

from backend.http_api import ApiHandler, ThreadingHTTPServer
from gateway.simulator import SimulatorAdapter


def test_http_api_ingests_and_lists_alerts():
    server = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {"X-Tenant-ID": "org_demo", "Content-Type": "application/json"}
        records = [item.to_dict() for item in SimulatorAdapter().readings(4)]
        request = urllib.request.Request(
            f"{base}/v1/telemetry", json.dumps({"records": records}).encode(), headers, method="POST"
        )
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
        request = urllib.request.Request(f"{base}/v1/alerts", headers={"X-Tenant-ID": "org_demo"})
        with urllib.request.urlopen(request) as response:
            payload = json.load(response)
        assert len(payload["items"]) == 1
        assert payload["items"][0]["device_id"] == "motor_02"

        preview_request = urllib.request.Request(
            f"{base}/v1/calibrations/modbus/preview",
            json.dumps({"device_id": "modbus_sensor_1", "reference_value": 25.0}).encode(),
            headers,
            method="POST",
        )
        with urllib.request.urlopen(preview_request) as response:
            assert response.status == 201
            preview = json.load(response)
        assert preview["proposal"]["tenant_id"] == "org_demo"
        assert preview["proposal"]["observed_value"] == 23.5
        assert preview["proposal"]["offset"] == 1.5
        assert preview["write_plan"]["register"] == 200
        assert preview["write_plan"]["original_raw_value"] == 0
        assert preview["write_plan"]["proposed_raw_value"] == 15
        assert "no hardware write" in preview["write_plan"]["reason"]

        other_tenant_headers = {"X-Tenant-ID": "org_other", "Content-Type": "application/json"}
        other_request = urllib.request.Request(
            f"{base}/v1/calibrations/modbus/preview",
            json.dumps({"device_id": "modbus_sensor_1", "reference_value": 25.0}).encode(),
            other_tenant_headers,
            method="POST",
        )
        with urllib.request.urlopen(other_request) as response:
            assert response.status == 201
            other_preview = json.load(response)
        assert other_preview["proposal"]["tenant_id"] == "org_other"

        campaign_request = urllib.request.Request(
            f"{base}/v1/calibration-campaigns",
            json.dumps({"sensor_count": 4, "reference_value": 25.0, "unit": "degC", "failure_ids": ["sensor_0002"]}).encode(),
            headers,
            method="POST",
        )
        with urllib.request.urlopen(campaign_request) as response:
            assert response.status == 201
            campaign = json.load(response)
        campaign_id = campaign["campaign_id"]
        with urllib.request.urlopen(urllib.request.Request(f"{base}/v1/calibration-campaigns/{campaign_id}/start", b"{}", headers, method="POST")) as response:
            started = json.load(response)
        assert started["counts"]["proposed"] == 3
        assert started["counts"]["failed"] == 1
        with urllib.request.urlopen(urllib.request.Request(f"{base}/v1/calibration-campaigns/{campaign_id}/approve", b"{}", headers, method="POST")) as response:
            assert json.load(response)["status"] == "approved"
        with urllib.request.urlopen(urllib.request.Request(f"{base}/v1/calibration-campaigns/{campaign_id}/apply", b"{}", headers, method="POST")) as response:
            applied = json.load(response)
        assert applied["counts"]["verified"] == 3
        with urllib.request.urlopen(urllib.request.Request(f"{base}/v1/calibration-campaigns/{campaign_id}/report", headers={"X-Tenant-ID": "other_org"})) as response:
            assert response.status == 200
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    finally:
        server.shutdown()
        thread.join(timeout=2)
