from __future__ import annotations

import os
import re
import urllib.error
from dataclasses import dataclass
from typing import Any

from .ai_router import ProviderError
from .http import SupabaseRest

MODEL = "gpt-6-luna"
PILOT_JOB = "9544a589-ef6f-4f52-946b-a29ac0cdab43"
PBHS_URL = "https://njrqiurqljwtuqrvguhj.supabase.co"
BUCKET = "memo-files"
LEDGER = "phase85-included-credit/2026-11-26"
SLOT_CEILING_NUSD = 20_000_000
SLOT_COUNT = 100


def _enabled(env: Any, name: str) -> bool:
    return env.get(name, "").strip().lower() == "true"


def credit_eligible(env: Any) -> bool:
    return bool(
        _enabled(env, "MEMO_OPENAI_INCLUDED_CREDIT_CONFIRMED")
        and re.fullmatch(r"org[-_][a-zA-Z0-9_-]+", env.get("MEMO_OPENAI_ORGANIZATION", ""))
        and re.fullmatch(r"proj_[a-zA-Z0-9_-]+", env.get("MEMO_OPENAI_PROJECT", ""))
        and env.get("OPENAI_API_KEY", "").strip()
    )


def private_job_enabled(env: Any, job_id: str | None) -> bool:
    return (
        job_id == PILOT_JOB
        and _enabled(env, "MEMO_OPENAI_SCHOOL_PRIVATE_APPROVED")
        and env.get("MEMO_PRIVACY_MODE", "APPROVED_EXTERNAL_ONLY").upper() == "APPROVED_EXTERNAL_ONLY"
        and env.get("SUPABASE_URL", "").rstrip("/") == PBHS_URL
    )


@dataclass(frozen=True)
class Reservation:
    slot: int
    request_ceiling_nusd: int


class CreditLedger:
    """Immutable per-request reservations shared by qualification and worker runs.

    Each storage slot is claimed with x-upsert=false. Only the winning writer may
    make its one POST. A crashed or uncertain request still consumes its slot.
    One hundred slots at at most $0.02 each bound the entire phase to $2.
    """

    def __init__(self, db: SupabaseRest, *, synthetic: bool = False) -> None:
        if db.base != PBHS_URL:
            raise ProviderError("OPENAI_LEDGER_TARGET_INVALID", "The credit ledger project is not approved.")
        self.db = db
        self.synthetic = synthetic
        self.next_slot = 2

    def reserve(self, stage: str, request_ceiling_nusd: int) -> Reservation:
        if not 0 < request_ceiling_nusd <= SLOT_CEILING_NUSD:
            raise ProviderError("OPENAI_REQUEST_BUDGET_EXCEEDED", "The request exceeds its credit reservation.")
        if self.synthetic:
            slots = (0,) if stage == "visual" else (1,)
        else:
            slots = range(self.next_slot, SLOT_COUNT)
        for slot in slots:
            path = f"{LEDGER}/{slot:03d}-reservation.json"
            try:
                self.db.upload_json(BUCKET, path, {
                    "stage": stage,
                    "synthetic": self.synthetic,
                    "model": MODEL,
                    "request_ceiling_nusd": request_ceiling_nusd,
                    "slot_ceiling_nusd": SLOT_CEILING_NUSD,
                }, upsert=False)
            except Exception as exc:
                http_error = exc.__cause__
                if isinstance(http_error, urllib.error.HTTPError) and (
                    http_error.code == 409
                    or (http_error.code == 400 and "already exists" in str(exc).lower())
                ):
                    continue
                raise ProviderError("OPENAI_LEDGER_UNAVAILABLE", "The credit reservation could not be verified.") from None
            if not self.synthetic:
                self.next_slot = slot + 1
            return Reservation(slot, request_ceiling_nusd)
        raise ProviderError("OPENAI_CREDIT_BUDGET_EXHAUSTED", "The included-credit request allowance is exhausted.")

    def finish(self, reservation: Reservation, receipt: dict[str, Any]) -> None:
        try:
            self.db.upload_json(BUCKET, f"{LEDGER}/{reservation.slot:03d}-receipt.json", receipt, upsert=False)
        except Exception:
            raise ProviderError("OPENAI_LEDGER_UNAVAILABLE", "The credit receipt could not be stored.") from None
