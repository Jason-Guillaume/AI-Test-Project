# 最终数据库 ER 图

本图基于当前 Alembic head `0086` 对应的 ORM 元数据生成，共 **187 张 ORM 表**。实体框仅列主键和外键字段，完整字段、索引、约束与模块分类见 [`database_inventory.md`](database_inventory.md)。

> 本机物理数据库已于2026-11-16升级到0086，共190张物理表；本图展示187张 ORM 表，不包含仍保留的两张 DB-only 表 `model_global_migration_audit` 和 `td_sandbox_task`。0083与0085各新增一张应用表。

```mermaid
erDiagram
  action_execution {
    int action_id FK
    int binding_id FK
    int flow_execution_id FK
    int id PK
  }
  agent_definition {
    int created_by FK
    int deleted_by FK
    int id PK
    int model_config_id FK
    int updated_by FK
  }
  agent_definition_revision {
    int agent_definition_id FK
    int created_by FK
    int id PK
  }
  agent_long_term_memory {
    int agent_definition_id FK
    int created_by FK
    int id PK
    int project_id FK
    int supersedes_id FK
  }
  agent_message {
    int id PK
    int session_id FK
  }
  agent_session {
    int deleted_by FK
    int id PK
    int project_id FK
    int task_agent_instance_id FK
    int task_run_id FK
    int user_id FK
  }
  agent_session_summary {
    int session_id PK, FK
  }
  agent_skill_usage_event {
    int agent_definition_id FK
    int id PK
    int skill_definition_id FK
    int task_run_id FK
  }
  agent_tool_definition_override {
    string tool_key PK
    int updated_by FK
  }
  api_change_log {
    int created_by FK
    int id PK
    int interface_id FK
  }
  api_import_record {
    int created_by FK
    int id PK
    int project_id FK
  }
  api_interface {
    int deleted_by FK
    int id PK
    int module_id FK
    int project_id FK
  }
  api_module {
    int deleted_by FK
    int id PK
    int parent_id FK
    int project_id FK
  }
  api_parameter {
    int id PK
    int interface_id FK
  }
  api_relation {
    int deleted_by FK
    int id PK
    int project_id FK
    int source_api_id FK
    int target_api_id FK
  }
  api_request_body {
    int id PK
    int interface_id FK
  }
  api_response {
    int id PK
    int interface_id FK
  }
  asr_api_binding {
    int api_interface_id FK
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_audio {
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_audio_version {
    int audio_id FK
    int id PK
  }
  asr_comparison {
    int audio_id FK
    int audio_version_id FK
    int id PK
    int job_id FK
    int project_id FK
  }
  asr_connection {
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_content_review_chunk {
    int id PK
    int input_artifact_id FK
    int response_artifact_id FK
    int review_job_id FK
  }
  asr_content_review_job {
    int comparison_id FK
    int experiment_id FK
    int id PK
    int job_id FK
    int model_config_id FK
    int primary_run_id FK
    int project_id FK
    int report_artifact_id FK
    int requested_by FK
  }
  asr_diarization_result {
    int audio_id FK
    int audio_version_id FK
    int id PK
    int processing_run_id FK
    int project_id FK
  }
  asr_diff_block {
    int comparison_id FK
    int id PK
  }
  asr_evaluation_artifact {
    int id PK
    int job_id FK
    int project_id FK
    int run_id FK
  }
  asr_experiment {
    int baseline_parameter_set_id FK
    int candidate_job_id FK
    int comparison_id FK
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_fusion_version {
    int audio_version_id FK
    int created_by FK
    int diarization_result_id FK
    int id PK
    int model_run_id FK
    int project_id FK
  }
  asr_ground_truth_version {
    int audio_id FK
    int audio_version_id FK
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_job {
    int created_by FK
    int id PK
    int project_id FK
    int schedule_id FK
  }
  asr_media_analysis {
    int audio_version_id FK
    int id PK
    int processing_run_id FK
    int project_id FK
  }
  asr_model_run {
    int audio_id FK
    int audio_version_id FK
    int connection_id FK
    int id PK
    int job_id FK
    int parameter_set_id FK
    int project_id FK
  }
  asr_parameter_set {
    int connection_id FK
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_processing_run {
    int audio_id FK
    int audio_version_id FK
    int connection_id FK
    int created_by FK
    int id PK
    int project_id FK
    int retry_of_id FK
  }
  asr_processing_work_item {
    int id PK
    int processing_run_id FK
  }
  asr_reference_sample {
    int audio_id FK
    int audio_version_id FK
    int block_id FK
    int comparison_id FK
    int id PK
    int project_id FK
    int reviewer_id FK
  }
  asr_review_audit {
    int block_id FK
    int id PK
    int reviewer_id FK
  }
  asr_schedule {
    int created_by FK
    int id PK
    int parameter_set_id FK
    int project_id FK
  }
  asr_speaker {
    int id PK
    int result_id FK
  }
  asr_speaker_assignment {
    int confirmed_speaker_id FK
    int fusion_version_id FK
    int id PK
    int segment_id FK
    int speaker_id FK
    int speaker_turn_id FK
  }
  asr_speaker_name_audit {
    int id PK
    int reviewer_id FK
    int speaker_id FK
  }
  asr_speaker_review_audit {
    int assignment_id FK
    int id PK
    int reviewer_id FK
    int speaker_id FK
  }
  asr_speaker_turn {
    int id PK
    int result_id FK
    int speaker_id FK
  }
  asr_suggestion {
    int comparison_id FK
    int created_by FK
    int id PK
    int project_id FK
  }
  asr_suggestion_job {
    int comparison_id FK
    int id PK
    int model_config_id FK
    int project_id FK
    int requested_by FK
  }
  asr_transcript_segment {
    int id PK
    int model_run_id FK
  }
  asr_tuning_item {
    int audio_id FK
    int audio_version_id FK
    int ground_truth_version_id FK
    int id PK
    int project_id FK
    int round_id FK
    int session_id FK
  }
  asr_tuning_round {
    int id PK
    int session_id FK
  }
  asr_tuning_session {
    int binding_id FK
    int created_by FK
    int id PK
    int model_config_id FK
    int project_id FK
  }
  asr_work_item {
    int id PK
    int run_id FK
  }
  asr_worker_heartbeat {
    string worker_id PK
  }
  automation_artifact {
    int execution_id FK
    int id PK
    int report_id FK
  }
  automation_callback_receipt {
    int execution_id FK
    int id PK
    int integration_config_id FK
  }
  automation_execution {
    int automation_project_id FK
    int created_by FK
    int id PK
    int integration_config_id FK
    int pipeline_binding_id FK
    int project_id FK
  }
  automation_integration_config {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  automation_jenkins_credential {
    int integration_config_id PK, FK
  }
  automation_pipeline {
    int automation_project_id FK
    int id PK
  }
  automation_project {
    int created_by FK
    int deleted_by FK
    int id PK
    int integration_config_id FK
    int notification_channel_id FK
    int project_id FK
  }
  automation_report {
    int automation_project_id FK
    int execution_id FK
    int id PK
    int project_id FK
  }
  automation_report_grant {
    int id PK
    int report_id FK
    int user_id FK
  }
  bug {
    int assignee_id FK
    int deleted_by FK
    int id PK
    int project_id FK
    int reporter_id FK
  }
  business_action {
    int deleted_by FK
    int flow_id FK
    int id PK
  }
  business_api_mapping {
    int binding_id FK
    int deleted_by FK
    int id PK
  }
  business_binding {
    int action_id FK
    int api_id FK
    int deleted_by FK
    int id PK
  }
  business_domain {
    int deleted_by FK
    int id PK
    int project_id FK
  }
  business_flow {
    int deleted_by FK
    int domain_id FK
    int id PK
    int project_id FK
  }
  business_precondition {
    int action_id FK
    int deleted_by FK
    int id PK
  }
  business_rule {
    int action_id FK
    int deleted_by FK
    int flow_id FK
    int id PK
    int project_id FK
  }
  business_state {
    int action_id FK
    int deleted_by FK
    int id PK
  }
  business_variable {
    int action_id FK
    int deleted_by FK
    int id PK
  }
  business_variable_ref {
    int deleted_by FK
    int flow_id FK
    int id PK
    int source_action_id FK
    int source_variable_id FK
    int target_action_id FK
    int target_variable_id FK
  }
  case_draft {
    int batch_id FK
    int child_agent_id FK
    int id PK
    int reviewed_by FK
    int test_case_id FK
    int work_item_id FK
  }
  case_execution {
    int id PK
    int test_case_id FK
    int test_run_id FK
  }
  case_generation_audit {
    int actor_id FK
    int batch_id FK
    int draft_id FK
    int id PK
    int project_id FK
  }
  case_generation_batch {
    int created_by FK
    int id PK
    int project_id FK
    int scope_node_id FK
    int supervisor_agent_id FK
    int task_run_id FK
  }
  data_execution {
    int case_execution_id FK
    int environment_id FK
    int id PK
    int project_id FK
    int test_run_id FK
  }
  data_lifecycle_audit_event {
    int id PK
  }
  data_pool {
    int asset_id FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  data_pool_item {
    int deleted_by FK
    int id PK
    int pool_id FK
  }
  data_pool_lease {
    int case_execution_id FK
    int id PK
    int item_id FK
    int project_id FK
    int test_run_id FK
  }
  data_provider {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  database_access_policy {
    int created_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  defect_source_link {
    int bug_id FK
    int case_execution_id FK
    int created_by FK
    int id PK
    int project_id FK
    int security_finding_id FK
  }
  environment {
    int created_by FK
    int deleted_by FK
    int id PK
    int updated_by FK
  }
  fixture {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  fixture_cache {
    int data_execution_id FK
    int fixture_id FK
    int id PK
    int project_id FK
  }
  fixture_dependency {
    int depends_on_fixture_id FK
    int fixture_id FK
    int id PK
  }
  fixture_execution {
    int data_execution_id FK
    int fixture_id FK
    int id PK
    int project_id FK
  }
  fixture_output {
    int fixture_id FK
    int id PK
  }
  fixture_step {
    int fixture_id FK
    int id PK
    int provider_id FK
  }
  flow_execution {
    int created_by FK
    int environment_id FK
    int flow_id FK
    int id PK
    int project_id FK
  }
  knowledge_base {
    int deleted_by FK
    int id PK
    int project_id FK
  }
  knowledge_chunk {
    int id PK
    int version_id FK
  }
  knowledge_document {
    int base_id FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  knowledge_document_version {
    int document_id FK
    int id PK
  }
  mcp_server {
    int created_by FK
    int deleted_by FK
    int id PK
    int updated_by FK
  }
  mock_context {
    int case_execution_id FK
    int id PK
    int project_id FK
    int test_run_id FK
  }
  mock_endpoint {
    int api_id FK
    int deleted_by FK
    int id PK
    int mock_service_id FK
    int project_id FK
  }
  mock_execution {
    int id PK
    int mock_endpoint_id FK
    int mock_scenario_id FK
    int mock_service_id FK
    int project_id FK
  }
  mock_matcher {
    int id PK
    int project_id FK
    int scenario_id FK
  }
  mock_scenario {
    int created_by FK
    int deleted_by FK
    int id PK
    int mock_endpoint_id FK
    int project_id FK
  }
  mock_service {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  model_configuration {
    int created_by FK
    int deleted_by FK
    int id PK
  }
  model_credential {
    int id PK
    int revision_id FK
  }
  model_default_binding {
    int id PK
    int profile_id FK
    int project_id FK
    int resource_id FK
    int revision_id FK
    int updated_by FK
  }
  model_legacy_binding {
    int id PK
    int resource_id FK
    int revision_id FK
  }
  model_parameter_profile {
    int created_by FK
    int id PK
    int legacy_parameter_set_id FK
    int resource_id FK
    int revision_id FK
  }
  model_resource {
    int created_by FK
    int id PK
    int legacy_model_id FK
    int project_id FK
  }
  model_resource_grant {
    int granted_by FK
    int id PK
    int project_id FK
    int resource_id FK
  }
  model_revision {
    int created_by FK
    int id PK
    int legacy_connection_id FK
    int resource_id FK
  }
  model_task_slot {
    int id PK
    int legacy_connection_id FK
    int profile_id FK
    int resource_id FK
    int revision_id FK
  }
  model_validation_run {
    int audio_id FK
    int id PK
    int profile_id FK
    int project_id FK
    int requested_by FK
    int resource_id FK
    int revision_id FK
  }
  notification {
    int deleted_by FK
    int id PK
    int organization_id FK
    int project_id FK
    int user_id FK
  }
  notification_channel {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  notification_record {
    int channel_id FK
    int id PK
    int project_id FK
    int report_id FK
  }
  organization {
    int deleted_by FK
    int id PK
    int owner_id FK
  }
  organization_member {
    int deleted_by FK
    int id PK
    int organization_id FK
    int user_id FK
  }
  project {
    int deleted_by FK
    int id PK
    int organization_id FK
    int owner_id FK
  }
  project_agent_knowledge_binding {
    int agent_id FK
    int id PK
    int project_id FK
  }
  project_environment {
    int created_by FK
    int environment_id FK
    int id PK
    int project_id FK
    int updated_by FK
  }
  project_member {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
    int user_id FK
  }
  project_outbound_target {
    int approved_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  provider_execution {
    int data_execution_id FK
    int fixture_execution_id FK
    int id PK
    int project_id FK
    int provider_id FK
  }
  recycle_bin_item {
    int id PK
  }
  runtime_call_fact {
    int agent_definition_id FK
    int agent_definition_revision_id FK
    int agent_instance_id FK
    int agent_session_id FK
    int attempt_id FK
    int execution_root_run_id FK
    int id PK
    int model_config_id FK
    int project_id FK
    int task_id FK
    int task_run_id FK
    int work_item_id FK
  }
  runtime_event_fact {
    int agent_definition_id FK
    int agent_definition_revision_id FK
    int agent_instance_id FK
    int agent_session_id FK
    int attempt_id FK
    int execution_root_run_id FK
    int id PK
    int project_id FK
    int task_id FK
    int task_run_id FK
    int work_item_id FK
  }
  runtime_trace_projection {
    int id PK
    int project_id FK
    int task_id FK
    int task_run_id FK
  }
  security_case {
    int api_id FK
    int baseline_case_id FK
    int business_action_id FK
    int confirmed_by FK
    int id PK
    int plan_id FK
    int project_id FK
    int rule_id FK
    int strategy_id FK
    int test_case_id FK
  }
  security_execution {
    int actor_id FK
    int case_execution_id FK
    int environment_id FK
    int id PK
    int project_id FK
    int security_case_id FK
    int test_run_id FK
  }
  security_finding {
    int api_id FK
    int business_action_id FK
    int case_execution_id FK
    int created_by FK
    int id PK
    int project_id FK
    int resolved_by FK
    int security_case_id FK
    int security_execution_id FK
    int strategy_id FK
    int test_run_id FK
  }
  security_mutation_rule {
    int deleted_by FK
    int id PK
    int project_id FK
    int strategy_id FK
  }
  security_plan {
    int api_id FK
    int baseline_case_id FK
    int business_action_id FK
    int confirmed_by FK
    int created_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  security_project_setting {
    int id PK
    int project_id FK
    int updated_by FK
  }
  security_scan_auth_profile {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
    int updated_by FK
  }
  security_scan_event {
    int id PK
    int job_id FK
    int project_id FK
  }
  security_scan_finding {
    int finding_id FK
    int id PK
    int job_id FK
    int project_id FK
  }
  security_scan_job {
    int approved_by FK
    int environment_id FK
    int id PK
    int initiated_by FK
    int project_id FK
    int scan_profile_id FK
    int target_id FK
    int test_run_id FK
  }
  security_scan_profile {
    int authentication_profile_id FK
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
    int updated_by FK
  }
  security_scan_target {
    int created_by FK
    int deleted_by FK
    int environment_id FK
    int id PK
    int project_id FK
    int updated_by FK
  }
  security_strategy {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  skill_definition {
    int created_by FK
    int deleted_by FK
    int id PK
    int updated_by FK
  }
  skill_definition_revision {
    int created_by FK
    int id PK
    int skill_definition_id FK
  }
  target_database_connection {
    int created_by FK
    int deleted_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  task {
    int agent_definition_id FK
    int created_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  task_agent_instance {
    int agent_definition_revision_id FK
    int id PK
    int model_config_id FK
    int parent_agent_instance_id FK
    int task_run_id FK
  }
  task_attempt {
    int id PK
    int work_item_id FK
  }
  task_command {
    int id PK
    int requested_by FK
    int task_run_id FK
  }
  task_event {
    int actor_user_id FK
    int agent_instance_id FK
    int id PK
    int task_run_id FK
  }
  task_message {
    int agent_instance_id FK
    int id PK
    int sender_instance_id FK
    int sender_user_id FK
    int task_run_id FK
  }
  task_plan {
    int created_by FK
    int id PK
    int task_run_id FK
  }
  task_resource_ref {
    int agent_instance_id FK
    int id PK
    int task_run_id FK
  }
  task_run {
    int created_by FK
    int execution_root_run_id FK
    int id PK
    int task_id FK
  }
  task_scheduler_control {
    int id PK
  }
  task_template {
    int created_by FK
    int id PK
    int project_id FK
    int updated_by FK
  }
  task_tool_invocation {
    int agent_instance_id FK
    int id PK
    int task_run_id FK
    int work_item_id FK
  }
  task_work_item {
    int agent_instance_id FK
    int id PK
    int task_run_id FK
  }
  task_work_item_dependency {
    int depends_on_id FK
    int id PK
    int work_item_id FK
  }
  test_assertion {
    int deleted_by FK
    int id PK
    int step_id FK
    int test_case_id FK
  }
  test_case {
    int agent_session_id FK
    int api_id FK
    int business_action_id FK
    int business_flow_id FK
    int created_by FK
    int deleted_by FK
    int generation_batch_id FK
    int id PK
    int project_id FK
    int test_point_id FK
  }
  test_case_asset {
    int id PK
    int test_case_id FK
  }
  test_case_data {
    int deleted_by FK
    int id PK
    int test_case_id FK
  }
  test_case_fixture {
    int fixture_id FK
    int id PK
    int test_case_id FK
  }
  test_case_import_batch {
    int created_by FK
    int id PK
    int project_id FK
    int scope_node_id FK
  }
  test_case_mock {
    int id PK
    int mock_endpoint_id FK
    int mock_scenario_id FK
    int mock_service_id FK
    int test_case_id FK
  }
  test_case_precondition {
    int deleted_by FK
    int id PK
    int test_case_id FK
  }
  test_case_scope {
    int id PK
    int scope_node_id FK
    int test_case_id FK
  }
  test_data_asset {
    int created_by FK
    int deleted_by FK
    int fixture_id FK
    int id PK
    int project_id FK
  }
  test_plan {
    int created_by FK
    int deleted_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  test_plan_suite {
    int deleted_by FK
    int id PK
    int plan_id FK
    int suite_id FK
  }
  test_point {
    int agent_session_id FK
    int api_id FK
    int business_action_id FK
    int business_flow_id FK
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
    int strategy_id FK
  }
  test_report {
    int created_by FK
    int deleted_by FK
    int environment_id FK
    int id PK
    int project_id FK
    int test_run_id FK
  }
  test_run {
    int created_by FK
    int environment_id FK
    int id PK
    int plan_id FK
    int project_id FK
  }
  test_scope_api_backfill {
    int test_case_id PK, FK
  }
  test_scope_migration_check {
    int id PK
  }
  test_scope_node {
    int created_by FK
    int deleted_by FK
    int id PK
    int parent_id FK
    int project_id FK
  }
  test_step {
    int deleted_by FK
    int id PK
    int test_case_id FK
  }
  test_strategy {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  test_suite {
    int created_by FK
    int deleted_by FK
    int id PK
    int project_id FK
  }
  test_suite_case {
    int deleted_by FK
    int id PK
    int suite_id FK
    int test_case_id FK
  }
  user {
    int deleted_by FK
    int id PK
  }
  web_agent_session {
    int agent_session_id FK
    int auth_profile_id FK
    int created_by FK
    int environment_id FK
    int id PK
    int project_id FK
    int task_agent_instance_id FK
    int task_run_id FK
  }
  web_agent_step {
    int id PK
    int session_id FK
  }
  web_artifact {
    int case_execution_id FK
    string id PK
    int project_id FK
    int test_case_id FK
  }
  web_auth_profile {
    int created_by FK
    int deleted_by FK
    int environment_id FK
    int id PK
    int project_id FK
  }
  web_case {
    int auth_profile_id FK
    int confirmed_by FK
    int test_case_id PK, FK
  }
  web_page_object {
    int deleted_by FK
    int id PK
    int project_id FK
  }
  business_binding o|--o{ action_execution : "binding_id"
  business_action o|--o{ action_execution : "action_id"
  flow_execution ||--o{ action_execution : "flow_execution_id"
  user o|--o{ agent_definition : "created_by"
  model_configuration o|--o{ agent_definition : "model_config_id"
  user o|--o{ agent_definition : "updated_by"
  user o|--o{ agent_definition : "deleted_by"
  user o|--o{ agent_definition_revision : "created_by"
  agent_definition ||--o{ agent_definition_revision : "agent_definition_id"
  agent_definition ||--o{ agent_long_term_memory : "agent_definition_id"
  project ||--o{ agent_long_term_memory : "project_id"
  user o|--o{ agent_long_term_memory : "created_by"
  agent_long_term_memory o|--o{ agent_long_term_memory : "supersedes_id"
  agent_session ||--o{ agent_message : "session_id"
  task_run o|--o{ agent_session : "task_run_id"
  project ||--o{ agent_session : "project_id"
  task_agent_instance o|--o{ agent_session : "task_agent_instance_id"
  user o|--o{ agent_session : "user_id"
  user o|--o{ agent_session : "deleted_by"
  agent_session ||--o{ agent_session_summary : "session_id"
  task_run ||--o{ agent_skill_usage_event : "task_run_id"
  agent_definition o|--o{ agent_skill_usage_event : "agent_definition_id"
  skill_definition ||--o{ agent_skill_usage_event : "skill_definition_id"
  user o|--o{ agent_tool_definition_override : "updated_by"
  user o|--o{ api_change_log : "created_by"
  api_interface ||--o{ api_change_log : "interface_id"
  user o|--o{ api_import_record : "created_by"
  project ||--o{ api_import_record : "project_id"
  api_module o|--o{ api_interface : "module_id"
  project ||--o{ api_interface : "project_id"
  user o|--o{ api_interface : "deleted_by"
  api_module o|--o{ api_module : "parent_id"
  project ||--o{ api_module : "project_id"
  user o|--o{ api_module : "deleted_by"
  api_interface ||--o{ api_parameter : "interface_id"
  api_interface ||--o{ api_relation : "target_api_id"
  api_interface ||--o{ api_relation : "source_api_id"
  project ||--o{ api_relation : "project_id"
  user o|--o{ api_relation : "deleted_by"
  api_interface ||--o{ api_request_body : "interface_id"
  api_interface ||--o{ api_response : "interface_id"
  user o|--o{ asr_api_binding : "created_by"
  api_interface o|--o{ asr_api_binding : "api_interface_id"
  project ||--o{ asr_api_binding : "project_id"
  user o|--o{ asr_audio : "created_by"
  project ||--o{ asr_audio : "project_id"
  asr_audio ||--o{ asr_audio_version : "audio_id"
  asr_audio_version o|--o{ asr_comparison : "audio_version_id"
  asr_audio ||--o{ asr_comparison : "audio_id"
  asr_job ||--o{ asr_comparison : "job_id"
  project ||--o{ asr_comparison : "project_id"
  user o|--o{ asr_connection : "created_by"
  project ||--o{ asr_connection : "project_id"
  asr_evaluation_artifact o|--o{ asr_content_review_chunk : "input_artifact_id"
  asr_content_review_job ||--o{ asr_content_review_chunk : "review_job_id"
  asr_evaluation_artifact o|--o{ asr_content_review_chunk : "response_artifact_id"
  asr_evaluation_artifact o|--o{ asr_content_review_job : "report_artifact_id"
  model_configuration ||--o{ asr_content_review_job : "model_config_id"
  asr_comparison o|--o{ asr_content_review_job : "comparison_id"
  project ||--o{ asr_content_review_job : "project_id"
  user o|--o{ asr_content_review_job : "requested_by"
  asr_model_run ||--o{ asr_content_review_job : "primary_run_id"
  asr_experiment o|--o{ asr_content_review_job : "experiment_id"
  asr_job ||--o{ asr_content_review_job : "job_id"
  asr_processing_run ||--o{ asr_diarization_result : "processing_run_id"
  asr_audio_version ||--o{ asr_diarization_result : "audio_version_id"
  asr_audio ||--o{ asr_diarization_result : "audio_id"
  project ||--o{ asr_diarization_result : "project_id"
  asr_comparison ||--o{ asr_diff_block : "comparison_id"
  asr_model_run ||--o{ asr_evaluation_artifact : "run_id"
  asr_job ||--o{ asr_evaluation_artifact : "job_id"
  project ||--o{ asr_evaluation_artifact : "project_id"
  user o|--o{ asr_experiment : "created_by"
  asr_parameter_set ||--o{ asr_experiment : "baseline_parameter_set_id"
  project ||--o{ asr_experiment : "project_id"
  asr_job o|--o{ asr_experiment : "candidate_job_id"
  asr_comparison ||--o{ asr_experiment : "comparison_id"
  asr_diarization_result ||--o{ asr_fusion_version : "diarization_result_id"
  asr_model_run ||--o{ asr_fusion_version : "model_run_id"
  user o|--o{ asr_fusion_version : "created_by"
  asr_audio_version ||--o{ asr_fusion_version : "audio_version_id"
  project ||--o{ asr_fusion_version : "project_id"
  project ||--o{ asr_ground_truth_version : "project_id"
  user o|--o{ asr_ground_truth_version : "created_by"
  asr_audio_version ||--o{ asr_ground_truth_version : "audio_version_id"
  asr_audio ||--o{ asr_ground_truth_version : "audio_id"
  user o|--o{ asr_job : "created_by"
  asr_schedule o|--o{ asr_job : "schedule_id"
  project ||--o{ asr_job : "project_id"
  asr_processing_run ||--o{ asr_media_analysis : "processing_run_id"
  asr_audio_version ||--o{ asr_media_analysis : "audio_version_id"
  project ||--o{ asr_media_analysis : "project_id"
  asr_audio ||--o{ asr_model_run : "audio_id"
  project ||--o{ asr_model_run : "project_id"
  asr_parameter_set o|--o{ asr_model_run : "parameter_set_id"
  asr_audio_version o|--o{ asr_model_run : "audio_version_id"
  asr_job ||--o{ asr_model_run : "job_id"
  asr_connection ||--o{ asr_model_run : "connection_id"
  user o|--o{ asr_parameter_set : "created_by"
  asr_connection ||--o{ asr_parameter_set : "connection_id"
  project ||--o{ asr_parameter_set : "project_id"
  user o|--o{ asr_processing_run : "created_by"
  asr_connection o|--o{ asr_processing_run : "connection_id"
  asr_audio ||--o{ asr_processing_run : "audio_id"
  asr_processing_run o|--o{ asr_processing_run : "retry_of_id"
  asr_audio_version ||--o{ asr_processing_run : "audio_version_id"
  project ||--o{ asr_processing_run : "project_id"
  asr_processing_run ||--o{ asr_processing_work_item : "processing_run_id"
  user o|--o{ asr_reference_sample : "reviewer_id"
  asr_diff_block ||--o{ asr_reference_sample : "block_id"
  asr_audio ||--o{ asr_reference_sample : "audio_id"
  asr_audio_version o|--o{ asr_reference_sample : "audio_version_id"
  asr_comparison ||--o{ asr_reference_sample : "comparison_id"
  project ||--o{ asr_reference_sample : "project_id"
  user o|--o{ asr_review_audit : "reviewer_id"
  asr_diff_block ||--o{ asr_review_audit : "block_id"
  user o|--o{ asr_schedule : "created_by"
  asr_parameter_set ||--o{ asr_schedule : "parameter_set_id"
  project ||--o{ asr_schedule : "project_id"
  asr_diarization_result ||--o{ asr_speaker : "result_id"
  asr_speaker_turn o|--o{ asr_speaker_assignment : "speaker_turn_id"
  asr_fusion_version ||--o{ asr_speaker_assignment : "fusion_version_id"
  asr_speaker o|--o{ asr_speaker_assignment : "speaker_id"
  asr_transcript_segment o|--o{ asr_speaker_assignment : "segment_id"
  asr_speaker o|--o{ asr_speaker_assignment : "confirmed_speaker_id"
  user o|--o{ asr_speaker_name_audit : "reviewer_id"
  asr_speaker ||--o{ asr_speaker_name_audit : "speaker_id"
  asr_speaker o|--o{ asr_speaker_review_audit : "speaker_id"
  user o|--o{ asr_speaker_review_audit : "reviewer_id"
  asr_speaker_assignment ||--o{ asr_speaker_review_audit : "assignment_id"
  asr_speaker o|--o{ asr_speaker_turn : "speaker_id"
  asr_diarization_result ||--o{ asr_speaker_turn : "result_id"
  asr_comparison ||--o{ asr_suggestion : "comparison_id"
  project ||--o{ asr_suggestion : "project_id"
  user o|--o{ asr_suggestion : "created_by"
  project ||--o{ asr_suggestion_job : "project_id"
  user o|--o{ asr_suggestion_job : "requested_by"
  model_configuration ||--o{ asr_suggestion_job : "model_config_id"
  asr_comparison ||--o{ asr_suggestion_job : "comparison_id"
  asr_model_run ||--o{ asr_transcript_segment : "model_run_id"
  asr_audio ||--o{ asr_tuning_item : "audio_id"
  asr_tuning_round ||--o{ asr_tuning_item : "round_id"
  asr_audio_version ||--o{ asr_tuning_item : "audio_version_id"
  project ||--o{ asr_tuning_item : "project_id"
  asr_tuning_session ||--o{ asr_tuning_item : "session_id"
  asr_ground_truth_version ||--o{ asr_tuning_item : "ground_truth_version_id"
  asr_tuning_session ||--o{ asr_tuning_round : "session_id"
  user o|--o{ asr_tuning_session : "created_by"
  model_configuration ||--o{ asr_tuning_session : "model_config_id"
  asr_api_binding ||--o{ asr_tuning_session : "binding_id"
  project ||--o{ asr_tuning_session : "project_id"
  asr_model_run ||--o{ asr_work_item : "run_id"
  automation_report o|--o{ automation_artifact : "report_id"
  automation_execution ||--o{ automation_artifact : "execution_id"
  automation_integration_config ||--o{ automation_callback_receipt : "integration_config_id"
  automation_execution o|--o{ automation_callback_receipt : "execution_id"
  automation_integration_config o|--o{ automation_execution : "integration_config_id"
  automation_project ||--o{ automation_execution : "automation_project_id"
  user o|--o{ automation_execution : "created_by"
  automation_pipeline o|--o{ automation_execution : "pipeline_binding_id"
  project ||--o{ automation_execution : "project_id"
  user o|--o{ automation_integration_config : "created_by"
  project ||--o{ automation_integration_config : "project_id"
  user o|--o{ automation_integration_config : "deleted_by"
  automation_integration_config ||--o{ automation_jenkins_credential : "integration_config_id"
  automation_project ||--o{ automation_pipeline : "automation_project_id"
  notification_channel o|--o{ automation_project : "notification_channel_id"
  project ||--o{ automation_project : "project_id"
  user o|--o{ automation_project : "created_by"
  automation_integration_config ||--o{ automation_project : "integration_config_id"
  user o|--o{ automation_project : "deleted_by"
  project ||--o{ automation_report : "project_id"
  automation_execution ||--o{ automation_report : "execution_id"
  automation_project ||--o{ automation_report : "automation_project_id"
  automation_report ||--o{ automation_report_grant : "report_id"
  user ||--o{ automation_report_grant : "user_id"
  user o|--o{ bug : "assignee_id"
  user o|--o{ bug : "reporter_id"
  project ||--o{ bug : "project_id"
  user o|--o{ bug : "deleted_by"
  business_flow ||--o{ business_action : "flow_id"
  user o|--o{ business_action : "deleted_by"
  business_binding ||--o{ business_api_mapping : "binding_id"
  user o|--o{ business_api_mapping : "deleted_by"
  api_interface o|--o{ business_binding : "api_id"
  business_action ||--o{ business_binding : "action_id"
  user o|--o{ business_binding : "deleted_by"
  project ||--o{ business_domain : "project_id"
  user o|--o{ business_domain : "deleted_by"
  business_domain ||--o{ business_flow : "domain_id"
  project ||--o{ business_flow : "project_id"
  user o|--o{ business_flow : "deleted_by"
  business_action ||--o{ business_precondition : "action_id"
  user o|--o{ business_precondition : "deleted_by"
  business_action o|--o{ business_rule : "action_id"
  business_flow o|--o{ business_rule : "flow_id"
  project ||--o{ business_rule : "project_id"
  user o|--o{ business_rule : "deleted_by"
  business_action ||--o{ business_state : "action_id"
  user o|--o{ business_state : "deleted_by"
  business_action ||--o{ business_variable : "action_id"
  user o|--o{ business_variable : "deleted_by"
  business_variable o|--o{ business_variable_ref : "target_variable_id"
  business_variable o|--o{ business_variable_ref : "source_variable_id"
  business_flow ||--o{ business_variable_ref : "flow_id"
  business_action ||--o{ business_variable_ref : "target_action_id"
  business_action ||--o{ business_variable_ref : "source_action_id"
  user o|--o{ business_variable_ref : "deleted_by"
  test_case o|--o{ case_draft : "test_case_id"
  agent_definition o|--o{ case_draft : "child_agent_id"
  task_work_item o|--o{ case_draft : "work_item_id"
  user o|--o{ case_draft : "reviewed_by"
  case_generation_batch ||--o{ case_draft : "batch_id"
  test_case o|--o{ case_execution : "test_case_id"
  test_run ||--o{ case_execution : "test_run_id"
  user o|--o{ case_generation_audit : "actor_id"
  case_draft o|--o{ case_generation_audit : "draft_id"
  case_generation_batch ||--o{ case_generation_audit : "batch_id"
  project ||--o{ case_generation_audit : "project_id"
  user o|--o{ case_generation_batch : "created_by"
  test_scope_node o|--o{ case_generation_batch : "scope_node_id"
  agent_definition o|--o{ case_generation_batch : "supervisor_agent_id"
  task_run o|--o{ case_generation_batch : "task_run_id"
  project ||--o{ case_generation_batch : "project_id"
  test_run o|--o{ data_execution : "test_run_id"
  project ||--o{ data_execution : "project_id"
  environment o|--o{ data_execution : "environment_id"
  case_execution o|--o{ data_execution : "case_execution_id"
  project ||--o{ data_pool : "project_id"
  test_data_asset o|--o{ data_pool : "asset_id"
  user o|--o{ data_pool : "deleted_by"
  data_pool ||--o{ data_pool_item : "pool_id"
  user o|--o{ data_pool_item : "deleted_by"
  case_execution o|--o{ data_pool_lease : "case_execution_id"
  test_run o|--o{ data_pool_lease : "test_run_id"
  project ||--o{ data_pool_lease : "project_id"
  data_pool_item ||--o{ data_pool_lease : "item_id"
  user o|--o{ data_provider : "created_by"
  project ||--o{ data_provider : "project_id"
  user o|--o{ data_provider : "deleted_by"
  project ||--o{ database_access_policy : "project_id"
  user o|--o{ database_access_policy : "created_by"
  environment ||--o{ database_access_policy : "environment_id"
  user o|--o{ defect_source_link : "created_by"
  case_execution o|--o{ defect_source_link : "case_execution_id"
  project ||--o{ defect_source_link : "project_id"
  security_finding o|--o{ defect_source_link : "security_finding_id"
  bug ||--o{ defect_source_link : "bug_id"
  user o|--o{ environment : "updated_by"
  user o|--o{ environment : "created_by"
  user o|--o{ environment : "deleted_by"
  user o|--o{ fixture : "created_by"
  project ||--o{ fixture : "project_id"
  user o|--o{ fixture : "deleted_by"
  data_execution o|--o{ fixture_cache : "data_execution_id"
  fixture ||--o{ fixture_cache : "fixture_id"
  project ||--o{ fixture_cache : "project_id"
  fixture ||--o{ fixture_dependency : "fixture_id"
  fixture ||--o{ fixture_dependency : "depends_on_fixture_id"
  fixture o|--o{ fixture_execution : "fixture_id"
  project ||--o{ fixture_execution : "project_id"
  data_execution ||--o{ fixture_execution : "data_execution_id"
  fixture ||--o{ fixture_output : "fixture_id"
  fixture ||--o{ fixture_step : "fixture_id"
  data_provider o|--o{ fixture_step : "provider_id"
  user o|--o{ flow_execution : "created_by"
  environment o|--o{ flow_execution : "environment_id"
  business_flow ||--o{ flow_execution : "flow_id"
  project ||--o{ flow_execution : "project_id"
  project ||--o{ knowledge_base : "project_id"
  user o|--o{ knowledge_base : "deleted_by"
  knowledge_document_version ||--o{ knowledge_chunk : "version_id"
  knowledge_base ||--o{ knowledge_document : "base_id"
  project ||--o{ knowledge_document : "project_id"
  user o|--o{ knowledge_document : "deleted_by"
  knowledge_document ||--o{ knowledge_document_version : "document_id"
  user o|--o{ mcp_server : "created_by"
  user o|--o{ mcp_server : "updated_by"
  user o|--o{ mcp_server : "deleted_by"
  test_run o|--o{ mock_context : "test_run_id"
  project ||--o{ mock_context : "project_id"
  case_execution o|--o{ mock_context : "case_execution_id"
  api_interface o|--o{ mock_endpoint : "api_id"
  mock_service ||--o{ mock_endpoint : "mock_service_id"
  project ||--o{ mock_endpoint : "project_id"
  user o|--o{ mock_endpoint : "deleted_by"
  mock_scenario o|--o{ mock_execution : "mock_scenario_id"
  mock_endpoint o|--o{ mock_execution : "mock_endpoint_id"
  mock_service o|--o{ mock_execution : "mock_service_id"
  project ||--o{ mock_execution : "project_id"
  mock_scenario ||--o{ mock_matcher : "scenario_id"
  project ||--o{ mock_matcher : "project_id"
  user o|--o{ mock_scenario : "created_by"
  mock_endpoint ||--o{ mock_scenario : "mock_endpoint_id"
  project ||--o{ mock_scenario : "project_id"
  user o|--o{ mock_scenario : "deleted_by"
  user o|--o{ mock_service : "created_by"
  project ||--o{ mock_service : "project_id"
  user o|--o{ mock_service : "deleted_by"
  user o|--o{ model_configuration : "created_by"
  user o|--o{ model_configuration : "deleted_by"
  model_revision ||--o{ model_credential : "revision_id"
  model_resource ||--o{ model_default_binding : "resource_id"
  user o|--o{ model_default_binding : "updated_by"
  model_revision ||--o{ model_default_binding : "revision_id"
  project o|--o{ model_default_binding : "project_id"
  model_parameter_profile o|--o{ model_default_binding : "profile_id"
  model_revision ||--o{ model_legacy_binding : "revision_id"
  model_resource ||--o{ model_legacy_binding : "resource_id"
  user o|--o{ model_parameter_profile : "created_by"
  asr_parameter_set o|--o{ model_parameter_profile : "legacy_parameter_set_id"
  model_revision ||--o{ model_parameter_profile : "revision_id"
  model_resource ||--o{ model_parameter_profile : "resource_id"
  model_configuration o|--o{ model_resource : "legacy_model_id"
  project o|--o{ model_resource : "project_id"
  user o|--o{ model_resource : "created_by"
  project ||--o{ model_resource_grant : "project_id"
  model_resource ||--o{ model_resource_grant : "resource_id"
  user o|--o{ model_resource_grant : "granted_by"
  user o|--o{ model_revision : "created_by"
  asr_connection o|--o{ model_revision : "legacy_connection_id"
  model_resource ||--o{ model_revision : "resource_id"
  model_parameter_profile o|--o{ model_task_slot : "profile_id"
  model_revision ||--o{ model_task_slot : "revision_id"
  model_resource ||--o{ model_task_slot : "resource_id"
  asr_connection o|--o{ model_task_slot : "legacy_connection_id"
  model_revision ||--o{ model_validation_run : "revision_id"
  asr_audio o|--o{ model_validation_run : "audio_id"
  model_parameter_profile o|--o{ model_validation_run : "profile_id"
  model_resource ||--o{ model_validation_run : "resource_id"
  user o|--o{ model_validation_run : "requested_by"
  project o|--o{ model_validation_run : "project_id"
  organization o|--o{ notification : "organization_id"
  project o|--o{ notification : "project_id"
  user ||--o{ notification : "user_id"
  user o|--o{ notification : "deleted_by"
  user o|--o{ notification_channel : "created_by"
  project ||--o{ notification_channel : "project_id"
  user o|--o{ notification_channel : "deleted_by"
  project ||--o{ notification_record : "project_id"
  test_report o|--o{ notification_record : "report_id"
  notification_channel ||--o{ notification_record : "channel_id"
  user ||--o{ organization : "owner_id"
  user o|--o{ organization : "deleted_by"
  organization ||--o{ organization_member : "organization_id"
  user ||--o{ organization_member : "user_id"
  user o|--o{ organization_member : "deleted_by"
  organization o|--o{ project : "organization_id"
  user ||--o{ project : "owner_id"
  user o|--o{ project : "deleted_by"
  project ||--o{ project_agent_knowledge_binding : "project_id"
  agent_definition ||--o{ project_agent_knowledge_binding : "agent_id"
  user o|--o{ project_environment : "updated_by"
  user o|--o{ project_environment : "created_by"
  environment ||--o{ project_environment : "environment_id"
  project ||--o{ project_environment : "project_id"
  user ||--o{ project_member : "created_by"
  user ||--o{ project_member : "user_id"
  project ||--o{ project_member : "project_id"
  user o|--o{ project_member : "deleted_by"
  user ||--o{ project_outbound_target : "approved_by"
  project ||--o{ project_outbound_target : "project_id"
  user o|--o{ project_outbound_target : "deleted_by"
  data_provider o|--o{ provider_execution : "provider_id"
  project ||--o{ provider_execution : "project_id"
  data_execution o|--o{ provider_execution : "data_execution_id"
  fixture_execution o|--o{ provider_execution : "fixture_execution_id"
  task ||--o{ runtime_call_fact : "task_id"
  model_configuration o|--o{ runtime_call_fact : "model_config_id"
  agent_definition o|--o{ runtime_call_fact : "agent_definition_id"
  agent_session o|--o{ runtime_call_fact : "agent_session_id"
  task_work_item ||--o{ runtime_call_fact : "work_item_id"
  project ||--o{ runtime_call_fact : "project_id"
  agent_definition_revision o|--o{ runtime_call_fact : "agent_definition_revision_id"
  task_agent_instance o|--o{ runtime_call_fact : "agent_instance_id"
  task_attempt ||--o{ runtime_call_fact : "attempt_id"
  task_run ||--o{ runtime_call_fact : "execution_root_run_id,task_id"
  task_run ||--o{ runtime_call_fact : "task_run_id,task_id"
  agent_session o|--o{ runtime_event_fact : "agent_session_id"
  task_work_item o|--o{ runtime_event_fact : "work_item_id"
  project ||--o{ runtime_event_fact : "project_id"
  agent_definition_revision o|--o{ runtime_event_fact : "agent_definition_revision_id"
  task_agent_instance o|--o{ runtime_event_fact : "agent_instance_id"
  task_attempt o|--o{ runtime_event_fact : "attempt_id"
  task o|--o{ runtime_event_fact : "task_id"
  agent_definition o|--o{ runtime_event_fact : "agent_definition_id"
  task_run o|--o{ runtime_event_fact : "execution_root_run_id,task_id"
  task_run o|--o{ runtime_event_fact : "task_run_id,task_id"
  task ||--o{ runtime_trace_projection : "task_id"
  project ||--o{ runtime_trace_projection : "project_id"
  task_run ||--o{ runtime_trace_projection : "task_run_id,task_id"
  business_action o|--o{ security_case : "business_action_id"
  security_mutation_rule o|--o{ security_case : "rule_id"
  test_case o|--o{ security_case : "baseline_case_id"
  test_case ||--o{ security_case : "test_case_id"
  user o|--o{ security_case : "confirmed_by"
  api_interface o|--o{ security_case : "api_id"
  security_strategy o|--o{ security_case : "strategy_id"
  security_plan o|--o{ security_case : "plan_id"
  project ||--o{ security_case : "project_id"
  test_run ||--o{ security_execution : "test_run_id"
  environment o|--o{ security_execution : "environment_id"
  case_execution ||--o{ security_execution : "case_execution_id"
  project ||--o{ security_execution : "project_id"
  user o|--o{ security_execution : "actor_id"
  security_case o|--o{ security_execution : "security_case_id"
  user o|--o{ security_finding : "resolved_by"
  security_case o|--o{ security_finding : "security_case_id"
  business_action o|--o{ security_finding : "business_action_id"
  security_execution o|--o{ security_finding : "security_execution_id"
  test_run o|--o{ security_finding : "test_run_id"
  user o|--o{ security_finding : "created_by"
  security_strategy o|--o{ security_finding : "strategy_id"
  api_interface o|--o{ security_finding : "api_id"
  case_execution o|--o{ security_finding : "case_execution_id"
  project ||--o{ security_finding : "project_id"
  project o|--o{ security_mutation_rule : "project_id"
  security_strategy ||--o{ security_mutation_rule : "strategy_id"
  user o|--o{ security_mutation_rule : "deleted_by"
  business_action o|--o{ security_plan : "business_action_id"
  api_interface o|--o{ security_plan : "api_id"
  user o|--o{ security_plan : "confirmed_by"
  environment o|--o{ security_plan : "environment_id"
  test_case o|--o{ security_plan : "baseline_case_id"
  project ||--o{ security_plan : "project_id"
  user o|--o{ security_plan : "created_by"
  user o|--o{ security_project_setting : "updated_by"
  project ||--o{ security_project_setting : "project_id"
  project ||--o{ security_scan_auth_profile : "project_id"
  user o|--o{ security_scan_auth_profile : "updated_by"
  user o|--o{ security_scan_auth_profile : "created_by"
  user o|--o{ security_scan_auth_profile : "deleted_by"
  project ||--o{ security_scan_event : "project_id"
  security_scan_job ||--o{ security_scan_event : "job_id"
  security_finding ||--o{ security_scan_finding : "finding_id"
  security_scan_job ||--o{ security_scan_finding : "job_id"
  project ||--o{ security_scan_finding : "project_id"
  environment o|--o{ security_scan_job : "environment_id"
  project ||--o{ security_scan_job : "project_id"
  user o|--o{ security_scan_job : "approved_by"
  security_scan_profile ||--o{ security_scan_job : "scan_profile_id"
  security_scan_target ||--o{ security_scan_job : "target_id"
  test_run o|--o{ security_scan_job : "test_run_id"
  user o|--o{ security_scan_job : "initiated_by"
  user o|--o{ security_scan_profile : "updated_by"
  security_scan_auth_profile o|--o{ security_scan_profile : "authentication_profile_id"
  user o|--o{ security_scan_profile : "created_by"
  project o|--o{ security_scan_profile : "project_id"
  user o|--o{ security_scan_profile : "deleted_by"
  user o|--o{ security_scan_target : "updated_by"
  environment o|--o{ security_scan_target : "environment_id"
  user o|--o{ security_scan_target : "created_by"
  project ||--o{ security_scan_target : "project_id"
  user o|--o{ security_scan_target : "deleted_by"
  user o|--o{ security_strategy : "created_by"
  project o|--o{ security_strategy : "project_id"
  user o|--o{ security_strategy : "deleted_by"
  user o|--o{ skill_definition : "updated_by"
  user o|--o{ skill_definition : "created_by"
  user o|--o{ skill_definition : "deleted_by"
  user o|--o{ skill_definition_revision : "created_by"
  skill_definition ||--o{ skill_definition_revision : "skill_definition_id"
  environment ||--o{ target_database_connection : "environment_id"
  project ||--o{ target_database_connection : "project_id"
  user o|--o{ target_database_connection : "created_by"
  user o|--o{ target_database_connection : "deleted_by"
  project ||--o{ task : "project_id"
  environment o|--o{ task : "environment_id"
  agent_definition o|--o{ task : "agent_definition_id"
  user o|--o{ task : "created_by"
  task_run ||--o{ task_agent_instance : "task_run_id"
  model_configuration o|--o{ task_agent_instance : "model_config_id"
  task_agent_instance o|--o{ task_agent_instance : "parent_agent_instance_id"
  agent_definition_revision o|--o{ task_agent_instance : "agent_definition_revision_id"
  task_work_item ||--o{ task_attempt : "work_item_id"
  user o|--o{ task_command : "requested_by"
  task_run ||--o{ task_command : "task_run_id"
  task_run ||--o{ task_event : "task_run_id"
  task_agent_instance o|--o{ task_event : "agent_instance_id"
  user o|--o{ task_event : "actor_user_id"
  task_agent_instance o|--o{ task_message : "sender_instance_id"
  user o|--o{ task_message : "sender_user_id"
  task_agent_instance ||--o{ task_message : "agent_instance_id"
  task_run ||--o{ task_message : "task_run_id"
  user o|--o{ task_plan : "created_by"
  task_run ||--o{ task_plan : "task_run_id"
  task_agent_instance o|--o{ task_resource_ref : "agent_instance_id"
  task_run ||--o{ task_resource_ref : "task_run_id"
  user o|--o{ task_run : "created_by"
  task ||--o{ task_run : "task_id"
  task_run o|--o{ task_run : "execution_root_run_id,task_id"
  user o|--o{ task_template : "updated_by"
  user o|--o{ task_template : "created_by"
  project ||--o{ task_template : "project_id"
  task_work_item ||--o{ task_tool_invocation : "work_item_id"
  task_run ||--o{ task_tool_invocation : "task_run_id"
  task_agent_instance o|--o{ task_tool_invocation : "agent_instance_id"
  task_agent_instance o|--o{ task_work_item : "agent_instance_id"
  task_run ||--o{ task_work_item : "task_run_id"
  task_work_item ||--o{ task_work_item_dependency : "depends_on_id"
  task_work_item ||--o{ task_work_item_dependency : "work_item_id"
  test_step o|--o{ test_assertion : "step_id"
  test_case ||--o{ test_assertion : "test_case_id"
  user o|--o{ test_assertion : "deleted_by"
  case_generation_batch o|--o{ test_case : "generation_batch_id"
  business_action o|--o{ test_case : "business_action_id"
  api_interface o|--o{ test_case : "api_id"
  project ||--o{ test_case : "project_id"
  user o|--o{ test_case : "created_by"
  agent_session o|--o{ test_case : "agent_session_id"
  business_flow o|--o{ test_case : "business_flow_id"
  test_point o|--o{ test_case : "test_point_id"
  user o|--o{ test_case : "deleted_by"
  test_case ||--o{ test_case_asset : "test_case_id"
  test_case ||--o{ test_case_data : "test_case_id"
  user o|--o{ test_case_data : "deleted_by"
  fixture ||--o{ test_case_fixture : "fixture_id"
  test_case ||--o{ test_case_fixture : "test_case_id"
  test_scope_node o|--o{ test_case_import_batch : "scope_node_id"
  user o|--o{ test_case_import_batch : "created_by"
  project ||--o{ test_case_import_batch : "project_id"
  mock_service ||--o{ test_case_mock : "mock_service_id"
  test_case ||--o{ test_case_mock : "test_case_id"
  mock_scenario ||--o{ test_case_mock : "mock_scenario_id"
  mock_endpoint ||--o{ test_case_mock : "mock_endpoint_id"
  test_case ||--o{ test_case_precondition : "test_case_id"
  user o|--o{ test_case_precondition : "deleted_by"
  test_case ||--o{ test_case_scope : "test_case_id"
  test_scope_node ||--o{ test_case_scope : "scope_node_id"
  project ||--o{ test_data_asset : "project_id"
  user o|--o{ test_data_asset : "created_by"
  fixture o|--o{ test_data_asset : "fixture_id"
  user o|--o{ test_data_asset : "deleted_by"
  user o|--o{ test_plan : "created_by"
  environment o|--o{ test_plan : "environment_id"
  project ||--o{ test_plan : "project_id"
  user o|--o{ test_plan : "deleted_by"
  test_suite ||--o{ test_plan_suite : "suite_id"
  test_plan ||--o{ test_plan_suite : "plan_id"
  user o|--o{ test_plan_suite : "deleted_by"
  user o|--o{ test_point : "created_by"
  business_action o|--o{ test_point : "business_action_id"
  api_interface o|--o{ test_point : "api_id"
  project ||--o{ test_point : "project_id"
  agent_session o|--o{ test_point : "agent_session_id"
  business_flow o|--o{ test_point : "business_flow_id"
  test_strategy o|--o{ test_point : "strategy_id"
  user o|--o{ test_point : "deleted_by"
  user o|--o{ test_report : "created_by"
  test_run o|--o{ test_report : "test_run_id"
  environment o|--o{ test_report : "environment_id"
  project ||--o{ test_report : "project_id"
  user o|--o{ test_report : "deleted_by"
  test_plan o|--o{ test_run : "plan_id"
  project ||--o{ test_run : "project_id"
  user o|--o{ test_run : "created_by"
  environment o|--o{ test_run : "environment_id"
  test_case ||--o{ test_scope_api_backfill : "test_case_id"
  user o|--o{ test_scope_node : "created_by"
  test_scope_node o|--o{ test_scope_node : "parent_id"
  project ||--o{ test_scope_node : "project_id"
  user o|--o{ test_scope_node : "deleted_by"
  test_case ||--o{ test_step : "test_case_id"
  user o|--o{ test_step : "deleted_by"
  user o|--o{ test_strategy : "created_by"
  project ||--o{ test_strategy : "project_id"
  user o|--o{ test_strategy : "deleted_by"
  user o|--o{ test_suite : "created_by"
  project ||--o{ test_suite : "project_id"
  user o|--o{ test_suite : "deleted_by"
  test_suite ||--o{ test_suite_case : "suite_id"
  test_case ||--o{ test_suite_case : "test_case_id"
  user o|--o{ test_suite_case : "deleted_by"
  user o|--o{ user : "deleted_by"
  environment ||--o{ web_agent_session : "environment_id"
  agent_session o|--o{ web_agent_session : "agent_session_id"
  task_run o|--o{ web_agent_session : "task_run_id"
  web_auth_profile o|--o{ web_agent_session : "auth_profile_id"
  project ||--o{ web_agent_session : "project_id"
  task_agent_instance o|--o{ web_agent_session : "task_agent_instance_id"
  user o|--o{ web_agent_session : "created_by"
  web_agent_session ||--o{ web_agent_step : "session_id"
  case_execution o|--o{ web_artifact : "case_execution_id"
  test_case o|--o{ web_artifact : "test_case_id"
  project ||--o{ web_artifact : "project_id"
  user o|--o{ web_auth_profile : "created_by"
  environment ||--o{ web_auth_profile : "environment_id"
  project ||--o{ web_auth_profile : "project_id"
  user o|--o{ web_auth_profile : "deleted_by"
  user o|--o{ web_case : "confirmed_by"
  web_auth_profile o|--o{ web_case : "auth_profile_id"
  test_case ||--o{ web_case : "test_case_id"
  project ||--o{ web_page_object : "project_id"
  user o|--o{ web_page_object : "deleted_by"
```
