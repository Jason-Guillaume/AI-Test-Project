CREATE TABLE "web_case" (
    test_case_id integer NOT NULL,
    auth_profile_id integer,
    timeout_ms integer DEFAULT 30000 NOT NULL,
    total_timeout_ms integer DEFAULT 120000 NOT NULL,
    confirmed_digest character varying(64),
    confirmed_by integer,
    CONSTRAINT web_case_pkey PRIMARY KEY (test_case_id)
);
ALTER TABLE "web_case" ADD CONSTRAINT web_case_auth_profile_id_fkey FOREIGN KEY (auth_profile_id) REFERENCES web_auth_profile(id) ON DELETE SET NULL;
ALTER TABLE "web_case" ADD CONSTRAINT web_case_confirmed_by_fkey FOREIGN KEY (confirmed_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "web_case" ADD CONSTRAINT web_case_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
COMMENT ON COLUMN "web_case".test_case_id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "web_case".auth_profile_id IS '关联 web_auth_profile 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "web_case".timeout_ms IS '字段 timeout_ms（timeout毫秒整数）；用于既有用例的 Web 执行配置与人工确认指纹，修改依赖后必须重新确认。';
COMMENT ON COLUMN "web_case".total_timeout_ms IS '字段 total_timeout_ms（总数timeout毫秒整数）；用于既有用例的 Web 执行配置与人工确认指纹，修改依赖后必须重新确认。';
COMMENT ON COLUMN "web_case".confirmed_digest IS '字段 confirmed_digest（confirmeddigest字符串）；用于既有用例的 Web 执行配置与人工确认指纹，修改依赖后必须重新确认。';
COMMENT ON COLUMN "web_case".confirmed_by IS '关联 user 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON TABLE "web_case" IS '既有用例的 Web 执行配置与人工确认指纹，修改依赖后必须重新确认。';
