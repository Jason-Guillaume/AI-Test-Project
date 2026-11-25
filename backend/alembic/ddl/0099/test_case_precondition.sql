CREATE TABLE "test_case_precondition" (
    id integer DEFAULT nextval('test_case_precondition_id_seq'::regclass) NOT NULL,
    test_case_id integer NOT NULL,
    type character varying(30) DEFAULT 'VARIABLE'::character varying NOT NULL,
    target character varying(200),
    operator character varying(20) DEFAULT 'EQ'::character varying NOT NULL,
    expected_value text,
    description character varying(500),
    config_json json,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_case_precondition PRIMARY KEY (id)
);
ALTER SEQUENCE test_case_precondition_id_seq OWNED BY "test_case_precondition".id;
ALTER TABLE "test_case_precondition" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_case_precondition" ADD CONSTRAINT test_case_precondition_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
CREATE INDEX ix_test_case_precondition_deleted_at ON public.test_case_precondition USING btree (deleted_at);
CREATE INDEX ix_test_case_precondition_id ON public.test_case_precondition USING btree (id);
CREATE INDEX ix_test_case_precondition_test_case_id ON public.test_case_precondition USING btree (test_case_id);
COMMENT ON COLUMN "test_case_precondition".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_case_precondition".test_case_id IS '所属测试用例ID';
COMMENT ON COLUMN "test_case_precondition".type IS '前置条件类型：VARIABLE/TEXT/FIXTURE/API/BUSINESS_ACTION/BUSINESS_FLOW；枚举取值含义：VARIABLE=业务状态/类别：variable；TEXT=业务状态/类别：文本；FIXTURE=业务状态/类别：fixture；API=业务状态/类别：接口；BUSINESS_ACTION=业务状态/类别：business、action；BUSINESS_FLOW=业务状态/类别：business、flow。';
COMMENT ON COLUMN "test_case_precondition".target IS '目标：变量名/实体/说明';
COMMENT ON COLUMN "test_case_precondition".operator IS '操作符：EQ/NE/GT/GE/LT/LE/IN/EXISTS/NOT_EXISTS/CONTAINS；枚举取值含义：EQ=业务状态/类别：eq；NE=业务状态/类别：ne；GT=业务状态/类别：gt；GE=业务状态/类别：ge；LT=业务状态/类别：lt；LE=业务状态/类别：le；IN=业务状态/类别：in；EXISTS=业务状态/类别：exists；NOT_EXISTS=业务状态/类别：not、exists；CONTAINS=业务状态/类别：contains。';
COMMENT ON COLUMN "test_case_precondition".expected_value IS '期望值';
COMMENT ON COLUMN "test_case_precondition".description IS '说明';
COMMENT ON COLUMN "test_case_precondition".config_json IS '附加配置';
COMMENT ON COLUMN "test_case_precondition".sort IS '排序';
COMMENT ON COLUMN "test_case_precondition".created_at IS '创建时间';
COMMENT ON COLUMN "test_case_precondition".updated_at IS '更新时间';
COMMENT ON COLUMN "test_case_precondition".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_case_precondition".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_case_precondition".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_case_precondition".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_case_precondition" IS '测试用例前置条件';
