CREATE TABLE "test_suite_case" (
    id integer DEFAULT nextval('test_suite_case_id_seq'::regclass) NOT NULL,
    suite_id integer NOT NULL,
    test_case_id integer NOT NULL,
    sort integer DEFAULT 0 NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_suite_case PRIMARY KEY (id)
);
ALTER SEQUENCE test_suite_case_id_seq OWNED BY "test_suite_case".id;
ALTER TABLE "test_suite_case" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_suite_case" ADD CONSTRAINT test_suite_case_suite_id_fkey FOREIGN KEY (suite_id) REFERENCES test_suite(id) ON DELETE CASCADE;
ALTER TABLE "test_suite_case" ADD CONSTRAINT test_suite_case_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
CREATE INDEX ix_test_suite_case_deleted_at ON public.test_suite_case USING btree (deleted_at);
CREATE INDEX ix_test_suite_case_id ON public.test_suite_case USING btree (id);
CREATE INDEX ix_test_suite_case_suite_id ON public.test_suite_case USING btree (suite_id);
CREATE INDEX ix_test_suite_case_suite_sort ON public.test_suite_case USING btree (suite_id, sort);
CREATE INDEX ix_test_suite_case_test_case_id ON public.test_suite_case USING btree (test_case_id);
CREATE UNIQUE INDEX uq_test_suite_case_suite_case_live ON public.test_suite_case USING btree (suite_id, test_case_id) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "test_suite_case".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_suite_case".suite_id IS '所属套件ID';
COMMENT ON COLUMN "test_suite_case".test_case_id IS '用例ID';
COMMENT ON COLUMN "test_suite_case".sort IS '排序';
COMMENT ON COLUMN "test_suite_case".enabled IS '是否启用';
COMMENT ON COLUMN "test_suite_case".created_at IS '创建时间';
COMMENT ON COLUMN "test_suite_case".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_suite_case".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_suite_case".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_suite_case".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_suite_case" IS '套件-用例关联';
