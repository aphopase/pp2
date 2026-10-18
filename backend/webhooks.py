"""Safe webhook event recording and signing."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WebhookEvent:
    event: str
    payload: dict[str, Any]
    signature: str


class RecordingWebhookTransport:
    def __init__(self) -> None:
        self.events: list[WebhookEvent] = []

    def publish(self, url: str, secret: str, event: str, payload: dict[str, Any]) -> WebhookEvent:
        del url
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        result = WebhookEvent(event, payload, signature)
        self.events.append(result)
        return result
