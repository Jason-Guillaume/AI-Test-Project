CREATE TABLE "test_suite" (
    id integer DEFAULT nextval('test_suite_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description character varying(1000),
    suite_type character varying(20) DEFAULT 'REGRESSION'::character varying NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_suite PRIMARY KEY (id)
);
ALTER SEQUENCE test_suite_id_seq OWNED BY "test_suite".id;
ALTER TABLE "test_suite" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_suite" ADD CONSTRAINT test_suite_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_suite" ADD CONSTRAINT test_suite_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
CREATE INDEX ix_test_suite_enabled ON public.test_suite USING btree (enabled);
CREATE INDEX ix_test_suite_id ON public.test_suite USING btree (id);
CREATE INDEX ix_test_suite_project_enabled ON public.test_suite USING btree (project_id, enabled);
CREATE INDEX ix_test_suite_project_id ON public.test_suite USING btree (project_id);
CREATE UNIQUE INDEX uq_test_suite_project_name ON public.test_suite USING btree (project_id, name) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "test_suite".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_suite".project_id IS '所属项目ID';
COMMENT ON COLUMN "test_suite".name IS '套件名';
COMMENT ON COLUMN "test_suite".description IS '套件描述';
COMMENT ON COLUMN "test_suite".suite_type IS '套件类型：SMOKE/REGRESSION/BUSINESS/CUSTOM；枚举取值含义：SMOKE=业务状态/类别：smoke；REGRESSION=业务状态/类别：regression；BUSINESS=业务状态/类别：business；CUSTOM=业务状态/类别：custom。';
COMMENT ON COLUMN "test_suite".enabled IS '是否启用';
COMMENT ON COLUMN "test_suite".created_by IS '创建人';
COMMENT ON COLUMN "test_suite".created_at IS '创建时间';
COMMENT ON COLUMN "test_suite".updated_at IS '更新时间';
COMMENT ON COLUMN "test_suite".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_suite".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_suite".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_suite".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_suite" IS '测试套件：测试用例的集合容器';
