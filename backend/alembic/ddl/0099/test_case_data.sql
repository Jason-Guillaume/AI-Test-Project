CREATE TABLE "test_case_data" (
    id integer DEFAULT nextval('test_case_data_id_seq'::regclass) NOT NULL,
    test_case_id integer NOT NULL,
    name character varying(100) NOT NULL,
    value_type character varying(20) DEFAULT 'STRING'::character varying NOT NULL,
    value text,
    source_type character varying(20) DEFAULT 'STATIC'::character varying NOT NULL,
    required boolean DEFAULT false NOT NULL,
    description character varying(500),
    config_json json,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    deleted_at timestamp without time zone,
    deleted_by integer,
    deletion_reason character varying(500),
    deletion_batch_id character varying(36),
    CONSTRAINT pk_test_case_data PRIMARY KEY (id)
);
ALTER SEQUENCE test_case_data_id_seq OWNED BY "test_case_data".id;
ALTER TABLE "test_case_data" ADD CONSTRAINT fk_soft_delete_deleted_by_user FOREIGN KEY (deleted_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "test_case_data" ADD CONSTRAINT test_case_data_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
CREATE INDEX ix_test_case_data_deleted_at ON public.test_case_data USING btree (deleted_at);
CREATE INDEX ix_test_case_data_id ON public.test_case_data USING btree (id);
CREATE INDEX ix_test_case_data_test_case_id ON public.test_case_data USING btree (test_case_id);
CREATE UNIQUE INDEX uq_test_case_data_case_name_live ON public.test_case_data USING btree (test_case_id, name) WHERE (deleted_at IS NULL);
COMMENT ON COLUMN "test_case_data".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "test_case_data".test_case_id IS '所属测试用例ID';
COMMENT ON COLUMN "test_case_data".name IS '数据项名';
COMMENT ON COLUMN "test_case_data".value_type IS '值类型：STRING/INTEGER/NUMBER/BOOLEAN/OBJECT/ARRAY；枚举取值含义：STRING=业务状态/类别：string；INTEGER=业务状态/类别：integer；NUMBER=业务状态/类别：number；BOOLEAN=业务状态/类别：boolean；OBJECT=业务状态/类别：object；ARRAY=业务状态/类别：array。';
COMMENT ON COLUMN "test_case_data".value IS '值或引用标识';
COMMENT ON COLUMN "test_case_data".source_type IS '来源：STATIC/ENVIRONMENT/VARIABLE/RUNTIME/FAKER/FIXTURE；枚举取值含义：STATIC=业务状态/类别：static；ENVIRONMENT=业务状态/类别：environment；VARIABLE=业务状态/类别：variable；RUNTIME=业务状态/类别：runtime；FAKER=业务状态/类别：faker；FIXTURE=业务状态/类别：fixture。';
COMMENT ON COLUMN "test_case_data".required IS '是否必需';
COMMENT ON COLUMN "test_case_data".description IS '说明';
COMMENT ON COLUMN "test_case_data".config_json IS '附加配置';
COMMENT ON COLUMN "test_case_data".sort IS '排序';
COMMENT ON COLUMN "test_case_data".created_at IS '创建时间';
COMMENT ON COLUMN "test_case_data".updated_at IS '更新时间';
COMMENT ON COLUMN "test_case_data".deleted_at IS '软删除时间';
COMMENT ON COLUMN "test_case_data".deleted_by IS '删除操作人';
COMMENT ON COLUMN "test_case_data".deletion_reason IS '删除原因';
COMMENT ON COLUMN "test_case_data".deletion_batch_id IS '删除批次 ID';
COMMENT ON TABLE "test_case_data" IS '测试用例数据项';
