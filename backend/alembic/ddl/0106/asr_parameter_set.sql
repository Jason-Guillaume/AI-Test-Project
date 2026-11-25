CREATE TABLE "asr_parameter_set" (
    id integer DEFAULT nextval('asr_parameter_set_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    connection_id integer NOT NULL,
    name character varying(120) NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    parameters json NOT NULL,
    definitions json DEFAULT '[]'::json NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT asr_parameter_set_pkey PRIMARY KEY (id),
    CONSTRAINT uq_asr_parameter_set_version UNIQUE (connection_id, name, version)
);
ALTER SEQUENCE asr_parameter_set_id_seq OWNED BY "asr_parameter_set".id;
ALTER TABLE "asr_parameter_set" ADD CONSTRAINT asr_parameter_set_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES asr_connection(id) ON DELETE CASCADE;
ALTER TABLE "asr_parameter_set" ADD CONSTRAINT asr_parameter_set_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "asr_parameter_set" ADD CONSTRAINT asr_parameter_set_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
CREATE INDEX ix_asr_parameter_set_connection_id ON public.asr_parameter_set USING btree (connection_id);
CREATE INDEX ix_asr_parameter_set_project_id ON public.asr_parameter_set USING btree (project_id);
COMMENT ON COLUMN "asr_parameter_set".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "asr_parameter_set".project_id IS '关联 project 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "asr_parameter_set".connection_id IS '关联 asr_connection 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "asr_parameter_set".name IS '名称；用于待测模型参数的不可变版本及其可验证定义。';
COMMENT ON COLUMN "asr_parameter_set".version IS '版本号；用于待测模型参数的不可变版本及其可验证定义。';
COMMENT ON COLUMN "asr_parameter_set".parameters IS '参数集合；用于待测模型参数的不可变版本及其可验证定义。';
COMMENT ON COLUMN "asr_parameter_set".definitions IS '字段 definitions（JSON 格式的definitions）；用于待测模型参数的不可变版本及其可验证定义。';
COMMENT ON COLUMN "asr_parameter_set".created_by IS '关联 user 表记录的外键 ID；用于定位对应业务对象。';
COMMENT ON COLUMN "asr_parameter_set".created_at IS '记录创建时间；用于待测模型参数的不可变版本及其可验证定义。';
COMMENT ON TABLE "asr_parameter_set" IS '待测模型参数的不可变版本及其可验证定义。';
