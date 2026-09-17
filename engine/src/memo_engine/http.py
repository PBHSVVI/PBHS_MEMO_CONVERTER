from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SupabaseRest:
    """Small server-side Supabase REST/Storage client for the hosted worker."""

    def __init__(self) -> None:
        self.base = os.environ["SUPABASE_URL"].rstrip("/")
        self.secret = os.environ["SUPABASE_SECRET_KEY"]

    def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        prefer: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> bytes:
        headers = {"apikey": self.secret}
        if body is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
        if prefer:
            headers["Prefer"] = prefer
        if extra_headers:
            headers.update(extra_headers)

        req = urllib.request.Request(
            f"{self.base}{path}",
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(512).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Supabase HTTP {exc.code} for {method} {path}: {detail}"
            ) from exc

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        raw = self._request_bytes(
            method,
            path,
            body=None if body is None else json.dumps(body).encode("utf-8"),
            content_type="application/json",
            prefer=prefer,
        )
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def get_job(self, job_id: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(job_id, safe="")
        rows = self._request_json(
            "GET",
            f"/rest/v1/jobs?id=eq.{encoded}&select=*",
        )
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
        rows = self._request_json(
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
        self._request_json(
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

    def download_object(self, bucket: str, object_path: str) -> bytes:
        bucket_q = urllib.parse.quote(bucket, safe="")
        path_q = urllib.parse.quote(object_path, safe="/")
        return self._request_bytes(
            "GET",
            f"/storage/v1/object/{bucket_q}/{path_q}",
        )

    def upload_object(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        *,
        content_type: str,
        upsert: bool = True,
    ) -> None:
        bucket_q = urllib.parse.quote(bucket, safe="")
        path_q = urllib.parse.quote(object_path, safe="/")
        self._request_bytes(
            "POST",
            f"/storage/v1/object/{bucket_q}/{path_q}",
            body=data,
            content_type=content_type,
            extra_headers={"x-upsert": "true" if upsert else "false"},
        )

    def upload_json(
        self,
        bucket: str,
        object_path: str,
        value: Any,
        *,
        upsert: bool = True,
    ) -> None:
        data = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.upload_object(
            bucket,
            object_path,
            data,
            content_type="application/json",
            upsert=upsert,
        )
