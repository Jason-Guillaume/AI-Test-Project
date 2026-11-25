CREATE TABLE "api_response" (
    id integer DEFAULT nextval('api_response_id_seq'::regclass) NOT NULL,
    interface_id integer NOT NULL,
    status_code integer,
    description character varying(500),
    schema_json json,
    example_json text,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    response_key character varying(16) NOT NULL,
    CONSTRAINT pk_api_response PRIMARY KEY (id)
);
ALTER SEQUENCE api_response_id_seq OWNED BY "api_response".id;
ALTER TABLE "api_response" ADD CONSTRAINT api_response_interface_id_fkey FOREIGN KEY (interface_id) REFERENCES api_interface(id) ON DELETE CASCADE;
CREATE INDEX ix_api_response_id ON public.api_response USING btree (id);
CREATE INDEX ix_api_response_interface_id ON public.api_response USING btree (interface_id);
CREATE INDEX ix_api_response_interface_status ON public.api_response USING btree (interface_id, status_code);
COMMENT ON COLUMN "api_response".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "api_response".interface_id IS '所属接口ID';
COMMENT ON COLUMN "api_response".status_code IS '具体 HTTP 状态码；范围码和 default 为空';
COMMENT ON COLUMN "api_response".description IS '响应描述';
COMMENT ON COLUMN "api_response".schema_json IS '响应 JSON Schema 结构';
COMMENT ON COLUMN "api_response".example_json IS '响应示例 JSON 文本';
COMMENT ON COLUMN "api_response".sort IS '排序';
COMMENT ON COLUMN "api_response".created_at IS '创建时间';
COMMENT ON COLUMN "api_response".updated_at IS '更新时间';
COMMENT ON TABLE "api_response" IS '接口响应（按 HTTP status_code 保存结构）';
