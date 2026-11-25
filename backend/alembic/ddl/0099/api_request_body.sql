CREATE TABLE "api_request_body" (
    id integer DEFAULT nextval('api_request_body_id_seq'::regclass) NOT NULL,
    interface_id integer NOT NULL,
    body_type character varying(20) DEFAULT 'none'::character varying NOT NULL,
    content_type character varying(100),
    schema_json json,
    raw_text text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_api_request_body PRIMARY KEY (id),
    CONSTRAINT uq_api_request_body_interface UNIQUE (interface_id)
);
ALTER SEQUENCE api_request_body_id_seq OWNED BY "api_request_body".id;
ALTER TABLE "api_request_body" ADD CONSTRAINT api_request_body_interface_id_fkey FOREIGN KEY (interface_id) REFERENCES api_interface(id) ON DELETE CASCADE;
CREATE INDEX ix_api_request_body_id ON public.api_request_body USING btree (id);
COMMENT ON COLUMN "api_request_body".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "api_request_body".interface_id IS '所属接口ID（一对一）';
COMMENT ON COLUMN "api_request_body".body_type IS 'body类型：none/json/form/multipart/raw；枚举取值含义：none=不使用鉴权；json=业务状态/类别：json；form=业务状态/类别：form；multipart=业务状态/类别：multipart；raw=业务状态/类别：raw。';
COMMENT ON COLUMN "api_request_body".content_type IS '实际 Content-Type';
COMMENT ON COLUMN "api_request_body".schema_json IS 'JSON Schema 树或 form/multipart 字段结构；枚举取值含义：form=业务状态/类别：form；multipart=业务状态/类别：multipart。';
COMMENT ON COLUMN "api_request_body".raw_text IS 'raw 文本体';
COMMENT ON COLUMN "api_request_body".created_at IS '创建时间';
COMMENT ON COLUMN "api_request_body".updated_at IS '更新时间';
COMMENT ON TABLE "api_request_body" IS '接口请求体（json/form/multipart/raw）';
