from __future__ import annotations
from pathlib import Path

POLICY_NAMES = [
    "Terms & Conditions",
    "Privacy Policy",
    "Community Guidelines",
    "Moderation Policy",
    "Data Retention Policy",
    "Refund/Payment Policy"
]

def policy_requirement() -> dict:
    return {
        "required": POLICY_NAMES,
        "rule": "Never invent a policy rule.",
        "version_required": True
    }
