from __future__ import annotations

def production_gate(
    tests_passed: bool,
    security_passed: bool,
    consensus_passed: bool,
    owner_approved: bool
) -> dict:
    checks = {
        "tests_passed":tests_passed,
        "security_passed":security_passed,
        "consensus_passed":consensus_passed,
        "owner_approved":owner_approved
    }

    if not all(checks.values()):
        return {
            "status":"BLOCKED",
            "checks":checks,
            "reason":"All required production gates must pass."
        }

    return {
        "status":"APPROVED_FOR_DEPLOYMENT",
        "checks":checks
    }
