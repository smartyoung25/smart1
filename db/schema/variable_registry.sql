-- ============================================================
-- Variable Registry — 모든 데이터 소스 변수의 단일 진실 소스
-- 새 소스 추가 시 source_mappings 에 항목만 추가
-- ============================================================

CREATE TABLE IF NOT EXISTS variable_registry (
    id              SERIAL PRIMARY KEY,
    canonical_name  VARCHAR(64) UNIQUE NOT NULL,  -- 정규 변수명 (영문 snake_case)
    display_name_ko VARCHAR(64) NOT NULL,          -- 한국어 표시명
    unit            VARCHAR(16) NOT NULL,          -- 정규 단위
    valid_min       FLOAT,                         -- 유효 범위 최솟값
    valid_max       FLOAT,                         -- 유효 범위 최댓값
    impute_strategy VARCHAR(16) DEFAULT 'locf'     -- locf | knn | hierarchy | none
        CHECK (impute_strategy IN ('locf','knn','hierarchy','none')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 소스별 필드 매핑 테이블
CREATE TABLE IF NOT EXISTS variable_source_mapping (
    id              SERIAL PRIMARY KEY,
    canonical_name  VARCHAR(64) REFERENCES variable_registry(canonical_name),
    source_id       VARCHAR(32) NOT NULL,          -- iot_sensor | rda_api | kamis | wur_dataset | manual
    source_field    VARCHAR(64),                   -- 원본 필드명 (NULL = 소스에 없음)
    source_unit     VARCHAR(16),                   -- 원본 단위
    transform_expr  VARCHAR(128),                  -- 변환식 (NULL = 변환 없음, 예: "value * 0.1")
    UNIQUE (canonical_name, source_id)
);

-- ============================================================
-- 기본 변수 등록
-- ============================================================

INSERT INTO variable_registry
    (canonical_name, display_name_ko, unit, valid_min, valid_max, impute_strategy)
VALUES
    ('temp_internal',   '내부 온도',      '°C',    0,    60,   'locf'),
    ('temp_external',   '외부 온도',      '°C',  -20,    50,   'locf'),
    ('humidity_int',    '내부 습도',      '%',     0,   100,   'locf'),
    ('co2_ppm',         'CO₂ 농도',      'ppm',   0,  5000,   'knn'),
    ('solar_rad',       '일사량',         'W/m²',  0,  1500,   'locf'),
    ('ec_dsm',          'EC',             'dS/m',  0,    10,   'knn'),
    ('ph',              'pH',             'pH',    0,    14,   'knn'),
    ('soil_temp',       '토양 온도',      '°C',    0,    50,   'locf'),
    ('wind_speed_ext',  '외부 풍속',      'm/s',   0,    50,   'locf'),
    ('wind_dir_ext',    '외부 풍향',      'deg',   0,   360,   'none'),
    ('cum_solar_ext',   '누적 일사량',    'MJ/m²', 0, 99999,   'locf'),
    ('rain_detect',     '강우 감지',      'bool',  0,     1,   'locf'),
    ('yield_kg_m2',     '수확량',         'kg/m²', 0,   100,   'none'),
    ('plant_height',    '초장',           'cm',    0,   200,   'none'),
    ('leaf_count',      '엽수',           '매',    0,   100,   'none'),
    ('leaf_length',     '엽장',           'cm',    0,    50,   'none'),
    ('leaf_width',      '엽폭',           'cm',    0,    30,   'none'),
    ('crown_diameter',  '관부직경',       'mm',    0,   100,   'none'),
    ('fruit_count',     '화방착과수',     '개',    0,   200,   'none'),
    ('kamis_price',     'KAMIS 단가',     '원/kg', 0, 99999,   'locf'),
    ('gdd_cumsum',      '누적 GDD',       '°C·d',  0, 99999,   'locf')
ON CONFLICT (canonical_name) DO NOTHING;

-- ============================================================
-- 소스 매핑 (원본필드 → 정규명)
-- ============================================================

INSERT INTO variable_source_mapping
    (canonical_name, source_id, source_field, source_unit, transform_expr)
VALUES
-- IoT 센서 (환경_2025.csv 컬럼명 기준)
('temp_internal',  'iot_sensor',  '온도_내부',        '°C',    NULL),
('temp_external',  'iot_sensor',  '온도_외부',        '°C',    NULL),
('humidity_int',   'iot_sensor',  '상대습도_내부',    '%',     NULL),
('co2_ppm',        'iot_sensor',  '잔존CO2',          'ppm',   NULL),
('solar_rad',      'iot_sensor',  '일사량_외부',      'W/m²',  NULL),
('cum_solar_ext',  'iot_sensor',  '누적일사량_외부',  'MJ/m²', NULL),
('soil_temp',      'iot_sensor',  '토양온도',         '°C',    NULL),
('wind_speed_ext', 'iot_sensor',  '풍속_외부',        'm/s',   NULL),
('wind_dir_ext',   'iot_sensor',  '풍향_외부',        'deg',   NULL),
('rain_detect',    'iot_sensor',  '강우감지',         'bool',  NULL),
-- EC: IoT는 mS/cm → dS/m 변환 필요
('ec_dsm',         'iot_sensor',  'EC',               'mS/cm', 'value * 0.1'),

-- 농진청 API
('temp_internal',  'rda_api',     '내부온도',         '°C',    NULL),
('humidity_int',   'rda_api',     '내부습도',         '%',     NULL),
('yield_kg_m2',    'rda_api',     '수확량',           'kg/m²', NULL),
('plant_height',   'rda_api',     '초장',             'cm',    NULL),
('leaf_count',     'rda_api',     '엽수',             '매',    NULL),
('leaf_length',    'rda_api',     '엽장',             'cm',    NULL),
('leaf_width',     'rda_api',     '엽폭',             'cm',    NULL),
('crown_diameter', 'rda_api',     '관부직경',         'mm',    NULL),
('fruit_count',    'rda_api',     '화방별착과수',     '개',    NULL),

-- KAMIS
('kamis_price',    'kamis',       '가격',             '원/kg', NULL),

-- WUR 네덜란드 데이터셋
('temp_internal',  'wur_dataset', 'T_air',            '°C',    NULL),
('co2_ppm',        'wur_dataset', 'CO2_conc',         'ppm',   NULL),
('solar_rad',      'wur_dataset', 'I_glob',           'W/m²',  NULL),
('ec_dsm',         'wur_dataset', 'EC_solution',      'dS/m',  NULL),
('yield_kg_m2',    'wur_dataset', 'Fresh_weight',     'kg/m²', NULL),

-- 농가 수동 입력
('yield_kg_m2',    'manual',      'harvest_weight',   'kg',    NULL),
('plant_height',   'manual',      'plant_height_cm',  'cm',    NULL),
('leaf_count',     'manual',      'leaf_count',       '매',    NULL)

ON CONFLICT (canonical_name, source_id) DO NOTHING;

-- ============================================================
-- 시계열 환경 데이터 테이블 (TimescaleDB hypertable)
-- ============================================================

CREATE TABLE IF NOT EXISTS env_measurements (
    time            TIMESTAMPTZ NOT NULL,
    farm_id         VARCHAR(32) NOT NULL,
    canonical_name  VARCHAR(64) NOT NULL,
    value           FLOAT NOT NULL,
    source_id       VARCHAR(32) NOT NULL,
    quality_tag     VARCHAR(16) DEFAULT 'FINETUNED'
        CHECK (quality_tag IN ('FINETUNED','TRANSFER','SIMULATION','LITERATURE')),
    imputed         BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (time, farm_id, canonical_name)
);

-- TimescaleDB 하이퍼테이블 전환 (TimescaleDB 미설치 환경에서도 안전하게 건너뜀)
DO $$
BEGIN
    PERFORM create_hypertable('env_measurements', 'time', if_not_exists => TRUE);
EXCEPTION WHEN undefined_function THEN
    NULL;  -- TimescaleDB 없는 순수 PostgreSQL 환경
END $$;

CREATE INDEX IF NOT EXISTS idx_env_farm_name ON env_measurements (farm_id, canonical_name, time DESC);

-- ============================================================
-- 농가 정보 테이블
-- ============================================================

CREATE TABLE IF NOT EXISTS farms (
    farm_id         VARCHAR(32) PRIMARY KEY,
    name            VARCHAR(64) NOT NULL,
    crop_type       VARCHAR(32) NOT NULL,   -- strawberry | tomato | cherry_tomato | melon
    region          VARCHAR(32),
    tier            VARCHAR(16) DEFAULT 'manual'
        CHECK (tier IN ('manual','semi_auto','auto')),
    area_m2         FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO farms (farm_id, name, crop_type, region, tier, area_m2)
VALUES
    ('farm_001', '이암허브 농장',    'strawberry',    '전북 군산', 'manual',    1200),
    ('farm_002', '농가 B',          'cherry_tomato', '경남 진주', 'semi_auto', 800),
    ('farm_003', '농가 C',          'tomato',        '충남 부여', 'manual',    1500),
    ('farm_004', '농가 D',          'melon',         '경북 성주', 'semi_auto', 1000),
    ('farm_005', '농가 E',          'strawberry',    '전남 담양', 'manual',    900)
ON CONFLICT (farm_id) DO NOTHING;

-- ============================================================
-- 생육 측정 데이터 테이블 (TimescaleDB hypertable)
-- env_measurements와 분리 — crop 컬럼으로 작목별 쿼리 지원
-- ============================================================

CREATE TABLE IF NOT EXISTS growth_measurements (
    time            TIMESTAMPTZ      NOT NULL,
    farm_id         VARCHAR(32)      NOT NULL,
    crop            VARCHAR(32)      NOT NULL,   -- 딸기 | 방울토마토 | 완숙토마토 | 참외 | 오이
    canonical_name  VARCHAR(64)      NOT NULL,   -- plant_height | leaf_count | ...
    value           DOUBLE PRECISION,
    source_id       VARCHAR(32)      NOT NULL DEFAULT 'rda_api',
    quality_tag     VARCHAR(16)      DEFAULT 'FINETUNED'
        CHECK (quality_tag IN ('FINETUNED','TRANSFER','SIMULATION','LITERATURE')),
    PRIMARY KEY (time, farm_id, crop, canonical_name)
);

-- TimescaleDB 하이퍼테이블 전환 (TimescaleDB 미설치 환경에서도 안전하게 건너뜀)
DO $$
BEGIN
    PERFORM create_hypertable('growth_measurements', 'time', if_not_exists => TRUE);
EXCEPTION WHEN undefined_function THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_growth_crop_name
    ON growth_measurements (crop, canonical_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_growth_farm_crop
    ON growth_measurements (farm_id, crop, time DESC);

-- ============================================================
-- 농가 수동 입력 로그
-- ============================================================

-- ============================================================
-- 사용자 계정 테이블 (JWT 인증용)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role            VARCHAR(16) DEFAULT 'viewer'
        CHECK (role IN ('admin', 'manager', 'viewer')),
    farm_id         VARCHAR(32) REFERENCES farms(farm_id),  -- NULL = 전체 농가 접근
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

-- 기본 관리자 계정 — 비밀번호는 init_admin.sql 또는 docker-entrypoint에서 설정
-- 여기서는 계정 행만 삽입; hashed_password는 배포 시 UPDATE로 교체
INSERT INTO users (username, hashed_password, role)
VALUES ('admin', '$2b$12$placeholder_replace_via_init_admin$', 'admin')
ON CONFLICT (username) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);

-- ============================================================
-- 농가 수동 입력 로그
-- ============================================================

CREATE TABLE IF NOT EXISTS manual_inputs (
    id              SERIAL PRIMARY KEY,
    farm_id         VARCHAR(32) REFERENCES farms(farm_id),
    input_type      VARCHAR(32) NOT NULL,   -- harvest | growth_survey | disease_report
    recorded_at     TIMESTAMPTZ NOT NULL,
    payload         JSONB NOT NULL,
    processed       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
