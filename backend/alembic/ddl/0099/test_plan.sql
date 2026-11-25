CREATE TABLE "test_plan" (
    id integer DEFAULT nextval('test_plan_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description character varying(1000),
    environment_id integer,
    status character varying(20) DEFAULT 'DRAFT'::character varying NOT NULL,
    execution_mode character varying(20) DEFAULT 'MANUAL'::character varying NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_plan PRIMARY KEY (id)
);
ALTER SEQUENCE test_plan_id_seq OWNED BY "test_plan".id;
ALTER TABLE "test_plan" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_plan" ADD CONSTRAINT test_plan_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_plan" ADD CONSTRAINT test_plan_environment_id_fkey FOREIGN KEY (environment_id) REFERENCES environment(id) ON DELETE SET NULL;
ALTER TABLE "test_plan" ADD CONSTRAINT test_plan_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
CREATE INDEX ix_test_plan_environment_id ON public.test_plan USING btree (environment_id);
CREATE INDEX ix_test_plan_id ON public.test_plan USING btree (id);
CREATE INDEX ix_test_plan_project_id ON public.test_plan USING btree (project_id);
CREATE INDEX ix_test_plan_project_status ON public.test_plan USING btree (project_id, status);
CREATE INDEX ix_test_plan_status ON public.test_plan USING btree (status);
CREATE UNIQUE INDEX uq_test_plan_project_name ON public.test_plan USING btree (project_id, name) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "test_plan".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_plan".project_id IS '所属项目ID';
COMMENT ON COLUMN "test_plan".name IS '计划名';
COMMENT ON COLUMN "test_plan".description IS '计划描述';
COMMENT ON COLUMN "test_plan".environment_id IS '执行环境ID（可空）';
COMMENT ON COLUMN "test_plan".status IS '状态：DRAFT/ACTIVE/DISABLED；枚举取值含义：DRAFT=草稿；ACTIVE=启用/活动中；DISABLED=已停用。';
COMMENT ON COLUMN "test_plan".execution_mode IS '执行模式：MANUAL/SCHEDULED/CI；枚举取值含义：MANUAL=业务状态/类别：manual；SCHEDULED=业务状态/类别：scheduled；CI=业务状态/类别：ci。';
COMMENT ON COLUMN "test_plan".created_by IS '创建人';
COMMENT ON COLUMN "test_plan".created_at IS '创建时间';
COMMENT ON COLUMN "test_plan".updated_at IS '更新时间';
COMMENT ON COLUMN "test_plan".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_plan".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_plan".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_plan".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_plan" IS '测试计划：组织套件与环境的执行单元';
