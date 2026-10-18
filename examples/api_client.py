"""Illustrative API client flow for a future hosted deployment."""
import json
from urllib.request import Request, urlopen


BASE = "http://127.0.0.1:8080"


def post(path: str, token: str, payload: dict) -> dict:
    request = Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"X-API-Key": token, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)


# Supply a key created for the project; no secret is committed here.
# campaign = post("/v1/projects/project-id/campaigns", API_KEY, {...})
