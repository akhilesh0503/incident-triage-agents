-- Services being monitored
CREATE TABLE IF NOT EXISTS services (
    id          SERIAL       PRIMARY KEY,
    name        VARCHAR(60)  NOT NULL UNIQUE,
    team        VARCHAR(60),
    port        INTEGER,
    language    VARCHAR(30),
    repo_url    TEXT
);

-- Deployment history
CREATE TABLE IF NOT EXISTS deployments (
    id           SERIAL       PRIMARY KEY,
    service      VARCHAR(60)  NOT NULL,
    version      VARCHAR(40)  NOT NULL,
    deployed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deployed_by  VARCHAR(60),
    commit_sha   VARCHAR(40),
    status       VARCHAR(20)  NOT NULL DEFAULT 'success',  -- success | failed | rolled_back
    notes        TEXT
);

-- Application logs (structured)
CREATE TABLE IF NOT EXISTS logs (
    id          BIGSERIAL    PRIMARY KEY,
    service     VARCHAR(60)  NOT NULL,
    level       VARCHAR(10)  NOT NULL,  -- DEBUG INFO WARN ERROR CRITICAL
    message     TEXT         NOT NULL,
    trace_id    VARCHAR(40),
    logged_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Time-series metrics snapshots
CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id           BIGSERIAL    PRIMARY KEY,
    service      VARCHAR(60)  NOT NULL,
    metric_name  VARCHAR(60)  NOT NULL,
    value        NUMERIC(12,4) NOT NULL,
    unit         VARCHAR(20),
    recorded_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Incident records (written by DiagnosisAgent)
CREATE TABLE IF NOT EXISTS incidents (
    id                SERIAL       PRIMARY KEY,
    service           VARCHAR(60)  NOT NULL,
    alert_description TEXT         NOT NULL,
    root_cause        TEXT,
    confidence        VARCHAR(10),             -- HIGH | MEDIUM | LOW
    remediation       JSONB,                   -- ordered list of remediation step strings
    agents_consulted  JSONB,                   -- list of agent names that contributed evidence
    status            VARCHAR(20)  NOT NULL DEFAULT 'open',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_logs_service_time   ON logs(service, logged_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_level          ON logs(level);
CREATE INDEX IF NOT EXISTS idx_metrics_service     ON metrics_snapshots(service, metric_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service, deployed_at DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_created   ON incidents(created_at DESC);

-- ── Seed data ────────────────────────────────────────────────────────────────

INSERT INTO services (name, team, port, language, repo_url) VALUES
    ('api-gateway',      'platform',  443,  'Go',     'https://github.com/example/api-gateway'),
    ('user-service',     'backend',   8080, 'Python', 'https://github.com/example/user-service'),
    ('payment-service',  'fintech',   8081, 'Java',   'https://github.com/example/payment-service'),
    ('auth-service',     'security',  8082, 'Python', 'https://github.com/example/auth-service'),
    ('db-proxy',         'data',      5432, 'Rust',   'https://github.com/example/db-proxy')
ON CONFLICT DO NOTHING;

-- Deployment history: last 7 days of normal deploys
INSERT INTO deployments (service, version, deployed_at, deployed_by, commit_sha, status)
SELECT
    s.service,
    'v' || (2 + (n % 5)) || '.' || (n % 10) || '.0',
    NOW() - (n * INTERVAL '18 hours'),
    CASE n % 3 WHEN 0 THEN 'alice' WHEN 1 THEN 'bob' ELSE 'carol' END,
    md5(s.service || n::text),
    'success'
FROM
    (VALUES ('api-gateway'),('user-service'),('payment-service'),('auth-service'),('db-proxy')) AS s(service),
    generate_series(1, 8) AS n;

-- Baseline metrics: last 2 hours of normal readings (every 30s)
INSERT INTO metrics_snapshots (service, metric_name, value, unit, recorded_at)
SELECT
    s.service,
    m.metric,
    CASE m.metric
        WHEN 'cpu_percent'      THEN 20 + (n % 20)
        WHEN 'memory_percent'   THEN 40 + (n % 15)
        WHEN 'error_rate'       THEN 0.1 + (n % 3) * 0.1
        WHEN 'latency_p95_ms'   THEN 50  + (n % 80)
        WHEN 'request_rate'     THEN 200 + (n % 150)
        WHEN 'db_connections'   THEN 10  + (n % 8)
    END,
    CASE m.metric
        WHEN 'cpu_percent'    THEN 'percent'
        WHEN 'memory_percent' THEN 'percent'
        WHEN 'error_rate'     THEN 'errors/min'
        WHEN 'latency_p95_ms' THEN 'ms'
        WHEN 'request_rate'   THEN 'req/s'
        WHEN 'db_connections' THEN 'count'
    END,
    NOW() - (n * INTERVAL '30 seconds')
FROM
    (VALUES ('api-gateway'),('user-service'),('payment-service'),('auth-service'),('db-proxy')) AS s(service),
    (VALUES ('cpu_percent'),('memory_percent'),('error_rate'),('latency_p95_ms'),('request_rate'),('db_connections')) AS m(metric),
    generate_series(1, 240) AS n;

-- Normal logs: last hour
INSERT INTO logs (service, level, message, logged_at)
SELECT
    s.service,
    'INFO',
    CASE (n % 5)
        WHEN 0 THEN 'Request processed successfully'
        WHEN 1 THEN 'Health check passed'
        WHEN 2 THEN 'Cache hit ratio: 94%'
        WHEN 3 THEN 'Database query completed in 12ms'
        ELSE       'Metrics flushed to collector'
    END,
    NOW() - (n * INTERVAL '10 seconds')
FROM
    (VALUES ('api-gateway'),('user-service'),('payment-service'),('auth-service'),('db-proxy')) AS s(service),
    generate_series(1, 360) AS n;
