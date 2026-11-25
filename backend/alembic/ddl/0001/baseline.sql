CREATE SEQUENCE user_id_seq AS integer;
CREATE SEQUENCE organization_id_seq AS integer;
CREATE SEQUENCE organization_member_id_seq AS integer;
CREATE SEQUENCE project_id_seq AS integer;
CREATE SEQUENCE project_member_id_seq AS integer;
CREATE SEQUENCE project_outbound_target_id_seq AS integer;
CREATE SEQUENCE model_configuration_id_seq AS integer;
CREATE SEQUENCE environment_id_seq AS integer;
CREATE SEQUENCE notification_id_seq AS integer;
CREATE TABLE "user" (
    id integer DEFAULT nextval('user_id_seq'::regclass) NOT NULL,
    username character varying(50),
    hashed_password character varying(255),
    role character varying(20) DEFAULT 'test'::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    token_version integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT user_pkey PRIMARY KEY (id)
);
CREATE TABLE "organization" (
    id integer DEFAULT nextval('organization_id_seq'::regclass) NOT NULL,
    name character varying(100) NOT NULL,
    owner_id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT organization_pkey PRIMARY KEY (id)
);
CREATE TABLE "organization_member" (
    id integer DEFAULT nextval('organization_member_id_seq'::regclass) NOT NULL,
    organization_id integer NOT NULL,
    user_id integer NOT NULL,
    role character varying(20) DEFAULT 'member'::character varying NOT NULL,
    agent_enabled boolean DEFAULT false NOT NULL,
    allowed_model_ids json DEFAULT '[]'::json NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT organization_member_pkey PRIMARY KEY (id),
    CONSTRAINT uq_organization_member_user UNIQUE (organization_id, user_id)
);
CREATE TABLE "project" (
    id integer DEFAULT nextval('project_id_seq'::regclass) NOT NULL,
    name character varying(100) NOT NULL,
    description character varying(500),
    owner_id integer NOT NULL,
    organization_id integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_pkey PRIMARY KEY (id)
);
CREATE TABLE "project_member" (
    id integer DEFAULT nextval('project_member_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    user_id integer NOT NULL,
    role character varying(30) DEFAULT 'member'::character varying NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_project_member PRIMARY KEY (id),
    CONSTRAINT uq_project_member_project_user UNIQUE (project_id, user_id)
);
CREATE TABLE "project_outbound_target" (
    id integer DEFAULT nextval('project_outbound_target_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    scheme character varying(8) NOT NULL,
    host character varying(253) NOT NULL,
    port integer NOT NULL,
    is_production boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    approved_by integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_outbound_target_pkey PRIMARY KEY (id),
    CONSTRAINT uq_project_outbound_target UNIQUE (project_id, scheme, host, port)
);
CREATE TABLE "model_configuration" (
    id integer DEFAULT nextval('model_configuration_id_seq'::regclass) NOT NULL,
    domain_id character varying(100) NOT NULL,
    label character varying(120) NOT NULL,
    provider character varying(50) DEFAULT 'openai-compatible'::character varying NOT NULL,
    api_base character varying(500) NOT NULL,
    api_key_encrypted text,
    model_name character varying(200) NOT NULL,
    temperature double precision DEFAULT 0.2 NOT NULL,
    max_tokens integer DEFAULT 4096 NOT NULL,
    timeout integer DEFAULT 60 NOT NULL,
    cost_per_1k_input double precision DEFAULT 0 NOT NULL,
    cost_per_1k_output double precision DEFAULT 0 NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    fallback_model_ids json DEFAULT '[]'::json NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT model_configuration_domain_id_key UNIQUE (domain_id),
    CONSTRAINT model_configuration_pkey PRIMARY KEY (id)
);
CREATE TABLE "environment" (
    id integer DEFAULT nextval('environment_id_seq'::regclass) NOT NULL,
    name character varying(50) NOT NULL,
    display_name character varying(100) DEFAULT ''::character varying NOT NULL,
    base_url character varying(500) DEFAULT ''::character varying NOT NULL,
    gateway_prefix character varying(200) DEFAULT ''::character varying NOT NULL,
    default_headers json DEFAULT '{}'::json NOT NULL,
    description text,
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_by integer,
    updated_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT environment_pkey PRIMARY KEY (id)
);
CREATE TABLE "notification" (
    id integer DEFAULT nextval('notification_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    project_id integer,
    organization_id integer,
    event_type character varying(100) NOT NULL,
    title character varying(200) NOT NULL,
    body text,
    payload json,
    is_read boolean DEFAULT false NOT NULL,
    read_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT notification_pkey PRIMARY KEY (id)
);
ALTER SEQUENCE user_id_seq OWNED BY "user".id;
CREATE INDEX ix_user_id ON public."user" USING btree (id);
CREATE UNIQUE INDEX ix_user_username ON public."user" USING btree (username);
ALTER SEQUENCE organization_id_seq OWNED BY "organization".id;
ALTER TABLE "organization" ADD CONSTRAINT organization_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES "user"(id);
CREATE INDEX ix_organization_owner_id ON public.organization USING btree (owner_id);
ALTER SEQUENCE organization_member_id_seq OWNED BY "organization_member".id;
ALTER TABLE "organization_member" ADD CONSTRAINT organization_member_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES organization(id) ON DELETE CASCADE;
ALTER TABLE "organization_member" ADD CONSTRAINT organization_member_user_id_fkey FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE;
CREATE INDEX ix_organization_member_organization_id ON public.organization_member USING btree (organization_id);
CREATE INDEX ix_organization_member_user_id ON public.organization_member USING btree (user_id);
ALTER SEQUENCE project_id_seq OWNED BY "project".id;
ALTER TABLE "project" ADD CONSTRAINT project_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES organization(id);
ALTER TABLE "project" ADD CONSTRAINT project_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES "user"(id);
CREATE INDEX ix_project_id ON public.project USING btree (id);
CREATE UNIQUE INDEX ix_project_name ON public.project USING btree (name);
CREATE INDEX ix_project_organization_id ON public.project USING btree (organization_id);
ALTER SEQUENCE project_member_id_seq OWNED BY "project_member".id;
ALTER TABLE "project_member" ADD CONSTRAINT project_member_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id);
ALTER TABLE "project_member" ADD CONSTRAINT project_member_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
ALTER TABLE "project_member" ADD CONSTRAINT project_member_user_id_fkey FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE;
CREATE INDEX ix_project_member_id ON public.project_member USING btree (id);
CREATE INDEX ix_project_member_project_id ON public.project_member USING btree (project_id);
CREATE INDEX ix_project_member_user_id ON public.project_member USING btree (user_id);
ALTER SEQUENCE project_outbound_target_id_seq OWNED BY "project_outbound_target".id;
ALTER TABLE "project_outbound_target" ADD CONSTRAINT project_outbound_target_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES "user"(id);
ALTER TABLE "project_outbound_target" ADD CONSTRAINT project_outbound_target_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
CREATE INDEX ix_project_outbound_target_project_id ON public.project_outbound_target USING btree (project_id);
ALTER SEQUENCE model_configuration_id_seq OWNED BY "model_configuration".id;
ALTER TABLE "model_configuration" ADD CONSTRAINT model_configuration_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id);
CREATE INDEX ix_model_configuration_domain_id ON public.model_configuration USING btree (domain_id);
CREATE INDEX ix_model_configuration_id ON public.model_configuration USING btree (id);
CREATE INDEX ix_model_configuration_is_default ON public.model_configuration USING btree (is_default);
CREATE INDEX ix_model_configuration_is_enabled ON public.model_configuration USING btree (is_enabled);
ALTER SEQUENCE environment_id_seq OWNED BY "environment".id;
ALTER TABLE "environment" ADD CONSTRAINT environment_created_by_fkey FOREIGN KEY (created_by) REFERENCES "user"(id) ON DELETE SET NULL;
ALTER TABLE "environment" ADD CONSTRAINT environment_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES "user"(id) ON DELETE SET NULL;
CREATE INDEX ix_environment_active_default ON public.environment USING btree (is_active, is_default);
CREATE INDEX ix_environment_created_by ON public.environment USING btree (created_by);
CREATE INDEX ix_environment_id ON public.environment USING btree (id);
CREATE INDEX ix_environment_is_active ON public.environment USING btree (is_active);
CREATE INDEX ix_environment_is_default ON public.environment USING btree (is_default);
CREATE UNIQUE INDEX ix_environment_name ON public.environment USING btree (name);
CREATE INDEX ix_environment_updated_by ON public.environment USING btree (updated_by);
ALTER SEQUENCE notification_id_seq OWNED BY "notification".id;
ALTER TABLE "notification" ADD CONSTRAINT notification_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES organization(id) ON DELETE CASCADE;
ALTER TABLE "notification" ADD CONSTRAINT notification_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
ALTER TABLE "notification" ADD CONSTRAINT notification_user_id_fkey FOREIGN KEY (user_id) REFERENCES "user"(id) ON DELETE CASCADE;
CREATE INDEX ix_notification_created_at ON public.notification USING btree (created_at);
CREATE INDEX ix_notification_event_type ON public.notification USING btree (event_type);
CREATE INDEX ix_notification_is_read ON public.notification USING btree (is_read);
CREATE INDEX ix_notification_organization_id ON public.notification USING btree (organization_id);
CREATE INDEX ix_notification_project_id ON public.notification USING btree (project_id);
CREATE INDEX ix_notification_user_id ON public.notification USING btree (user_id);
CREATE INDEX ix_notification_user_read_created ON public.notification USING btree (user_id, is_read, created_at);
COMMENT ON COLUMN "user".username IS '用户名';
COMMENT ON COLUMN "user".hashed_password IS '加密密码';
COMMENT ON COLUMN "user".role IS '平台角色： admin/test/dev';
COMMENT ON COLUMN "user".is_active IS '是否激活';
COMMENT ON COLUMN "user".token_version IS 'JWT 撤销版本：修改密码、禁用、调整角色时递增使旧令牌失效';
COMMENT ON COLUMN "user".created_at IS '注册时间';
COMMENT ON COLUMN "user".updated_at IS '更新时间';
COMMENT ON TABLE "user" IS '平台登录用户、角色及账号状态';
COMMENT ON TABLE "organization" IS '组织边界及负责人';
COMMENT ON COLUMN "organization_member".role IS '组织角色： owner/admin/member';
COMMENT ON COLUMN "organization_member".agent_enabled IS '是否开放智能体能力';
COMMENT ON COLUMN "organization_member".allowed_model_ids IS '允许的模型 domain_id 列表';
COMMENT ON TABLE "organization_member" IS '组织成员、Agent 开放权限及模型分配';
COMMENT ON COLUMN "project".name IS '项目名称';
COMMENT ON COLUMN "project".description IS '项目描述';
COMMENT ON COLUMN "project".owner_id IS '负责人ID';
COMMENT ON COLUMN "project".created_at IS '创建时间';
COMMENT ON COLUMN "project".updated_at IS '更新时间';
COMMENT ON TABLE "project" IS '测试项目及负责人信息';
COMMENT ON COLUMN "project_member".role IS '项目角色： viewer/member/editor';
COMMENT ON TABLE "project_member" IS '项目成员及其数据访问角色';
COMMENT ON TABLE "project_outbound_target" IS '项目出站目标、协议端口及生产目标授权';
COMMENT ON COLUMN "model_configuration".domain_id IS '后端生成的稳定逻辑ID';
COMMENT ON COLUMN "model_configuration".label IS '前端展示名称';
COMMENT ON COLUMN "model_configuration".provider IS '模型供应商';
COMMENT ON COLUMN "model_configuration".api_base IS 'OpenAI兼容接口根地址';
COMMENT ON COLUMN "model_configuration".api_key_encrypted IS '加密后的API Key';
COMMENT ON COLUMN "model_configuration".model_name IS '供应商模型名称';
COMMENT ON COLUMN "model_configuration".temperature IS '采样温度';
COMMENT ON COLUMN "model_configuration".max_tokens IS '最大输出Token';
COMMENT ON COLUMN "model_configuration".timeout IS '请求超时秒数';
COMMENT ON COLUMN "model_configuration".cost_per_1k_input IS '千输入Token成本';
COMMENT ON COLUMN "model_configuration".cost_per_1k_output IS '千输出Token成本';
COMMENT ON COLUMN "model_configuration".is_enabled IS '是否启用';
COMMENT ON COLUMN "model_configuration".is_default IS '是否默认模型';
COMMENT ON COLUMN "model_configuration".fallback_model_ids IS '有序备用模型配置 ID';
COMMENT ON COLUMN "model_configuration".sort_order IS '展示顺序';
COMMENT ON COLUMN "model_configuration".created_by IS '创建人ID';
COMMENT ON COLUMN "model_configuration".created_at IS '创建时间';
COMMENT ON COLUMN "model_configuration".updated_at IS '更新时间';
COMMENT ON TABLE "model_configuration" IS '大模型连接、调用参数及启停状态配置';
COMMENT ON COLUMN "environment".name IS '环境唯一标识，如 dev/test';
COMMENT ON COLUMN "environment".display_name IS '展示名称';
COMMENT ON COLUMN "environment".base_url IS '被测服务基础URL';
COMMENT ON COLUMN "environment".gateway_prefix IS '网关路径前缀';
COMMENT ON COLUMN "environment".default_headers IS '该环境默认请求头';
COMMENT ON COLUMN "environment".description IS '环境用途说明';
COMMENT ON COLUMN "environment".is_default IS '未指定环境时的兜底';
COMMENT ON COLUMN "environment".is_active IS '停用后不可被选择';
COMMENT ON TABLE "environment" IS '接口执行环境路由配置';
COMMENT ON COLUMN "notification".event_type IS '事件类型';
COMMENT ON COLUMN "notification".title IS '标题';
COMMENT ON COLUMN "notification".body IS '正文';
COMMENT ON COLUMN "notification".payload IS '结构化上下文';
COMMENT ON COLUMN "notification".is_read IS '是否已读';
COMMENT ON COLUMN "notification".read_at IS '已读时间';
COMMENT ON TABLE "notification" IS '用户通知收件箱';
