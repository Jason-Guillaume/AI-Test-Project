CREATE TABLE "agent_session_summary" (
    session_id integer NOT NULL,
    summary_version integer DEFAULT 1 NOT NULL,
    summary_kind character varying(24) DEFAULT 'EXTRACTIVE'::character varying NOT NULL,
    summary_text text NOT NULL,
    source_refs json DEFAULT '[]'::json NOT NULL,
    source_digest character varying(64) NOT NULL,
    source_through_message_id integer NOT NULL,
    expires_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT agent_session_summary_pkey PRIMARY KEY (session_id)
);
ALTER TABLE "agent_session_summary" ADD CONSTRAINT agent_session_summary_session_id_fkey FOREIGN KEY (session_id) REFERENCES agent_session(id) ON DELETE CASCADE;
COMMENT ON TABLE "agent_session_summary" IS 'Agent 会话提取式摘要索引，原始消息保留为事实来源';
