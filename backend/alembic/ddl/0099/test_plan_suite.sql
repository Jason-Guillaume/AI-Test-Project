CREATE TABLE "test_plan_suite" (
    id integer DEFAULT nextval('test_plan_suite_id_seq'::regclass) NOT NULL,
    plan_id integer NOT NULL,
    suite_id integer NOT NULL,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_plan_suite PRIMARY KEY (id)
);
ALTER SEQUENCE test_plan_suite_id_seq OWNED BY "test_plan_suite".id;
ALTER TABLE "test_plan_suite" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_plan_suite" ADD CONSTRAINT test_plan_suite_plan_id_fkey FOREIGN KEY (plan_id) REFERENCES test_plan(id) ON DELETE CASCADE;
ALTER TABLE "test_plan_suite" ADD CONSTRAINT test_plan_suite_suite_id_fkey FOREIGN KEY (suite_id) REFERENCES test_suite(id) ON DELETE CASCADE;
CREATE INDEX ix_test_plan_suite_deleted_at ON public.test_plan_suite USING btree (deleted_at);
CREATE INDEX ix_test_plan_suite_id ON public.test_plan_suite USING btree (id);
CREATE INDEX ix_test_plan_suite_plan_id ON public.test_plan_suite USING btree (plan_id);
CREATE INDEX ix_test_plan_suite_plan_sort ON public.test_plan_suite USING btree (plan_id, sort);
CREATE INDEX ix_test_plan_suite_suite_id ON public.test_plan_suite USING btree (suite_id);
CREATE UNIQUE INDEX uq_test_plan_suite_plan_suite_live ON public.test_plan_suite USING btree (plan_id, suite_id) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "test_plan_suite".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_plan_suite".plan_id IS '所属计划ID';
COMMENT ON COLUMN "test_plan_suite".suite_id IS '套件ID';
COMMENT ON COLUMN "test_plan_suite".sort IS '排序';
COMMENT ON COLUMN "test_plan_suite".created_at IS '创建时间';
COMMENT ON COLUMN "test_plan_suite".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_plan_suite".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_plan_suite".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_plan_suite".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_plan_suite" IS '计划-套件关联';
