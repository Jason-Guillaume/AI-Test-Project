// 业务管理页（用户视角）。
// 左右布局：左侧业务域/流程树，右侧流程详情（步骤编排 + 变量引用 + 规则）。
// 点击流程步骤打开 ActionDrawer，配置前置条件 / 输入输出变量 / 业务状态 / API 绑定。
//
// 权限（服务端为准，前端隐藏只是辅助）：读 = 项目可见（viewer+）；写 = 项目成员（member+）；
// 跨项目越权按 404 返回，前端不展示。
//
// 第一阶段仅支持 API 通道绑定；Web/Mobile 通道已预留字段与下拉，标记「预留·未接入」。
import { useState } from 'react';
import { App, Button, Col, Form, Input, Modal, Row, Select, Space } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { businessApi } from '@/features/business/api/business';
import { getErrorMessage } from '@/shared/api/client';
import { EmptyState, PageContainer } from '@/shared/ui/PageState';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { DOMAIN_STATUS_OPTIONS, FLOW_STATUS_OPTIONS } from './constants';
import { DomainTree } from './DomainTree';
import { FlowDetail } from './FlowDetail';
import type { BusinessDomainCreate, BusinessDomainStatus, BusinessFlowCreate, BusinessFlowStatus } from '@/features/business/contracts';


interface DomainFormValues {
  name: string;
  description?: string;
  status: BusinessDomainStatus;
}
interface FlowFormValues {
  name: string;
  description?: string;
  status: BusinessFlowStatus;
}

/**
 * 业务管理页。
 *
 * 依赖当前项目作用域：未选项目时整页空态。切换项目由 useConsoleScope 失效 ['business']。
 * 左侧树选中域与流程后，右侧渲染 FlowDetail（聚合详情一次性拉取，4 Tab 共享同一份数据）。
 */
export function ConsoleBusinessManagementPage() {
  const { currentProjectId } = useConsoleScope();
  return <BusinessWorkspace key={currentProjectId ?? 'none'} />;
}

function BusinessWorkspace() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { currentProjectId } = useConsoleScope();

  const [selectedDomainId, setSelectedDomainId] = useState<number | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<number | null>(null);
  const [domainOpen, setDomainOpen] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const [domainForm] = Form.useForm<DomainFormValues>();
  const [flowForm] = Form.useForm<FlowFormValues>();

  const createDomainMutation = useMutation({
    mutationFn: (body: BusinessDomainCreate) =>
      businessApi.createDomain(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('业务域已创建');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setDomainOpen(false);
      domainForm.resetFields();
      setSelectedDomainId(data.id);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const createFlowMutation = useMutation({
    mutationFn: (body: BusinessFlowCreate) =>
      businessApi.createFlow(currentProjectId!, body),
    onSuccess: (data) => {
      message.success('业务流程已创建');
      queryClient.invalidateQueries({ queryKey: ['business'] });
      setFlowOpen(false);
      flowForm.resetFields();
      setSelectedFlowId(data.id);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  if (currentProjectId == null) {
    return (
      <PageContainer>
        <EmptyState description="请先在顶部选择一个项目" />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <Row gutter={16} className="resource-split">
        <Col className="resource-split__sidebar">
          <div
            className="resource-split__panel"
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 8,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <Space
              style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}
              wrap
            >
              <span style={{ fontWeight: 600 }}>业务域 / 流程</span>
              <Space size={4}>
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    domainForm.resetFields();
                    setDomainOpen(true);
                  }}
                >
                  新建域
                </Button>
                <Button
                  size="small"
                  type="primary"
                  disabled={selectedDomainId == null}
                  onClick={() => {
                    flowForm.resetFields();
                    setFlowOpen(true);
                  }}
                >
                  新建流程
                </Button>
              </Space>
            </Space>
            <div style={{ flex: 1, overflow: 'auto' }}>
              <DomainTree
                projectId={currentProjectId}
                selectedDomainId={selectedDomainId}
                onSelectDomain={setSelectedDomainId}
                selectedFlowId={selectedFlowId}
                onSelectFlow={setSelectedFlowId}
              />
            </div>
          </div>
        </Col>
        <Col className="resource-split__detail">
          <div
            className="resource-split__panel"
            style={{
              border: '1px solid #f0f0f0',
              borderRadius: 8,
              padding: 16,
              overflow: 'auto',
            }}
          >
            {selectedFlowId == null ? (
              <EmptyState description="请在左侧选择一个业务流程，或新建一个流程" />
            ) : (
              <FlowDetail flowId={selectedFlowId} projectId={currentProjectId} />
            )}
          </div>
        </Col>
      </Row>

      {/* 新建业务域弹窗 */}
      <Modal
        title="新建业务域"
        open={domainOpen}
        onCancel={() => setDomainOpen(false)}
        onOk={async () => {
          const values = await domainForm.validateFields();
          await createDomainMutation.mutateAsync({
            name: values.name,
            description: values.description || null,
            status: values.status || 'ACTIVE',
            sort: 0,
          });
        }}
        confirmLoading={createDomainMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<DomainFormValues>
          form={domainForm}
          layout="vertical"
          initialValues={{ status: 'ACTIVE' }}
        >
          <Form.Item
            name="name"
            label="业务域名称"
            rules={[{ required: true, message: '请输入业务域名称' }]}
          >
            <Input maxLength={100} placeholder="如 AI选址" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={DOMAIN_STATUS_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建业务流程弹窗 */}
      <Modal
        title="新建业务流程"
        open={flowOpen}
        onCancel={() => setFlowOpen(false)}
        onOk={async () => {
          const values = await flowForm.validateFields();
          if (selectedDomainId == null) return;
          await createFlowMutation.mutateAsync({
            name: values.name,
            description: values.description || null,
            status: values.status || 'DRAFT',
            domain_id: selectedDomainId,
          });
        }}
        confirmLoading={createFlowMutation.isPending}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<FlowFormValues>
          form={flowForm}
          layout="vertical"
          initialValues={{ status: 'DRAFT' }}
        >
          <Form.Item
            name="name"
            label="流程名称"
            rules={[{ required: true, message: '请输入流程名称' }]}
          >
            <Input maxLength={200} placeholder="如 AI选址任务流程" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={FLOW_STATUS_OPTIONS} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
