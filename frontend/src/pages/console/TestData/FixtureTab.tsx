// Fixture Tab：左树 + 右详情。
//
// §7.3：左树按 entity_type 分组（FixtureTree），右详情 FixtureDetail。
// 顶部「新增 Fixture」打开创建弹窗（最小字段：name/fixture_key/entity_type/scope/status，
// 步骤与输出在详情里逐步编辑）。创建成功后选中新建项并失效列表缓存。
//
// Phase B：右栏头部多两个运行时按钮「生成」「清理」（§7.5），都依赖顶部选中的执行环境。
// 生成按 CASE 作用域跑含依赖链，cleanup_policy=AFTER_CASE 时后端自动执行 Cleanup；
// 结果都开进 ExecutionDetailDrawer 看每步 input/output/error。
import { useMemo, useState } from 'react';
import { App, Button, Col, Form, Input, Modal, Row, Select, Space, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import { ErrorState, LoadingState } from '@/components/PageState';
import { FIXTURE_SCOPE_OPTIONS, FIXTURE_STATUS_OPTIONS } from './constants';
import { FixtureTree } from './FixtureTree';
import { FixtureDetail } from './FixtureDetail';
import { ExecutionDetailDrawer } from './ExecutionDetailDrawer';
import type { DataExecutionDetail, FixtureBrief, FixtureCreate } from '@/types';

interface CreateValues {
  name: string;
  fixture_key: string;
  entity_type: string;
  scope?: string;
  status?: string;
  description?: string;
}

// fixture_key 规则与后端一致：^[A-Z][A-Z0-9_]{0,99}$
const FIXTURE_KEY_PATTERN = /^[A-Z][A-Z0-9_]{0,99}$/;

/**
 * Fixture 管理页。
 */
export function FixtureTab({
  projectId,
  environmentId,
  environmentName,
}: {
  projectId: number;
  environmentId: number | null;
  environmentName: string | null;
}) {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  // 运行时结果：作为详情抽屉的 seed，省一次回读。
  const [detail, setDetail] = useState<DataExecutionDetail | null>(null);
  const [form] = Form.useForm<CreateValues>();

  const listQuery = useQuery({
    queryKey: ['test-data', 'fixtures', projectId],
    queryFn: () => testDataApi.listFixtures(projectId, { page_size: 500 }),
    enabled: projectId != null,
  });

  const createMutation = useMutation({
    mutationFn: (body: FixtureCreate) => testDataApi.createFixture(projectId, body),
    onSuccess: (data) => {
      message.success('Fixture 已创建');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixtures'] });
      setCreateOpen(false);
      setSelectedId(data.id);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const briefs: FixtureBrief[] = useMemo(() => listQuery.data?.items ?? [], [listQuery.data?.items]);
  const selected: FixtureBrief | undefined = useMemo(
    () => briefs.find((b) => b.id === selectedId),
    [briefs, selectedId],
  );

  /** 生成 / 清理都要先选执行环境。 */
  const requireEnv = () => {
    if (environmentId == null) {
      message.warning('请先在顶部选择执行环境');
      return false;
    }
    return true;
  };

  /** 生成：手工试跑含依赖链，按 CASE 作用域，不写项目级缓存。 */
  const handleGenerate = () => {
    if (selectedId == null || !requireEnv()) return;
    const envLabel = environmentName ?? String(environmentId);
    modal.confirm({
      title: '生成确认',
      content: `将在环境「${envLabel}」下生成「${selected?.name ?? `#${selectedId}`}」（含依赖链），确认继续？`,
      okText: '生成',
      cancelText: '取消',
      onOk: async () => {
        try {
          const data = await testDataApi.generateFixture(selectedId, {
            environment_id: environmentId as number,
          });
          setDetail(data);
          message.success(
            data.status === 'FAILED' ? `生成结束，但执行失败（${data.error_code ?? 'UNKNOWN'}）` : '生成完成',
          );
          queryClient.invalidateQueries({ queryKey: ['test-data', 'executions'] });
        } catch (e) {
          message.error(getErrorMessage(e, '生成失败'));
        }
      },
    });
  };

  /** 清理：只执行该 Fixture 的 CLEANUP 步骤，不重新生成。 */
  const handleCleanup = () => {
    if (selectedId == null || !requireEnv()) return;
    const envLabel = environmentName ?? String(environmentId);
    modal.confirm({
      title: '清理确认',
      content: `将在环境「${envLabel}」下执行「${selected?.name ?? `#${selectedId}`}」的 CLEANUP 步骤，确认继续？`,
      okText: '清理',
      cancelText: '取消',
      onOk: async () => {
        try {
          const data = await testDataApi.cleanupFixture(selectedId);
          setDetail(data);
          message.success(data.status === 'FAILED' ? '清理已执行，部分步骤失败' : '清理完成');
          queryClient.invalidateQueries({ queryKey: ['test-data', 'executions'] });
        } catch (e) {
          message.error(getErrorMessage(e, '清理失败'));
        }
      },
    });
  };

  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError) return <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />;

  return (
    <>
      <Row gutter={16}>
        <Col flex="320px">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 8,
              height: 'calc(100vh - 280px)',
              minHeight: 400,
              overflow: 'auto',
            }}
          >
            <Space style={{ marginBottom: 8 }}>
              <Button
                type="primary"
                onClick={() => {
                  form.resetFields();
                  form.setFieldsValue({ scope: 'PROJECT', status: 'DRAFT' });
                  setCreateOpen(true);
                }}
              >
                新增 Fixture
              </Button>
            </Space>
            <FixtureTree
              briefs={briefs}
              selectedId={selectedId}
              onSelect={setSelectedId}
              keyword={keyword}
              setKeyword={setKeyword}
            />
          </div>
        </Col>
        <Col flex="auto">
          <div
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 16,
              height: 'calc(100vh - 280px)',
              minHeight: 400,
              overflow: 'auto',
            }}
          >
            {selectedId != null ? (
              <Space style={{ marginBottom: 12 }}>
                <Button type="primary" onClick={handleGenerate}>
                  生成
                </Button>
                <Button danger onClick={handleCleanup}>
                  清理
                </Button>
                <Typography.Text type="secondary">
                  {environmentId == null
                    ? '未选择执行环境'
                    : `执行环境：${environmentName ?? environmentId}`}
                </Typography.Text>
              </Space>
            ) : null}
            <FixtureDetail fixtureId={selectedId} />
          </div>
        </Col>
      </Row>

      <Modal
        title="新增 Fixture"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await form.validateFields();
          createMutation.mutate({
            name: values.name,
            fixture_key: values.fixture_key,
            entity_type: values.entity_type,
            description: values.description || null,
            scope: values.scope as FixtureCreate['scope'],
            status: values.status as FixtureCreate['status'],
          });
        }}
        confirmLoading={createMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={520}
      >
        <Form<CreateValues> form={form} layout="vertical" initialValues={{ scope: 'PROJECT', status: 'DRAFT' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={200} placeholder="如 创建测试用户" />
          </Form.Item>
          <Form.Item
            name="fixture_key"
            label="fixture_key"
            rules={[
              { required: true, message: '请输入 fixture_key' },
              {
                pattern: FIXTURE_KEY_PATTERN,
                message: '大写字母开头，仅含大写字母/数字/下划线，1-100 位',
              },
            ]}
            tooltip="项目内唯一，大写字母开头，仅含 A-Z 0-9 _，1-100 位"
          >
            <Input maxLength={100} placeholder="如 USER" style={{ textTransform: 'uppercase' }} />
          </Form.Item>
          <Form.Item
            name="entity_type"
            label="实体类型"
            rules={[{ required: true, message: '请输入实体类型' }]}
          >
            <Input maxLength={100} placeholder="如 user" />
          </Form.Item>
          <Form.Item name="scope" label="作用域">
            <Select options={FIXTURE_SCOPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={FIXTURE_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      <ExecutionDetailDrawer
        open={detail != null}
        executionId={detail?.id ?? null}
        seed={detail}
        onClose={() => setDetail(null)}
      />
    </>
  );
}
