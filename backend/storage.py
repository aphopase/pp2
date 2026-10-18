"""SQLite persistence for projects, identities, calibration configuration, campaigns, and SaaS state."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_secret(secret: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 120_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split(":", 1)
        expected = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt_hex), 120_000)
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


class Repository:
    def __init__(self, path: str | Path = "industrial_iot.db") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_members (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner','operator','viewer')),
                PRIMARY KEY(project_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id), label TEXT NOT NULL,
                key_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, revoked_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
            CREATE TABLE IF NOT EXISTS sensor_models (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, protocol TEXT NOT NULL, measurement TEXT NOT NULL,
                unit TEXT NOT NULL, config_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(project_id, name)
            );
            CREATE TABLE IF NOT EXISTS calibration_profiles (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL, unit TEXT NOT NULL, max_offset REAL NOT NULL,
                tolerance REAL NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(project_id, name)
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                model_id TEXT NOT NULL, profile_id TEXT NOT NULL, state_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
                event TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS webhook_endpoints (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                url TEXT NOT NULL, secret_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint_id TEXT NOT NULL,
                event TEXT NOT NULL, payload_json TEXT NOT NULL, signature TEXT NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                plan TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_counters (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                period TEXT NOT NULL, campaigns INTEGER NOT NULL DEFAULT 0,
                sensor_operations INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(project_id, period)
            );
            CREATE TABLE IF NOT EXISTS billing_events (
                event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def create_user(self, email: str, password: str) -> dict[str, Any]:
        if not email or len(password) < 8:
            raise ValueError("email and a password of at least 8 characters are required")
        user_id = f"user:{secrets.token_hex(12)}"
        self.connection.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, email.lower(), hash_secret(password), utc_now()))
        self.connection.commit()
        return {"id": user_id, "email": email.lower()}

    def authenticate_user(self, email: str, password: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        if row and verify_secret(password, row["password_hash"]):
            return {"id": row["id"], "email": row["email"]}
        return None

    def create_project(self, owner_id: str, name: str) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("project name is required")
        project_id = f"project:{secrets.token_hex(12)}"
        now = utc_now()
        self.connection.execute("INSERT INTO projects VALUES (?, ?, ?, ?)", (project_id, owner_id, name.strip(), now))
        self.connection.execute("INSERT INTO project_members VALUES (?, ?, 'owner')", (project_id, owner_id))
        self.connection.commit()
        return {"id": project_id, "name": name.strip(), "role": "owner"}

    def projects_for_user(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT p.id, p.name, m.role FROM projects p JOIN project_members m ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.created_at", (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def role(self, project_id: str, user_id: str) -> str | None:
        row = self.connection.execute("SELECT role FROM project_members WHERE project_id=? AND user_id=?", (project_id, user_id)).fetchone()
        return row["role"] if row else None

    def add_member(self, project_id: str, email: str, role: str) -> dict[str, Any]:
        if role not in {"owner", "operator", "viewer"}:
            raise ValueError("invalid role")
        row = self.connection.execute("SELECT id, email FROM users WHERE email=?", (email.lower(),)).fetchone()
        if not row:
            raise ValueError("user does not exist")
        self.connection.execute("INSERT OR REPLACE INTO project_members VALUES (?, ?, ?)", (project_id, row["id"], role))
        self.connection.commit()
        return {"email": row["email"], "role": role}

    def create_model(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        model_id = f"model:{secrets.token_hex(12)}"
        self.connection.execute("INSERT INTO sensor_models VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (model_id, project_id, body["name"], body["protocol"], body["measurement"], body["unit"], json.dumps(body.get("config", {})), utc_now()))
        self.connection.commit()
        return {"id": model_id, "project_id": project_id, **body}

    def models(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM sensor_models WHERE project_id=?", (project_id,)).fetchall()
        return [{"id": r["id"], "project_id": r["project_id"], "name": r["name"], "protocol": r["protocol"], "measurement": r["measurement"], "unit": r["unit"], "config": json.loads(r["config_json"])} for r in rows]

    def create_profile(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if body["max_offset"] <= 0 or body["tolerance"] <= 0:
            raise ValueError("profile limits must be positive")
        profile_id = f"profile:{secrets.token_hex(12)}"
        self.connection.execute("INSERT INTO calibration_profiles VALUES (?, ?, ?, ?, ?, ?, ?)", (profile_id, project_id, body["name"], body["unit"], body["max_offset"], body["tolerance"], utc_now()))
        self.connection.commit()
        return {"id": profile_id, "project_id": project_id, **body}

    def profiles(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM calibration_profiles WHERE project_id=?", (project_id,)).fetchall()
        return [{"id": r["id"], "project_id": r["project_id"], "name": r["name"], "unit": r["unit"], "max_offset": r["max_offset"], "tolerance": r["tolerance"]} for r in rows]

    def create_api_key(self, project_id: str, user_id: str, label: str) -> tuple[dict[str, Any], str]:
        raw = "iot_" + secrets.token_urlsafe(30)
        key_id = f"key:{secrets.token_hex(12)}"
        self.connection.execute("INSERT INTO api_keys VALUES (?, ?, ?, ?, ?, ?)", (key_id, project_id, user_id, label or "default", hash_secret(raw), utc_now()))
        self.connection.commit()
        return {"id": key_id, "project_id": project_id, "label": label or "default"}, raw

    def authenticate_key(self, raw: str) -> dict[str, Any] | None:
        for row in self.connection.execute("SELECT * FROM api_keys").fetchall():
            if verify_secret(raw, row["key_hash"]):
                role = self.role(row["project_id"], row["user_id"])
                return {"user_id": row["user_id"], "project_id": row["project_id"], "role": role}
        return None

    def create_session(self, user_id: str, ttl_seconds: int = 3600) -> str:
        if ttl_seconds < 60:
            raise ValueError("session lifetime is too short")
        token = "sess_" + secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, timezone.utc).isoformat().replace("+00:00", "Z")
        self.connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL)", (f"session:{secrets.token_hex(12)}", user_id, hash_secret(token), utc_now(), expires_at))
        self.connection.commit()
        return token

    def authenticate_session(self, raw: str) -> dict[str, Any] | None:
        now = utc_now()
        for row in self.connection.execute("SELECT * FROM sessions WHERE revoked_at IS NULL AND expires_at > ?", (now,)).fetchall():
            if verify_secret(raw, row["token_hash"]):
                return {"user_id": row["user_id"], "project_id": None, "role": None}
        return None

    def revoke_session(self, raw: str) -> None:
        now = utc_now()
        for row in self.connection.execute("SELECT id, token_hash FROM sessions WHERE revoked_at IS NULL").fetchall():
            if verify_secret(raw, row["token_hash"]):
                self.connection.execute("UPDATE sessions SET revoked_at=? WHERE id=?", (now, row["id"]))
                self.connection.commit()
                return

    def record_campaign(self, project_id: str, campaign_id: str, state: dict[str, Any], model_id: str, profile_id: str) -> None:
        now = utc_now()
        self.connection.execute("INSERT OR REPLACE INTO campaigns VALUES (?, ?, ?, ?, ?, ?, ?)", (campaign_id, project_id, model_id, profile_id, json.dumps(state), now, now))
        self.connection.commit()

    def campaign_state(self, project_id: str, campaign_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT state_json FROM campaigns WHERE project_id=? AND id=?", (project_id, campaign_id)).fetchone()
        return json.loads(row["state_json"]) if row else None

    def campaign_rows(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT id, model_id, profile_id, state_json, created_at, updated_at FROM campaigns WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
        return [{"id": r["id"], "model_id": r["model_id"], "profile_id": r["profile_id"], "created_at": r["created_at"], "updated_at": r["updated_at"], **json.loads(r["state_json"])} for r in rows]

    def create_webhook(self, project_id: str, url: str, secret: str) -> dict[str, Any]:
        if not url.strip() or not secret:
            raise ValueError("webhook URL and secret are required")
        endpoint_id = f"webhook:{secrets.token_hex(12)}"
        self.connection.execute("INSERT INTO webhook_endpoints VALUES (?, ?, ?, ?, ?)", (endpoint_id, project_id, url.strip(), hash_secret(secret), utc_now()))
        self.connection.commit()
        return {"id": endpoint_id, "project_id": project_id, "url": url.strip()}

    def webhooks(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT id, project_id, url, created_at FROM webhook_endpoints WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def record_webhook_delivery(self, endpoint_id: str, event: str, payload: dict[str, Any], signature: str, status: str = "recorded") -> dict[str, Any]:
        cursor = self.connection.execute("INSERT INTO webhook_deliveries(endpoint_id, event, payload_json, signature, status, created_at) VALUES (?, ?, ?, ?, ?, ?)", (endpoint_id, event, json.dumps(payload, sort_keys=True), signature, status, utc_now()))
        self.connection.commit()
        return {"id": cursor.lastrowid, "endpoint_id": endpoint_id, "event": event, "status": status}

    def webhook_deliveries(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT d.id, d.endpoint_id, d.event, d.signature, d.status, d.attempts, d.created_at FROM webhook_deliveries d JOIN webhook_endpoints e ON e.id=d.endpoint_id WHERE e.project_id=? ORDER BY d.created_at DESC", (project_id,)).fetchall()
        return [dict(row) for row in rows]

    def audit(self, project_id: str, event: str, payload: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO audit_events(project_id, event, payload_json, created_at) VALUES (?, ?, ?, ?)", (project_id, event, json.dumps(payload, sort_keys=True), utc_now()))
        self.connection.commit()

    def audit_events(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT id, event, payload_json, created_at FROM audit_events WHERE project_id=? ORDER BY id", (project_id,)).fetchall()
        return [{"id": r["id"], "event": r["event"], "payload": json.loads(r["payload_json"]), "created_at": r["created_at"]} for r in rows]

    def create_subscription(self, project_id: str, plan: str, status: str = "active") -> None:
        self.connection.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?)", (project_id, plan, status, utc_now()))
        self.connection.commit()

    def subscription(self, project_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT project_id, plan, status, updated_at FROM subscriptions WHERE project_id=?", (project_id,)).fetchone()
        return dict(row) if row else None

    def usage(self, project_id: str, period: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT campaigns, sensor_operations FROM usage_counters WHERE project_id=? AND period=?", (project_id, period)).fetchone()
        return {"project_id": project_id, "period": period, "campaigns": row["campaigns"] if row else 0, "sensor_operations": row["sensor_operations"] if row else 0}

    def increment_usage(self, project_id: str, period: str, field: str, amount: int) -> None:
        if field not in {"campaigns", "sensor_operations"} or amount < 0:
            raise ValueError("invalid usage counter")
        self.connection.execute("INSERT OR IGNORE INTO usage_counters(project_id, period) VALUES (?, ?)", (project_id, period))
        self.connection.execute(f"UPDATE usage_counters SET {field}={field}+? WHERE project_id=? AND period=?", (amount, project_id, period))
        self.connection.commit()

    def record_billing_event(self, event_id: str, payload: dict[str, Any]) -> bool:
        cursor = self.connection.execute("INSERT OR IGNORE INTO billing_events VALUES (?, ?, ?)", (event_id, json.dumps(payload, sort_keys=True), utc_now()))
        self.connection.commit()
        return cursor.rowcount == 1
