CREATE TABLE "security_project_setting" (
    id integer DEFAULT nextval('security_project_setting_id_seq'::regclass) NOT NULL,
    project_id integer NOT NULL,
    allow_dev boolean DEFAULT true NOT NULL,
    allow_test boolean DEFAULT true NOT NULL,
    allow_staging boolean DEFAULT false NOT NULL,
    allow_production boolean DEFAULT false NOT NULL,
    updated_by integer,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    CONSTRAINT pk_security_project_setting PRIMARY KEY (id),
    CONSTRAINT uq_security_setting_project UNIQUE (project_id)
);
ALTER SEQUENCE security_project_setting_id_seq OWNED BY "security_project_setting".id;
ALTER TABLE "security_project_setting" ADD CONSTRAINT security_project_setting_project_id_fkey FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE;
ALTER TABLE "security_project_setting" ADD CONSTRAINT security_project_setting_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES "user"(id) ON DELETE SET NULL;
CREATE INDEX ix_security_project_setting_id ON public.security_project_setting USING btree (id);
COMMENT ON COLUMN "security_project_setting".id IS '本表记录的唯一主键，用于稳定引用该记录。';
COMMENT ON COLUMN "security_project_setting".project_id IS '所属平台项目ID';
COMMENT ON COLUMN "security_project_setting".allow_dev IS '允许在开发环境发安全变异请求';
COMMENT ON COLUMN "security_project_setting".allow_test IS '允许在测试环境发安全变异请求';
COMMENT ON COLUMN "security_project_setting".allow_staging IS '允许在预发环境执行（项目管理员可打开）；未知环境名按预发处理';
COMMENT ON COLUMN "security_project_setting".allow_production IS '仅记录意图：服务层忽略此列，生产永远拒绝';
COMMENT ON COLUMN "security_project_setting".updated_by IS '最后修改人';
COMMENT ON COLUMN "security_project_setting".created_at IS '创建时间';
COMMENT ON COLUMN "security_project_setting".updated_at IS '更新时间';
COMMENT ON COLUMN "security_project_setting".revision IS '乐观锁版本号';
COMMENT ON TABLE "security_project_setting" IS '项目级安全执行环境开关：生产永远拒绝，allow_production 仅记录意图';
