from __future__ import annotations

import re
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple, Union

import hcl2
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ai-platform-observability-server")

# ============================
# Datadog Terraform Guardrails
# ============================

ALLOWED_ENV_PREFIXES = {
    "Dev", "QA", "Stage", "Prod", "Global",
    "Recovery", "Sandbox", "Lowers", "Perf"
}

ALLOWED_ENV_TAGS = {
    "production", "stage", "qa", "development", "personal",
    "sandbox", "performance", "recovery", "lower",
    "stable", "stablellm", "global",
}

ALLOWED_CREATED_USING = {
    "cli", "python", "terraform", "pulumi", "terragrunt", "console"
}

RECIPIENT_PATTERNS = ("@distro-", "@teams-", "@opsgenie-")


# ============================
# Helpers
# ============================

class HCLExpr:
    """Represents a raw HCL expression that should not be quoted."""
    def __init__(self, expr: str):
        self.expr = expr

    def __repr__(self) -> str:
        return f"HCLExpr({self.expr})"


def _looks_like_hcl_expr(s: str) -> bool:
    """
    Heuristic: treat certain strings as Terraform expressions, not string literals.
    Enables locals-based output and validation:
      - local.env_lower, local.env_short
      - ternary expressions
      - join(...) queries with for/split/trimspace patterns
    """
    s = s.strip()
    if not s:
        return False

    # interpolation or references
    if "${" in s:
        return True

    # Common Terraform references
    if re.match(r"^(local|var|data|module)\.[A-Za-z0-9_]+$", s):
        return True

    # Ternary expressions for recipients, etc.
    if ("?" in s and ":" in s and "[" in s and "]" in s):
        return True

    # HCL function expressions / comprehensions
    expr_starters = (
        "join(", "format(", "merge(", "coalesce(", "concat(", "tolist(",
        "tomap(", "zipmap(", "jsonencode(", "yamldecode(", "split(", "trimspace(",
    )
    if s.startswith(expr_starters):
        return True

    # Comprehension patterns often used in query style
    if "[for " in s or "for line in split" in s:
        return True

    return False


def _hcl(v: Any) -> str:
    """
    Render Python values to HCL.
    - Strings are quoted by default
    - HCLExpr is emitted raw
    - Strings that look like Terraform expressions are emitted raw
    """
    if v is None:
        return "null"

    if isinstance(v, HCLExpr):
        return v.expr

    if isinstance(v, bool):
        return "true" if v else "false"

    if isinstance(v, (int, float)):
        return str(v)

    if isinstance(v, str):
        if _looks_like_hcl_expr(v):
            return v
        return '"' + v.replace('"', '\\"') + '"'

    if isinstance(v, list):
        return "[" + ", ".join(_hcl(x) for x in v) + "]"

    if isinstance(v, dict):
        inner = ",\n".join([f'    "{k}" = {_hcl(val)}' for k, val in v.items()])
        return "{\n" + inner + "\n  }"

    return _hcl(str(v))


def _normalize_tags(tags: Any) -> Dict[str, str]:
    """
    Accept tags as:
    - dict: {"team":"x",...}
    - list of "k=v"
    - list of {"key":"k","value":"v"}
    - list of {"k":"team","v":"x"} style
    """
    if tags is None:
        return {}

    if isinstance(tags, dict):
        return {str(k): str(v) for k, v in tags.items()}

    if isinstance(tags, list):
        out: Dict[str, str] = {}
        for item in tags:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                out[k.strip()] = v.strip()
            elif isinstance(item, dict):
                if "key" in item and "value" in item:
                    out[str(item["key"]).strip()] = str(item["value"]).strip()
                elif "k" in item and "v" in item:
                    out[str(item["k"]).strip()] = str(item["v"]).strip()
        return out

    return {}


def _normalize_recipients(recipients: Any) -> Any:
    """
    Keep recipients as:
    - list[str] if it's a list or a simple string list
    - raw string expression if it looks like a Terraform expression (ternary, locals, etc.)
    """
    if recipients is None:
        return []

    if isinstance(recipients, str) and _looks_like_hcl_expr(recipients):
        return recipients  # keep expression

    if isinstance(recipients, list):
        return [str(x).strip() for x in recipients if str(x).strip()]

    if isinstance(recipients, str):
        parts = re.split(r"[,\n\s]+", recipients.strip())
        return [p for p in parts if p]

    return [str(recipients).strip()]


def _extract_recipients_from_message(msg: Any) -> List[str]:
    if not msg:
        return []
    s = str(msg)
    return sorted(set(re.findall(r"@(?:distro|teams|opsgenie)-[A-Za-z0-9_.-]+", s)))


def _guess_is_production(env: Any, tags: Dict[str, str], recipients: Any) -> bool:
    """
    Best-effort production detection:
    - tags.env literal production
    - env literal production
    - expressions mention == "production"
    """
    if tags.get("env") == "production":
        return True
    if isinstance(env, str) and env.strip() == "production":
        return True
    s = " ".join([str(env or ""), str(recipients or "")])
    return '== "production"' in s or "env:production" in s or "env: production" in s


def _indent(lines: List[str], n: int) -> str:
    pad = " " * n
    return "\n".join(pad + l for l in lines)


def _parse_first_module(obj: dict) -> Optional[Tuple[str, dict]]:
    """
    python-hcl2 sometimes returns:
      "module": { "name": {...} }
    or:
      "module": [ { "name": {...} }, ... ]
    """
    modules = obj.get("module")
    if not modules:
        return None

    if isinstance(modules, list):
        # take first module block in provided HCL snippet
        module_block = modules[0]
    elif isinstance(modules, dict):
        module_block = modules
    else:
        return None

    module_name, attrs = next(iter(module_block.items()))
    return module_name, attrs


def _parse_all_datadog_monitor_resources(obj: dict) -> List[Tuple[str, str, dict]]:
    """
    python-hcl2 resource shape is typically:
      "resource": [
        {"datadog_monitor": {"foo": {...}, "bar": {...}}}
      ]
    or dict variants.
    Return list of (resource_type, resource_name, attrs)
    """
    resources = obj.get("resource")
    if not resources:
        return []

    # Normalize to list[dict]
    blocks: List[dict] = []
    if isinstance(resources, list):
        blocks = resources
    elif isinstance(resources, dict):
        blocks = [resources]
    else:
        return []

    out: List[Tuple[str, str, dict]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for rtype, named in block.items():
            if rtype != "datadog_monitor":
                continue
            if isinstance(named, dict):
                for rname, attrs in named.items():
                    if isinstance(attrs, dict):
                        out.append((rtype, rname, attrs))
            elif isinstance(named, list):
                # uncommon, but handle
                for item in named:
                    if isinstance(item, dict):
                        for rname, attrs in item.items():
                            if isinstance(attrs, dict):
                                out.append((rtype, rname, attrs))
    return out


# ============================
# Core Compliance Validator
# ============================

def validate_monitor_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates a *module-style monitor spec* against the compliance guardrails you provided.
    Supports locals/ternary expressions best-effort.

    This is used by:
      - module generator tool
      - module HCL validator tool (module blocks)
      - resource validator tool (via resource->spec mapping)
    """
    errors: List[str] = []
    warnings: List[str] = []

    use_locals = bool(spec.get("use_locals", False))

    # Normalize fields for consistent checks
    recipients = _normalize_recipients(spec.get("recipients", []))
    tags = _normalize_tags(spec.get("tags", {}))

    # If user provided repo, map to required source_code tag if missing
    if "source_code" not in tags and spec.get("repo"):
        tags["source_code"] = str(spec["repo"]).strip()

    # If use_locals=true and env tag missing, set it to local.env_lower (do NOT overwrite if user set)
    if use_locals and "env" not in tags:
        tags["env"] = "local.env_lower"

    spec["recipients"] = recipients
    spec["tags"] = tags

    # Required fields (module_source is required only for module generation/validation; resource validation can pass None)
    required = ["name", "type", "query", "env_prefix", "tags", "thresholds"]
    for k in required:
        if k not in spec or spec[k] in (None, "", []):
            errors.append(f"Missing required field: {k}")

    # env is required for module blocks; for raw resources we infer from tags.env.
    if "env" not in spec or spec["env"] in (None, "", []):
        # attempt to infer
        inferred_env = tags.get("env")
        if inferred_env:
            spec["env"] = inferred_env
        else:
            errors.append("Missing required field: env")

    # recipients is required for module blocks; for raw resources we may infer from message
    if "recipients" not in spec or spec["recipients"] in (None, "", []):
        errors.append("Missing required field: recipients")

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}

    name = str(spec["name"]).strip()
    env = spec.get("env")
    env_prefix = spec.get("env_prefix")

    if not name:
        errors.append("Monitor name cannot be empty.")

    # env_prefix validation (only when literal)
    env_prefix_is_expr = isinstance(env_prefix, str) and _looks_like_hcl_expr(env_prefix)
    if not env_prefix_is_expr:
        env_prefix_str = str(env_prefix).strip()
        if env_prefix_str not in ALLOWED_ENV_PREFIXES:
            errors.append(f"env_prefix must be one of: {sorted(ALLOWED_ENV_PREFIXES)}")
        if name and not re.search(rf"^{re.escape(env_prefix_str)}\b", name):
            errors.append("Monitor name must begin with the configured env_prefix.")
    else:
        # locals mode hint
        if use_locals and "${local.env_short}" not in name:
            warnings.append("use_locals=true: name should typically start with ${local.env_short}.")

    # Recipient patterns (works for list or expression)
    joined_recipients = " ".join(recipients) if isinstance(recipients, list) else str(recipients)
    if not any(x in joined_recipients for x in RECIPIENT_PATTERNS):
        errors.append(
            "Monitor recipients must include at least one valid recipient: @distro-*, @teams-*, or @opsgenie-*."
        )

    # Production rule: require opsgenie for prod, including ternary prod branch if detectable
    is_production_literal = isinstance(env, str) and env.strip() == "production"
    is_production_guess = _guess_is_production(env, tags, recipients)

    def _prod_branch_has_opsgenie(expr: str) -> bool:
        m = re.search(r'\?\s*\[(.*?)\]\s*:\s*\[', expr, flags=re.S)
        if not m:
            return "@opsgenie-" in expr
        prod_branch = m.group(1)
        return "@opsgenie-" in prod_branch

    if is_production_literal:
        if "@opsgenie-" not in joined_recipients:
            errors.append("Production monitors must include at least one @opsgenie-* recipient.")
    else:
        # env is not a literal "production"; try to validate prod branch if expression includes it
        if isinstance(recipients, str) and '== "production"' in recipients and "?" in recipients:
            if not _prod_branch_has_opsgenie(recipients):
                errors.append(
                    "Production monitors must include at least one @opsgenie-* recipient "
                    "(prod branch of conditional recipients)."
                )
        else:
            # We can't be certain; warn if it smells like prod but we can't confirm opsgenie.
            if is_production_guess and "@opsgenie-" not in joined_recipients:
                warnings.append(
                    "Monitor appears to be production (or contains production logic), but no @opsgenie-* recipient "
                    "was detected. If recipients are computed via locals, ensure prod includes opsgenie."
                )

    # Required tags
    required_tags = {"team", "env", "service", "created_using", "source_code"}
    missing = [t for t in required_tags if t not in tags]
    if missing:
        errors.append(f"Missing required tags: {missing}")

    # Validate env tag only if literal
    env_tag = str(tags.get("env", ""))
    if env_tag and not _looks_like_hcl_expr(env_tag):
        if env_tag not in ALLOWED_ENV_TAGS:
            errors.append(f"env tag must be one of: {sorted(ALLOWED_ENV_TAGS)}")

    # created_using validation
    if tags.get("created_using") not in ALLOWED_CREATED_USING:
        errors.append(f"created_using tag must be one of: {sorted(ALLOWED_CREATED_USING)}")

    # source_code validation
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", str(tags.get("source_code", ""))):
    errors.append("source_code tag must be in the form owner/repository-name.")

    # Missing-data conflict (same as Terraform check block)
    on_missing_data = spec.get("on_missing_data")
    notify_no_data = spec.get("notify_no_data")
    no_data_timeframe = spec.get("no_data_timeframe")
    if on_missing_data is not None and (notify_no_data is True or no_data_timeframe is not None):
        errors.append(
            "Invalid monitor configuration: on_missing_data conflicts with notify_no_data/no_data_timeframe. "
            "If on_missing_data is set, notify_no_data must be false and no_data_timeframe must be null."
        )

    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ============================
# HCL → Validator Tools
# ============================

@mcp.tool()
def ddtf_validate_monitor_hcl(hcl: str) -> dict:
    """
    Validate an existing Terraform monitor block for compliance.

    You can paste EITHER:
      A) module "x" { ... }   (datadog-common-module-templates monitor module)
      B) resource "datadog_monitor" "x" { ... }

    Returns:
      - ok/errors/warnings
      - detected kind: module|resource
      - name: module/resource name
    """
    try:
        obj = hcl2.load(StringIO(hcl))
    except Exception as e:
        return {"ok": False, "errors": [f"HCL parse error: {e}"], "warnings": []}

    # Try module first
    mod = _parse_first_module(obj)
    if mod:
        module_name, attrs = mod
        spec = {
            "module_source": attrs.get("source"),
            "name": attrs.get("name"),
            "type": attrs.get("type"),
            "query": attrs.get("query"),
            "env": attrs.get("env"),
            "env_prefix": attrs.get("env_prefix"),
            "recipients": attrs.get("recipients"),
            "tags": attrs.get("tags"),
            "thresholds": attrs.get("thresholds"),
            "on_missing_data": attrs.get("on_missing_data"),
            "notify_no_data": attrs.get("notify_no_data"),
            "no_data_timeframe": attrs.get("no_data_timeframe"),
        }
        result = validate_monitor_spec(spec)
        result.update(
            {
                "kind": "module",
                "module_name": module_name,
                "notes": [
                    "Validation mirrors the standard Datadog monitor module guardrails.",
                    "Conditional/locals expressions are validated best-effort (pattern-based).",
                ],
            }
        )
        return result

    # Else try resource datadog_monitor
    resources = _parse_all_datadog_monitor_resources(obj)
    if not resources:
        return {"ok": False, "errors": ["No module block or datadog_monitor resource found."], "warnings": []}

    # Validate first resource in snippet (common paste behavior)
    _rtype, rname, attrs = resources[0]
    spec = _resource_monitor_to_spec(rname, attrs)
    result = validate_monitor_spec(spec)
    result.update(
        {
            "kind": "resource",
            "resource_name": rname,
            "notes": [
                "Resource validation infers env from tags.env and recipients from @mentions in message.",
                "If recipients/tags/env are dynamic via locals, results may include warnings.",
            ],
        }
    )
    return result


def _resource_monitor_to_spec(resource_name: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a raw datadog_monitor resource into the same validation spec shape.
    - env inferred from tags.env
    - env_prefix inferred from name prefix if possible
    - recipients inferred from @mentions in message
    """
    tags = _normalize_tags(attrs.get("tags", {}))
    msg = attrs.get("message")

    env = tags.get("env", "")
    env_prefix_guess = ""
    monitor_name = str(attrs.get("name", "") or "")
    for p in ALLOWED_ENV_PREFIXES:
        if monitor_name.startswith(p):
            env_prefix_guess = p
            break

    # thresholds: Datadog TF uses monitor_thresholds block; hcl2 may parse it in different shapes.
    thresholds = attrs.get("thresholds")
    if thresholds is None:
        thresholds = attrs.get("monitor_thresholds")

    # query may be under "query"
    query = attrs.get("query")

    return {
        "module_source": None,  # not applicable
        "name": attrs.get("name"),
        "type": attrs.get("type"),
        "query": query,
        "message": msg,
        "priority": attrs.get("priority"),
        "notify_no_data": attrs.get("notify_no_data"),
        "no_data_timeframe": attrs.get("no_data_timeframe"),
        "on_missing_data": attrs.get("on_missing_data"),
        "env": env,
        "env_prefix": env_prefix_guess,
        "recipients": _extract_recipients_from_message(msg),
        "tags": tags,
        "thresholds": thresholds,
    }


# ============================
# Generator (Module Call)
# ============================

def _localsify_monitor_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    If use_locals=true, convert certain fields to locals-based expressions:
      - env        -> local.env_lower
      - env_prefix -> local.env_short
      - tags.env   -> local.env_lower (only if missing or already expression)
      - name       -> "${local.env_short} <base name>" (avoid double prefix)
    """
    use_locals = bool(spec.get("use_locals", False))
    if not use_locals:
        return spec

    spec["env"] = "local.env_lower"
    spec["env_prefix"] = "local.env_short"

    name = str(spec.get("name", "")).strip()
    if "${local.env_short}" not in name:
        name = re.sub(r"^(Dev|QA|Stage|Prod|Global|Recovery|Sandbox|Lowers|Perf)\s+", "", name)
        spec["name"] = f"${{local.env_short}} {name}".strip()

    tags = _normalize_tags(spec.get("tags", {}))
    if "env" not in tags or _looks_like_hcl_expr(str(tags.get("env", ""))):
        tags["env"] = "local.env_lower"
    spec["tags"] = tags

    return spec


def render_monitor_module_call(spec: Dict[str, Any]) -> Dict[str, Any]:
    spec = _localsify_monitor_spec(spec)

    module_name = spec.get(
        "module_name",
        "ddmon_" + re.sub(r"[^a-z0-9]+", "_", str(spec["name"]).lower())[:45].strip("_"),
    )

    tags = _normalize_tags(spec.get("tags"))
    service = tags.get("service", "service")
    filename = spec.get("filename", f"monitors/{service}/{module_name}.tf")

    keys = [
        "name", "type", "query", "message", "priority",
        "notify_no_data", "no_data_timeframe", "on_missing_data",
        "renotify_interval", "evaluation_delay",
        "renotify_statuses", "include_tags", "require_full_window",
        "enable_logs_sample", "groupby_simple_monitor",
        "new_group_delay", "thresholds", "tags", "extra_tags",
        "env", "env_prefix", "recipients",
    ]

    lines = [
        f'module "{module_name}" {{',
        f'  source = {_hcl(spec["module_source"])}',
    ]

    for k in keys:
        if spec.get(k) is not None:
            lines.append(f"  {k} = {_hcl(spec[k])}")

    lines.append("}")
    return {"filename": filename, "hcl": "\n".join(lines) + "\n"}


@mcp.tool()
def ddtf_generate_monitor_module_call(spec: dict) -> dict:
    """
    Generate a compliant Datadog monitor module call.

    Required inputs for generation:
      - module_source (the approved monitor module)
      - name, type, query, env, env_prefix, recipients, tags, thresholds

    Tip:
      set "use_locals": true to emit locals-based style:
        env        = local.env_lower
        env_prefix = local.env_short
        tags.env   = local.env_lower
        name       = "${local.env_short} ..."
    """
    # Ensure module_source present for generation
    if not spec.get("module_source"):
        return {
            "ok": False,
            "errors": ["Missing required field: module_source (required for module generation)."],
            "warnings": [],
        }

    v = validate_monitor_spec(spec)
    if not v["ok"]:
        return {"ok": False, **v}

    out = render_monitor_module_call(spec)
    return {
        "ok": True,
        **out,
        "notes": [
            "Generated module satisfies all compliance guardrails (best-effort for locals/conditionals).",
            "If use_locals=true, env/env_prefix/tags.env/name are rendered using locals.",
        ],
    }


# ============================
# GitHub Actions CI/CD
# ============================

@mcp.tool()
def gha_generate_workflow(spec: dict) -> dict:
    """
    Generate a GitHub Actions CI workflow YAML.

    Input spec example:
    {
      "name": "CI",
      "language": "python | node | dotnet | java | go",
      "runs_on": "ubuntu-latest",
      "default_branch": "main"
    }

    Output:
      - path: .github/workflows/ci.yml
      - yaml: workflow contents
    """
    name = spec.get("name", "CI")
    runs_on = spec.get("runs_on", "ubuntu-latest")
    branch = spec.get("default_branch", "main")
    language = (spec.get("language") or "python").lower()

    steps = ["- uses: actions/checkout@v4"]

    if language == "python":
        steps += [
            "- uses: actions/setup-python@v5",
            "  with:",
            "    python-version: '3.11'",
            "- run: pip install -r requirements.txt",
            "- run: pytest -q",
        ]
    elif language == "node":
        steps += [
            "- uses: actions/setup-node@v4",
            "  with:",
            "    node-version: '20'",
            "- run: npm ci",
            "- run: npm test --silent",
        ]
    else:
        steps += [
            "- name: Build/Test (placeholder)",
            "  run: echo 'Add build steps for your stack'",
        ]

    yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branch}]
  push:
    branches: [{branch}]
  workflow_dispatch:

jobs:
  build:
    runs-on: {runs_on}
    steps:
{_indent(steps, 6)}
"""
    return {"path": ".github/workflows/ci.yml", "yaml": yaml}


# ============================
# Prompts (Slash Commands)
# ============================

@mcp.prompt()
def datadog_monitor() -> str:
    return (
        "You are the Datadog Terraform compliance agent.\n"
        "Monitors may be implemented either as:\n"
        "  1) a module call to an approved Datadog monitor module\n"
        "  2) a raw resource \"datadog_monitor\"\n"
        "Validate BOTH styles using the SAME guardrails:\n"
        "- missing-data conflict rules\n"
        "- env_prefix/name prefix\n"
        "- recipients (@teams/@opsgenie/@distro), prod requires @opsgenie\n"
        "- required tags team/env/service/created_using/source_code\n"
        "Do not confuse the shared monitor module with a consuming infrastructure repository.\n"
    )

@mcp.prompt()
def github_actions_pipeline() -> str:
    return (
        "You are the GitHub Actions CI/CD agent.\n"
        "Generate a production-ready workflow under .github/workflows/ci.yml.\n"
        "Ask for stack details and test command if missing.\n"
    )
def _ensure_stdio_open() -> None:
    """
    Fix for container/K8s cases where uvicorn logging crashes with:
      ValueError: I/O operation on closed file
    """
    import os
    import sys

    def _fix(stream, fd: int):
        try:
            stream.fileno()
            _ = stream.isatty()
            return stream
        except Exception:
            return os.fdopen(fd, "w", buffering=1, closefd=False)

    sys.stdout = _fix(sys.stdout, 1)
    sys.stderr = _fix(sys.stderr, 2)


if __name__ == "__main__":
    import os
    import uvicorn

    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    # VS Code MCP (mcp.json) uses stdio, keep that path unchanged
    if transport == "stdio":
        mcp.run()
        raise SystemExit(0)

    # Docker/Kubernetes demo path: run SSE over HTTP via uvicorn bound to 0.0.0.0
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    # Get an ASGI app from FastMCP (different SDK versions expose different attributes)
    app = None

    # Most common: method that returns a Starlette/FastAPI ASGI app for SSE
    if hasattr(mcp, "sse_app") and callable(getattr(mcp, "sse_app")):
        app = mcp.sse_app()
    # Some versions expose a generic "app" directly
    elif hasattr(mcp, "app"):
        app = getattr(mcp, "app")
    # Some versions expose an ASGI app attribute
    elif hasattr(mcp, "asgi_app"):
        app = getattr(mcp, "asgi_app")

    if app is None:
        raise RuntimeError(
            "Could not find an ASGI app on FastMCP. "
            "Tried: sse_app(), app, asgi_app. "
            "Upgrade mcp or adjust app exposure."
        )

    # Avoid uvicorn logging formatter issues in some containers by disabling uvicorn log config
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)





