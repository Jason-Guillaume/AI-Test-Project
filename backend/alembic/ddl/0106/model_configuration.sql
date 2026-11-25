CREATE TABLE "model_configuration" (
    id integer DEFAULT nextval('model_configuration_id_seq'::regclass) NOT NULL,
    domain_id character varying(100) NOT NULL,
    label character varying(120) NOT NULL,
    provider character varying(50) DEFAULT 'openai-compatible'::character varying NOT NULL,
    api_base character varying(500) NOT NULL,
    api_key_encrypted text,
    model_name character varying(200) NOT NULL,
    temperature double precision DEFAULT 0.2 NOT NULL,
    max_tokens integer DEFAULT 4096 NOT NULL,
    timeout integer DEFAULT 60 NOT NULL,
    cost_per_1k_input double precision DEFAULT 0 NOT NULL,
    cost_per_1k_output double precision DEFAULT 0 NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    fallback_model_ids json DEFAULT '[]'::json NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT model_configuration_pkey PRIMARY KEY (id)
);
ALTER SEQUENCE model_configuration_id_seq OWNED BY "model_configuration".id;
ALTER TABLE "model_configuration" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "model_configuration" ADD CONSTRAINT model_configuration_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id);
CREATE INDEX ix_model_configuration_deleted_at ON public.model_configuration USING btree (deleted_at);
CREATE INDEX ix_model_configuration_id ON public.model_configuration USING btree (id);
CREATE INDEX ix_model_configuration_is_default ON public.model_configuration USING btree (is_default);
CREATE INDEX ix_model_configuration_is_enabled ON public.model_configuration USING btree (is_enabled);
CREATE UNIQUE INDEX uq_model_configuration_domain_id_live ON public.model_configuration USING btree (domain_id) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "model_configuration".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "model_configuration".domain_id IS '后端生成的稳定逻辑ID';
COMMENT ON COLUMN "model_configuration".label IS '前端展示名称';
COMMENT ON COLUMN "model_configuration".provider IS '模型供应商';
COMMENT ON COLUMN "model_configuration".api_base IS 'OpenAI兼容接口根地址';
COMMENT ON COLUMN "model_configuration".api_key_encrypted IS '加密后的API Key';
COMMENT ON COLUMN "model_configuration".model_name IS '供应商模型名称';
COMMENT ON COLUMN "model_configuration".temperature IS '采样温度';
COMMENT ON COLUMN "model_configuration".max_tokens IS '最大输出Token';
COMMENT ON COLUMN "model_configuration".timeout IS '请求超时秒数';
COMMENT ON COLUMN "model_configuration".cost_per_1k_input IS '千输入Token成本';
COMMENT ON COLUMN "model_configuration".cost_per_1k_output IS '千输出Token成本';
COMMENT ON COLUMN "model_configuration".is_enabled IS '是否启用';
COMMENT ON COLUMN "model_configuration".is_default IS '是否默认模型';
COMMENT ON COLUMN "model_configuration".fallback_model_ids IS '有序备用模型配置 ID';
COMMENT ON COLUMN "model_configuration".sort_order IS '展示顺序';
COMMENT ON COLUMN "model_configuration".created_by IS '创建人ID';
COMMENT ON COLUMN "model_configuration".created_at IS '创建时间';
COMMENT ON COLUMN "model_configuration".updated_at IS '更新时间';
COMMENT ON COLUMN "model_configuration".deleted_at IS '软删除时间';
COMMENT ON COLUMN "model_configuration".deleted_by IS '删除操作人';
COMMENT ON COLUMN "model_configuration".deletion_reason IS '删除原因';
COMMENT ON COLUMN "model_configuration".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "model_configuration" IS '大模型连接、调用参数及启停状态配置';
