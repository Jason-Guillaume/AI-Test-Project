CREATE TABLE "test_assertion" (
    id integer DEFAULT nextval('test_assertion_id_seq'::regclass) NOT NULL,
    test_case_id integer NOT NULL,
    step_id integer,
    assertion_type character varying(30) DEFAULT 'STATUS_CODE'::character varying NOT NULL,
    source character varying(100),
    path character varying(500),
    operator character varying(20) DEFAULT 'EQ'::character varying NOT NULL,
    expected_value text,
    required boolean DEFAULT true NOT NULL,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_assertion PRIMARY KEY (id)
);
ALTER SEQUENCE test_assertion_id_seq OWNED BY "test_assertion".id;
ALTER TABLE "test_assertion" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_assertion" ADD CONSTRAINT test_assertion_step_id_fkey FOREIGN KEY (step_id) REFERENCES test_step(id) ON DELETE SET NULL;
ALTER TABLE "test_assertion" ADD CONSTRAINT test_assertion_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
CREATE INDEX ix_test_assertion_deleted_at ON public.test_assertion USING btree (deleted_at);
CREATE INDEX ix_test_assertion_id ON public.test_assertion USING btree (id);
CREATE INDEX ix_test_assertion_test_case_id ON public.test_assertion USING btree (test_case_id);
COMMENT ON COLUMN "test_assertion".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_assertion".test_case_id IS '所属测试用例ID';
COMMENT ON COLUMN "test_assertion".step_id IS '关联步骤ID（可空，空表示用例级断言）';
COMMENT ON COLUMN "test_assertion".assertion_type IS '断言类型：STATUS_CODE/JSON_PATH/HEADER/RESPONSE_TIME/CONTAINS/NOT_CONTAINS；枚举取值含义：STATUS_CODE=业务状态/类别：status、code；JSON_PATH=业务状态/类别：json、path；HEADER=业务状态/类别：header；RESPONSE_TIME=业务状态/类别：response、time；CONTAINS=业务状态/类别：contains；NOT_CONTAINS=业务状态/类别：not、contains。';
COMMENT ON COLUMN "test_assertion".source IS '来源标识：HEADER 名 / CONTEXT 作用域';
COMMENT ON COLUMN "test_assertion".path IS 'JSONPath 或字段路径（如 $.code）';
COMMENT ON COLUMN "test_assertion".operator IS '操作符：EQ/NE/GT/GE/LT/LE/IN/EXISTS/NOT_EXISTS；枚举取值含义：EQ=业务状态/类别：eq；NE=业务状态/类别：ne；GT=业务状态/类别：gt；GE=业务状态/类别：ge；LT=业务状态/类别：lt；LE=业务状态/类别：le；IN=业务状态/类别：in；EXISTS=业务状态/类别：exists；NOT_EXISTS=业务状态/类别：not、exists。';
COMMENT ON COLUMN "test_assertion".expected_value IS '期望值';
COMMENT ON COLUMN "test_assertion".required IS '是否必需（软断言=False）';
COMMENT ON COLUMN "test_assertion".sort IS '排序';
COMMENT ON COLUMN "test_assertion".created_at IS '创建时间';
COMMENT ON COLUMN "test_assertion".updated_at IS '更新时间';
COMMENT ON COLUMN "test_assertion".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_assertion".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_assertion".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_assertion".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_assertion" IS '测试断言';
