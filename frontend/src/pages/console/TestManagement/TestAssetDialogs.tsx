// 测试资产创建与基础信息编辑弹窗。
import { Form, Input, Modal, Select, Switch } from 'antd';
import { TEST_CASE_TYPE_OPTIONS, TEST_PRIORITY_OPTIONS, TEST_STATUS_OPTIONS, TEST_STRATEGY_CATEGORY_OPTIONS, TEST_TARGET_TYPE_OPTIONS } from './constants';

// 测试资产创建与基础信息编辑弹窗。
import type { FormInstance } from 'antd/es/form';
// ---- 表单值类型 ----
export interface StrategyFormValues {
  name: string;
  category: 'FUNCTIONAL' | 'PARAMETER' | 'BOUNDARY' | 'AUTH' | 'PERMISSION' | 'BUSINESS' | 'EXCEPTION' | 'IDEMPOTENCY' | 'SECURITY' | 'DATA_CONSISTENCY';
  enabled: boolean;
  description?: string;
}
export interface PointFormValues {
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  target_type: 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  description?: string;
}
export interface CaseFormValues {
  name: string;
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  case_type: 'FUNCTIONAL' | 'BUSINESS' | 'NEGATIVE' | 'BOUNDARY' | 'PERMISSION' | 'SECURITY' | 'EXCEPTION';
  target_type: 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION';
  status: 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
  enabled: boolean;
  description?: string;
}

interface TestAssetDialogsProps {
 strategyOpen:boolean; setStrategyOpen:(open:boolean)=>void; pointOpen:boolean; setPointOpen:(open:boolean)=>void;
 caseOpen:boolean; setCaseOpen:(open:boolean)=>void; caseEditOpen:boolean; setCaseEditOpen:(open:boolean)=>void;
 strategyForm:FormInstance<StrategyFormValues>; pointForm:FormInstance<PointFormValues>; caseForm:FormInstance<CaseFormValues>; caseEditForm:FormInstance<CaseFormValues>;
 creatingStrategy:boolean; creatingPoint:boolean; creatingCase:boolean; updatingCase:boolean;
 onCreateStrategy:()=>Promise<void>; onCreatePoint:()=>Promise<void>; onCreateCase:()=>Promise<void>; onUpdateCase:()=>Promise<void>;
}

export function TestAssetDialogs({ strategyOpen,setStrategyOpen,pointOpen,setPointOpen,caseOpen,setCaseOpen,caseEditOpen,setCaseEditOpen,strategyForm,pointForm,caseForm,caseEditForm,creatingStrategy,creatingPoint,creatingCase,updatingCase,onCreateStrategy,onCreatePoint,onCreateCase,onUpdateCase }:TestAssetDialogsProps) {
 return (
 <>
      {/* 新建策略 */}
      <Modal
        title="新建测试策略"
        open={strategyOpen}
        onCancel={() => setStrategyOpen(false)}
        onOk={onCreateStrategy}
        confirmLoading={creatingStrategy}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<StrategyFormValues> form={strategyForm} layout="vertical" initialValues={{ category: 'FUNCTIONAL', enabled: true }}>
          <Form.Item name="name" label="策略名称" rules={[{ required: true, message: '请输入策略名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="category" label="类别">
            <Select options={TEST_STRATEGY_CATEGORY_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建测试点 */}
      <Modal
        title="新建测试点"
        open={pointOpen}
        onCancel={() => setPointOpen(false)}
        onOk={onCreatePoint}
        confirmLoading={creatingPoint}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<PointFormValues> form={pointForm} layout="vertical" initialValues={{ priority: 'P1', target_type: 'API', status: 'DRAFT' }}>
          <Form.Item name="name" label="测试点名称" rules={[{ required: true, message: '请输入测试点名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新建用例 */}
      <Modal
        title="新建测试用例"
        open={caseOpen}
        onCancel={() => setCaseOpen(false)}
        onOk={onCreateCase}
        confirmLoading={creatingCase}
        okText="创建"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<CaseFormValues> form={caseForm} layout="vertical" initialValues={{ priority: 'P1', case_type: 'FUNCTIONAL', target_type: 'API', status: 'DRAFT', enabled: true }}>
          <Form.Item name="name" label="用例名称" rules={[{ required: true, message: '请输入用例名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="case_type" label="用例类型">
            <Select options={TEST_CASE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑用例基本信息（乐观锁）*/}
      <Modal
        title="编辑测试用例"
        open={caseEditOpen}
        onCancel={() => setCaseEditOpen(false)}
        onOk={onUpdateCase}
        confirmLoading={updatingCase}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={480}
      >
        <Form<CaseFormValues> form={caseEditForm} layout="vertical">
          <Form.Item name="name" label="用例名称" rules={[{ required: true, message: '请输入用例名称' }]}>
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={TEST_PRIORITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="case_type" label="用例类型">
            <Select options={TEST_CASE_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="target_type" label="被测对象类型">
            <Select options={TEST_TARGET_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select options={TEST_STATUS_OPTIONS} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
 </>
 );
}
