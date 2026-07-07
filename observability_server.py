# observability_server.py
"""
MCP server: Observability / Datadog Synthetics deprecated_auth_provider scanner

What this server provides:
- scan_synthetics_for_deprecated_auth_provider: inventory all Synthetics tests, detect deprecated_auth_provider high availability (deprecated_auth_provider) usage,
  classify (healthcheck vs token_dependent vs unknown), and group notification payloads by owner.

Required env vars (can be provided via .env):
- DD_API_KEY
- DD_APP_KEY
Optional:
- DD_SITE (e.g., datadoghq.com, datadoghq.eu, us3.datadoghq.com)

How .env works:
- Create a file named ".env" in the project root (same folder as this file)
- Put:
    DD_API_KEY=...
    DD_APP_KEY=...
    DD_SITE=datadoghq.com
- Do NOT commit .env (add it to .gitignore)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v1.api.synthetics_api import SyntheticsApi


# Load .env from the current working directory (VS Code workspace root)
# Safe to call even if no .env exists.
load_dotenv()


# -----------------------------
# MCP Server
# -----------------------------
mcp = FastMCP("observability-automation-server")


# -----------------------------
# Config / Patterns (tune these)
# -----------------------------
# Put your real deprecated_auth_provider hostnames here (regex is supported)
LEGACY_AUTH_HOST_PATTERNS = [
    r"\bdeprecated_auth_provider\.",         # deprecated_auth_provider.company.com
    r"\bdeprecated_auth_provider\.",      # legacy-deprecated_auth_provider-authentication.company.com
    # r"\bauth-vip4\.",   # example
]

# Endpoints that strongly indicate token/auth flow dependency
TOKEN_PATH_PATTERNS = [
    r"/oauth2?/token",
    r"/authorize",
    r"/introspect",
    r"/userinfo",
    r"/jwks",
    r"/\.well-known/openid-configuration",
]

# Endpoints that indicate "healthcheck-like" behavior
HEALTH_PATH_PATTERNS = [
    r"/health",
    r"/healthcheck",
    r"/ready",
    r"/live",
    r"/status",
]

# Token-ish fields that often appear in JSON assertions or extracted variables
TOKEN_BODY_KEYS = ["access_token", "id_token", "token_type", "expires_in"]


# -----------------------------
# Datadog client helpers
# -----------------------------
def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your terminal or add it to a .env file in the project root."
        )
    return v


def _dd_client() -> ApiClient:
    """
    Create Datadog API client using env vars.
    """
    cfg = Configuration()
    cfg.api_key["apiKeyAuth"] = _require_env("DD_API_KEY")
    cfg.api_key["appKeyAuth"] = _require_env("DD_APP_KEY")

    # DD_SITE support varies by client version.
    site = os.environ.get("DD_SITE")
    if site:
        try:
            cfg.server_variables["site"] = site
        except Exception:
            # If the installed client doesn't support server_variables["site"], ignore.
            pass

    return ApiClient(cfg)


def _synthetics_list_tests() -> List[Dict[str, Any]]:
    """Returns list of tests (lightweight)."""
    with _dd_client() as api_client:
        api = SyntheticsApi(api_client)
        resp = api.list_tests()
        tests = getattr(resp, "tests", None) or []
        return [t.to_dict() for t in tests]


def _synthetics_get_test(public_id: str) -> Dict[str, Any]:
    """Returns full test definition."""
    with _dd_client() as api_client:
        api = SyntheticsApi(api_client)
        resp = api.get_test(public_id)
        return resp.to_dict()


# -----------------------------
# Detection / Classification
# -----------------------------
def _flatten_strings(obj: Any, out: List[str]) -> None:
    """Collect all strings from nested structures (dict/list/str)."""
    if obj is None:
        return
    if isinstance(obj, str):
        out.append(obj)
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _flatten_strings(v, out)
        return
    if isinstance(obj, list):
        for v in obj:
            _flatten_strings(v, out)
        return


def _matches_any(text_lc: str, patterns: List[str]) -> bool:
    return any(re.search(p, text_lc) for p in patterns)


def _extract_candidate_strings(test_def: Dict[str, Any], cap: int = 4000) -> List[str]:
    strings: List[str] = []
    _flatten_strings(test_def, strings)

    uniq: List[str] = []
    seen = set()
    for s in strings:
        if not s or not isinstance(s, str):
            continue
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
        if len(uniq) >= cap:
            break
    return uniq


def _get_tags(test_def: Dict[str, Any]) -> List[str]:
    tags = test_def.get("tags") or []
    return tags if isinstance(tags, list) else []


def _resolve_owner(test_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort owner resolution.
    Prefer tags if present: owner:, team:
    Fallback: created_by / creator fields.
    """
    tags = _get_tags(test_def)
    owner: Dict[str, Any] = {"team": None, "handle": None, "source": None}

    for t in tags:
        tl = t.lower()
        if tl.startswith("team:") and not owner["team"]:
            owner["team"] = t.split(":", 1)[1].strip()
            owner["source"] = owner["source"] or "tag:team"
        if tl.startswith("owner:") and not owner["handle"]:
            owner["handle"] = t.split(":", 1)[1].strip()
            owner["source"] = owner["source"] or "tag:owner"

    creator = test_def.get("created_by") or test_def.get("creator")
    if not owner["handle"] and isinstance(creator, dict):
        owner["handle"] = creator.get("email") or creator.get("handle") or creator.get("name")
        owner["source"] = owner["source"] or "created_by"

    return owner


def _classify_deprecated_auth_provider_usage(test_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based classification:
    - healthcheck: deprecated_auth_provider present + health endpoint present + no token/auth signals
    - token_dependent: any token/auth signals
    - unknown: deprecated_auth_provider present but not enough to decide
    """
    texts = _extract_candidate_strings(test_def)

    uses_deprecated_auth_provider = False
    health_like = False
    token_like = False
    evidence: List[str] = []

    for s in texts:
        sl = s.lower()

        if _matches_any(sl, LEGACY_AUTH_HOST_PATTERNS):
            uses_deprecated_auth_provider = True
            if len(evidence) < 30:
                evidence.append(f"host match: {s}")

        if _matches_any(sl, HEALTH_PATH_PATTERNS):
            health_like = True
            if len(evidence) < 30:
                evidence.append(f"health-path match: {s}")

        if _matches_any(sl, TOKEN_PATH_PATTERNS):
            token_like = True
            if len(evidence) < 30:
                evidence.append(f"token-path match: {s}")

        if any(k in sl for k in TOKEN_BODY_KEYS):
            token_like = True
            if len(evidence) < 30:
                evidence.append(f"token-body-key match: {s}")

    if not uses_deprecated_auth_provider:
        return {"uses_deprecated_auth_provider": False}

    if health_like and not token_like:
        return {
            "uses_deprecated_auth_provider": True,
            "category": "healthcheck",
            "recommended_action": "disable_remove",
            "evidence": evidence[:20],
        }

    if token_like:
        return {
            "uses_deprecated_auth_provider": True,
            "category": "token_dependent",
            "recommended_action": "migrate_to_current_auth_provider",
            "evidence": evidence[:20],
        }

    return {
        "uses_deprecated_auth_provider": True,
        "category": "unknown",
        "recommended_action": "owner_review",
        "evidence": evidence[:20],
    }


def _group_notifications(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in findings:
        owner = r.get("owner") or {}
        key = owner.get("handle") or owner.get("team") or "unknown_owner"
        grouped.setdefault(key, []).append(r)

    notifications: List[Dict[str, Any]] = []
    for key, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: 0 if x.get("category") == "token_dependent" else 1)

        lines = [
            f"- {it.get('name')} ({it.get('test_id')}) — {it.get('category')} — {it.get('recommended_action')}"
            for it in items_sorted
        ]

        msg = (
            "Action required: Datadog Synthetic tests using deprecated authentication high availability (deprecated_auth_providerentication)\n\n"
            "Health-check tests can be disabled/removed.\n"
            "Token-dependent tests must be migrated to IdP3.\n\n"
            "Tests:\n" + "\n".join(lines)
        )

        notifications.append(
            {"owner_key": key, "tests": [it.get("test_id") for it in items_sorted], "message": msg}
        )

    return notifications


# -----------------------------
# MCP Tools
# -----------------------------
@mcp.tool()
def scan_synthetics_for_deprecated_auth_provider(limit: int = 2500) -> Dict[str, Any]:
    """
    Scan Datadog Synthetics tests for deprecated_auth_provider usage.
    """
    tests = _synthetics_list_tests()

    counts = {
        "tests_scanned": 0,
        "deprecated_auth_provider_tests": 0,
        "healthcheck": 0,
        "token_dependent": 0,
        "unknown": 0,
    }

    findings: List[Dict[str, Any]] = []

    for t in tests[: max(0, int(limit))]:
        public_id = t.get("public_id") or t.get("publicId") or t.get("id")
        if not public_id:
            continue

        counts["tests_scanned"] += 1

        try:
            full = _synthetics_get_test(str(public_id))
        except Exception as e:
            findings.append(
                {
                    "test_id": str(public_id),
                    "name": t.get("name"),
                    "type": t.get("type"),
                    "status": t.get("status"),
                    "error": f"Failed to fetch full test definition: {type(e).__name__}",
                    "category": "unknown",
                    "recommended_action": "owner_review",
                    "owner": {"team": None, "handle": None, "source": None},
                    "deprecated_auth_provider_evidence": [],
                    "tags": t.get("tags") or [],
                }
            )
            counts["unknown"] += 1
            continue

        classified = _classify_deprecated_auth_provider_usage(full)
        if not classified.get("uses_deprecated_auth_provider"):
            continue

        counts["deprecated_auth_provider_tests"] += 1
        cat = classified["category"]
        counts[cat] += 1

        findings.append(
            {
                "test_id": str(public_id),
                "name": full.get("name"),
                "type": full.get("type"),
                "status": full.get("status") or t.get("status"),
                "tags": _get_tags(full),
                "owner": _resolve_owner(full),
                "category": cat,
                "recommended_action": classified["recommended_action"],
                "deprecated_auth_provider_evidence": classified.get("evidence", []),
            }
        )

    return {
        "counts": counts,
        "findings": findings,
        "notifications": _group_notifications(findings),
        "deprecated_auth_provider_patterns": {
            "host_patterns": LEGACY_AUTH_HOST_PATTERNS,
            "token_path_patterns": TOKEN_PATH_PATTERNS,
            "health_path_patterns": HEALTH_PATH_PATTERNS,
        },
    }


if __name__ == "__main__":
    mcp.run()


