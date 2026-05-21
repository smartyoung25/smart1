-- ============================================================
-- 스마트팜 AI 플랫폼 — 빌링/구독 DB 스키마
-- PostgreSQL 17 / 실행: psql -U smartfarm -d smartfarm -f billing_schema.sql
-- ============================================================

-- 구독 테이블 (농장별 현재 티어·결제 주기)
CREATE TABLE IF NOT EXISTS subscriptions (
    farm_id              VARCHAR(32)  PRIMARY KEY,
    tier                 VARCHAR(20)  NOT NULL DEFAULT 'basic'
                             CHECK (tier IN ('basic','smart','pro','enterprise')),
    status               VARCHAR(20)  NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','suspended','trial','expired')),
    trial_ends_at        TIMESTAMPTZ,
    billing_cycle        VARCHAR(10)  NOT NULL DEFAULT 'monthly'
                             CHECK (billing_cycle IN ('monthly','annual')),
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_period_end   TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 month'),
    next_billing_at      TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 사용량 로그 테이블 (AI 쿼터·기능 사용 추적)
CREATE TABLE IF NOT EXISTS usage_logs (
    id               BIGSERIAL    PRIMARY KEY,
    farm_id          VARCHAR(32)  NOT NULL,
    feature_code     VARCHAR(64)  NOT NULL,
    endpoint         VARCHAR(128),
    ts               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    quota_consumed   INT          NOT NULL DEFAULT 1,
    metadata         JSONB
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_farm_feature_ts
    ON usage_logs (farm_id, feature_code, ts DESC);

-- 업그레이드 요청 테이블
CREATE TABLE IF NOT EXISTS upgrade_requests (
    id             BIGSERIAL    PRIMARY KEY,
    farm_id        VARCHAR(32)  NOT NULL,
    requested_tier VARCHAR(20)  NOT NULL,
    status         VARCHAR(20)  NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','approved','rejected','cancelled')),
    pg_channel     VARCHAR(20),   -- 'kakaopay' | 'toss' | 'manual'
    amount_krw     INT,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    processed_at   TIMESTAMPTZ
);

-- 기본 구독 초기 데이터 (farm_001~005)
INSERT INTO subscriptions (farm_id, tier, status)
VALUES
    ('farm_001', 'pro',    'active'),
    ('farm_002', 'smart',  'active'),
    ('farm_003', 'smart',  'active'),
    ('farm_004', 'basic',  'active'),
    ('farm_005', 'basic',  'trial')
ON CONFLICT (farm_id) DO NOTHING;

-- 월별 AI 쿼터 사용량 집계 뷰
CREATE OR REPLACE VIEW v_chat_quota_monthly AS
SELECT
    farm_id,
    DATE_TRUNC('month', ts) AS month,
    SUM(quota_consumed)     AS used
FROM usage_logs
WHERE feature_code = 'ai_chat_basic'
GROUP BY farm_id, DATE_TRUNC('month', ts);

COMMENT ON TABLE subscriptions   IS '농가별 구독 티어 및 결제 주기';
COMMENT ON TABLE usage_logs      IS 'AI 쿼터 및 기능별 사용량 로그';
COMMENT ON TABLE upgrade_requests IS '티어 업그레이드 요청 이력';
