"""Authentication and project role helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.storage import Repository


@dataclass(frozen=True)
class Principal:
    user_id: str
    project_id: str | None = None
    role: str | None = None


class AuthService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def register(self, email: str, password: str) -> dict[str, Any]:
        return self.repository.create_user(email, password)

    def login(self, email: str, password: str) -> dict[str, Any]:
        user = self.repository.authenticate_user(email, password)
        if user is None:
            raise PermissionError("invalid credentials")
        return {**user, "access_token": self.repository.create_session(user["id"])}

    def authenticate(self, token: str, project_id: str | None = None) -> Principal:
        principal = self.repository.authenticate_key(token)
        if principal is None:
            principal = self.repository.authenticate_session(token)
        if principal is None:
            raise PermissionError("invalid credentials")
        if principal.get("project_id") is None:
            projects = self.repository.projects_for_user(principal["user_id"])
            selected = next((item for item in projects if item["id"] == project_id), None)
            if selected is None and len(projects) == 1:
                selected = projects[0]
            if selected is not None:
                principal = {**principal, "project_id": selected["id"], "role": selected["role"]}
        if not principal.get("role"):
            raise PermissionError("project selection is required")
        return Principal(principal["user_id"], principal["project_id"], principal["role"])

    def logout(self, token: str) -> None:
        self.repository.revoke_session(token)

    @staticmethod
    def require(principal: Principal, *roles: str) -> None:
        if principal.role not in roles:
            raise PermissionError("insufficient project role")
