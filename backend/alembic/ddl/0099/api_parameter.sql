CREATE TABLE "api_parameter" (
    id integer DEFAULT nextval('api_parameter_id_seq'::regclass) NOT NULL,
    interface_id integer NOT NULL,
    name character varying(100) NOT NULL,
    location character varying(10) NOT NULL,
    type character varying(30) DEFAULT 'string'::character varying NOT NULL,
    required boolean DEFAULT false NOT NULL,
    description character varying(500),
    example text,
    default_value text,
    schema_json json,
    sort integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_api_parameter PRIMARY KEY (id)
);
ALTER SEQUENCE api_parameter_id_seq OWNED BY "api_parameter".id;
ALTER TABLE "api_parameter" ADD CONSTRAINT api_parameter_interface_id_fkey FOREIGN KEY (interface_id) REFERENCES api_interface(id) ON DELETE CASCADE;
CREATE INDEX ix_api_parameter_id ON public.api_parameter USING btree (id);
CREATE INDEX ix_api_parameter_interface_id ON public.api_parameter USING btree (interface_id);
CREATE INDEX ix_api_parameter_interface_location ON public.api_parameter USING btree (interface_id, location);
COMMENT ON COLUMN "api_parameter".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "api_parameter".interface_id IS '所属接口ID';
COMMENT ON COLUMN "api_parameter".name IS '参数名';
COMMENT ON COLUMN "api_parameter".location IS '位置：PATH/QUERY/HEADER/COOKIE/BODY；枚举取值含义：PATH=业务状态/类别：path；QUERY=业务状态/类别：query；HEADER=业务状态/类别：header；COOKIE=业务状态/类别：cookie；BODY=业务状态/类别：body。';
COMMENT ON COLUMN "api_parameter".type IS '参数类型';
COMMENT ON COLUMN "api_parameter".required IS '是否必填';
COMMENT ON COLUMN "api_parameter".description IS '参数描述';
COMMENT ON COLUMN "api_parameter".example IS '示例值';
COMMENT ON COLUMN "api_parameter".default_value IS '默认值';
COMMENT ON COLUMN "api_parameter".schema_json IS '参数 schema（含 enum/嵌套结构等）';
COMMENT ON COLUMN "api_parameter".sort IS '同位置内排序';
COMMENT ON COLUMN "api_parameter".created_at IS '创建时间';
COMMENT ON TABLE "api_parameter" IS '接口请求参数（PATH/QUERY/HEADER/COOKIE/BODY）';
