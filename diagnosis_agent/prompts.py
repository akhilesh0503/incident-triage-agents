from __future__ import annotations

from typing import Any


def build_diagnosis_prompt(
    alert_description: str,
    service: str,
    log_findings: dict[str, Any],
    metrics_findings: dict[str, Any],
    deployment_findings: dict[str, Any],
) -> str:
    sections: list[str] = []

    sections.append(f"ALERT: {alert_description}")
    sections.append(f"AFFECTED SERVICE: {service}")

    # Metrics section
    anomalies = metrics_findings.get("anomalies", [])
    if anomalies:
        lines = ["METRIC ANOMALIES:"]
        for a in anomalies:
            lines.append(
                f"  - {a['metric']}: current_max={a['current_max']}, "
                f"baseline={a['baseline']}, change={a['pct_change']}%, "
                f"severity={a['severity']}"
            )
        sections.append("\n".join(lines))
    else:
        sections.append("METRICS: All within normal range")

    # Logs section
    log_error_count = log_findings.get("error_count", 0)
    log_patterns = log_findings.get("findings", [])
    if log_patterns:
        lines = [f"LOG ERRORS ({log_error_count} total in window):"]
        for f in log_patterns[:5]:
            sample = f["sample_messages"][0] if f["sample_messages"] else ""
            lines.append(f"  - pattern={f['pattern']}, count={f['count']}, example: \"{sample}\"")
        sections.append("\n".join(lines))
    else:
        lines = [f"LOGS: {log_error_count} errors, no matching error patterns"]
        sections.append("\n".join(lines))

    # Deployment section
    deploy_score = deployment_findings.get("correlation_score", 0)
    deploy_reason = deployment_findings.get("correlation_reason", "")
    recent_deploys = deployment_findings.get("recent_deployments", [])
    if recent_deploys:
        latest = recent_deploys[0]
        sections.append(
            f"RECENT DEPLOYMENT: version={latest.get('version')}, "
            f"status={latest.get('status')}, "
            f"correlation_score={deploy_score}/100 — {deploy_reason}"
        )
    else:
        sections.append(f"DEPLOYMENTS: {deploy_reason}")

    evidence_block = "\n\n".join(sections)

    return f"""{evidence_block}

You are an SRE diagnosing a production incident for {service}.
Write your diagnosis below. Every answer must be a complete sentence — no blank answers.

ROOT CAUSE:
The root cause is

CONFIDENCE: HIGH

REMEDIATION STEPS:
1.
2.
3.
4.

Rules:
- ROOT CAUSE must name {service}, the failure mode, and what caused it.
- Step 1 must be an action to take right now (restart, rollback, scale, etc).
- Step 2 must fix the underlying cause within the hour.
- Step 3 must name a specific metric or log to confirm recovery.
- Step 4 must prevent recurrence (alerting threshold, config change, code fix).
- Do NOT repeat these rules in your answer. Just write the diagnosis."""
