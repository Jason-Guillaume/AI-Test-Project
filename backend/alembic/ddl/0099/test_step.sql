CREATE TABLE "test_step" (
    id integer DEFAULT nextval('test_step_id_seq'::regclass) NOT NULL,
    test_case_id integer NOT NULL,
    name character varying(200) NOT NULL,
    step_type character varying(20) DEFAULT 'ACTION'::character varying NOT NULL,
    target_type character varying(20),
    target_id integer,
    sort integer DEFAULT 0 NOT NULL,
    config_json json,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_step PRIMARY KEY (id)
);
ALTER SEQUENCE test_step_id_seq OWNED BY "test_step".id;
ALTER TABLE "test_step" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_step" ADD CONSTRAINT test_step_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
CREATE INDEX ix_test_step_deleted_at ON public.test_step USING btree (deleted_at);
CREATE INDEX ix_test_step_id ON public.test_step USING btree (id);
CREATE INDEX ix_test_step_sort ON public.test_step USING btree (sort);
CREATE INDEX ix_test_step_test_case_id ON public.test_step USING btree (test_case_id);
COMMENT ON COLUMN "test_step".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_step".test_case_id IS '所属测试用例ID';
COMMENT ON COLUMN "test_step".name IS '步骤名';
COMMENT ON COLUMN "test_step".step_type IS '步骤类型：SETUP/ACTION/ASSERT/CLEANUP；枚举取值含义：SETUP=业务状态/类别：setup；ACTION=业务状态/类别：action；ASSERT=业务状态/类别：assert；CLEANUP=业务状态/类别：cleanup。';
COMMENT ON COLUMN "test_step".target_type IS '被测对象类型：API/BUSINESS_FLOW/BUSINESS_ACTION；枚举取值含义：API=业务状态/类别：接口；BUSINESS_FLOW=业务状态/类别：business、flow；BUSINESS_ACTION=业务状态/类别：business、action。';
COMMENT ON COLUMN "test_step".target_id IS '被测对象ID';
COMMENT ON COLUMN "test_step".sort IS '排序';
COMMENT ON COLUMN "test_step".config_json IS '步骤配置（path_params/headers/query/body/timeout 等）；枚举取值含义：path_params=业务状态/类别：path、params；headers=业务状态/类别：headers；query=业务状态/类别：query；body=业务状态/类别：body；timeout=业务状态/类别：timeout。';
COMMENT ON COLUMN "test_step".created_at IS '创建时间';
COMMENT ON COLUMN "test_step".updated_at IS '更新时间';
COMMENT ON COLUMN "test_step".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_step".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_step".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_step".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_step" IS '测试步骤';
