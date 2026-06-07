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

Based on the evidence above, provide a structured incident diagnosis.

Respond in this exact format (do not add extra sections):

ROOT CAUSE:
<one or two sentences identifying the specific technical root cause>

CONFIDENCE: <HIGH|MEDIUM|LOW>

REMEDIATION STEPS:
1. <immediate action — what to do right now>
2. <short-term fix — within the hour>
3. <verification step — how to confirm the fix worked>
4. <preventive measure — to stop recurrence>

Do not repeat the evidence. Be specific about the service name and the exact metrics cited."""
