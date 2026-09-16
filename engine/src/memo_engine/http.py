from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SupabaseRest:
    """Tiny Phase 0 REST client using only the Python standard library.

    Uses Supabase's modern server-side secret key through the `apikey` header.
    Do not send an sb_secret_... key as an Authorization Bearer token: it is
    not a JWT.
    """

    def __init__(self) -> None:
        self.base = os.environ["SUPABASE_URL"].rstrip("/")
        self.secret = os.environ["SUPABASE_SECRET_KEY"]

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self.secret,
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer

        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Supabase HTTP {exc.code}") from exc

        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get_job(self, job_id: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(job_id, safe="")
        rows = self._request("GET", f"/rest/v1/jobs?id=eq.{encoded}&select=*")
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("Job not found or not unique")
        return rows[0]

    def patch_job(
        self,
        job_id: str,
        expected_status: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        encoded = urllib.parse.quote(job_id, safe="")
        status = urllib.parse.quote(expected_status, safe="")
        rows = self._request(
            "PATCH",
            f"/rest/v1/jobs?id=eq.{encoded}&status=eq.{status}",
            body=values,
            prefer="return=representation",
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("Job transition rejected")
        return rows[0]

    def add_event(
        self,
        job: dict[str, Any],
        event_type: str,
        stage: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._request(
            "POST",
            "/rest/v1/job_events",
            body={
                "job_id": job["id"],
                "user_id": job["user_id"],
                "event_type": event_type,
                "stage": stage,
                "payload": payload or {},
            },
        )
