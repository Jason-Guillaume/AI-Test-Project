CREATE TABLE "asr_connection" (
    id integer DEFAULT nextval('asr_connection_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    name character varying(120) NOT NULL,
    role character varying(20),
    provider_id character varying(80) DEFAULT '''generic-json'''::character varying NOT NULL,
    model_id character varying(160) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    endpoint_ciphertext text NOT NULL,
    endpoint_display character varying(500) NOT NULL,
    config_json json NOT NULL,
    secret_ciphertext text,
    secret_header character varying(100),
    enabled boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    task_type character varying(30) DEFAULT 'TRANSCRIPTION'::character varying NOT NULL,
    CONSTRAINT asr_connection_pkey PRIMARY KEY (id),
    CONSTRAINT uq_asr_connection_project_name_version UNIQUE (project_id, name, version)
);
ALTER SEQUENCE asr_connection_id_seq OWNED BY "asr_connection".id;
ALTER TABLE "asr_connection" ADD CONSTRAINT asr_connection_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "asr_connection" ADD CONSTRAINT asr_connection_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
CREATE INDEX ix_asr_connection_project_id ON public.asr_connection USING btree (project_id);
COMMENT ON COLUMN "asr_connection".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "asr_connection".project_id IS '关联 project 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "asr_connection".name IS '名称；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".role IS '角色；用于一个转写或说话人处理 HTTP 连接的不可变配置版本；枚举取值含义：TEST=待测对象/测试模型；REFERENCE=参考模型。';
COMMENT ON COLUMN "asr_connection".provider_id IS '字段 provider_id（服务提供方ID关联标识符）；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".model_id IS '字段 model_id（模型ID关联标识符）；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".version IS '版本号；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".endpoint_ciphertext IS '加密保存的服务地址密文；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".endpoint_display IS '脱敏后展示的服务地址；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".config_json IS 'JSON 格式配置；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".secret_ciphertext IS '加密保存的凭据密文；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".secret_header IS '字段 secret_header（凭据header字符串）；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".enabled IS '是否启用；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".created_by IS '关联 user 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "asr_connection".created_at IS '记录创建时间；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".updated_at IS '记录最后更新时间；用于一个转写或说话人处理 HTTP 连接的不可变配置版本。';
COMMENT ON COLUMN "asr_connection".task_type IS '字段 task_type（任务类型字符串）；用于一个转写或说话人处理 HTTP 连接的不可变配置版本；枚举取值含义：TRANSCRIPTION=语音转写；DIARIZATION=说话人分离。';
COMMENT ON TABLE "asr_connection" IS '一个转写或说话人处理 HTTP 连接的不可变配置版本。';
