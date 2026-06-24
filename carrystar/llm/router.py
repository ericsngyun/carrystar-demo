"""LiteLLM model routing for the agent loop.

Frontier APIs from the orchestration spine: Haiku-class for triage, Claude-class
for messy/low-confidence parse repair. Carrystar is the non-regulated track, so
no local OSS / EVO-X2 here.

Every call is defensive: if CARRYSTAR_USE_LLM is off, or LiteLLM/network fails,
we fall back to deterministic heuristics so rehearsals never break offline. The
demo's correctness never depends on a live model — the model adds judgement on
top of a deterministic spine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from carrystar.config import settings

_ORDER_KEYWORDS = ("po", "p.o", "bol", "b/l", "order", "shipment", "ctn", "carton", "container", "eta", "etd")


@dataclass
class TriageDecision:
    decision: str   # "order" | "not_order"
    reason: str
    model: str      # which model produced it ("heuristic" when offline)
    is_order: bool


def triage_email(subject: str, account: str, has_attachments: bool) -> TriageDecision:
    """Is this inbound mail an order/shipment worth processing?"""
    if settings.use_llm:
        out = _triage_llm(subject, account, has_attachments)
        if out is not None:
            return out
    # Heuristic fallback.
    text = (subject or "").lower()
    keyword_hit = any(k in text for k in _ORDER_KEYWORDS)
    is_order = bool(has_attachments or keyword_hit)
    reason = (
        f"{'attachments present; ' if has_attachments else ''}"
        f"{'order keywords in subject' if keyword_hit else 'no order keywords'}"
    )
    return TriageDecision("order" if is_order else "not_order", reason, "heuristic", is_order)


def _triage_llm(subject: str, account: str, has_attachments: bool) -> TriageDecision | None:
    try:
        import litellm

        prompt = (
            "You are triaging inbound warehouse email. Decide if it is an order/shipment "
            "notice that should update the shipment tracker. Respond with strict JSON: "
            '{"is_order": bool, "reason": "<short>"}.\n\n'
            f"account: {account}\nsubject: {subject}\nhas_attachments: {has_attachments}"
        )
        resp = litellm.completion(
            model=settings.triage_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=120,
        )
        content = resp["choices"][0]["message"]["content"]
        data = json.loads(_extract_json(content))
        is_order = bool(data.get("is_order"))
        return TriageDecision(
            "order" if is_order else "not_order",
            str(data.get("reason", "")),
            settings.triage_model,
            is_order,
        )
    except Exception:  # noqa: BLE001 — any failure -> heuristic fallback
        return None


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end != -1 else "{}"
