CREATE TABLE "test_scope_api_backfill" (
    test_case_id integer NOT NULL,
    CONSTRAINT test_scope_api_backfill_pkey PRIMARY KEY (test_case_id)
);
ALTER TABLE "test_scope_api_backfill" ADD CONSTRAINT test_scope_api_backfill_test_case_id_fkey FOREIGN KEY (test_case_id) REFERENCES test_case(id) ON DELETE CASCADE;
