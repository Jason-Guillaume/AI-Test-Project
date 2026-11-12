// Fixture 步骤列表（生成流程 / Cleanup 共用，按 phase 区分）。
//
// §7.3：每行 sort、step_type、名称、配置摘要、删除、上移、下移。新增用 Modal 选类型后填 config。
// 保存步骤时一次 PUT 整表（PUT /fixtures/{id}/steps）。后端重建步骤派生依赖边并跑环检测，
// 返回 FIXTURE_DEPENDENCY_CYCLE 时用 App.useApp().message.error 展示 message。
//
// 合并策略：PUT 替换的是该 Fixture 的「全部步骤」。当前 phase 的行由本表编辑，
// 另一 phase 的步骤从当前详情原样回传，避免编辑生成流程时误删清理步骤。
import { useEffect, useState } from 'react';
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from 'antd';
import { DownOutlined, UpOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/features/test-data/api/testData';
import { getErrorMessage } from '@/shared/api/client';
import {
  FIXTURE_ON_FAILURE_OPTIONS,
  FIXTURE_STEP_TYPE_OPTIONS,
  labelOf,
} from './constants';
import type { FixtureDetail, FixturePhase, FixtureStepInput, FixtureStepType, FixtureOnFailure } from '@/features/test-data/contracts';


interface Row {
  key: string;
  step_type: FixtureStepType;
  name: string;
  on_failure: FixtureOnFailure;
  provider_id: number | null;
  config_text: string;
}

let seq = 0;
const nextKey = () => `step_${Date.now()}_${seq++}`;

interface ModalValues {
  step_type: FixtureStepType;
  name: string;
  on_failure: FixtureOnFailure;
  provider_id?: string;
  config_text?: string;
}

/** 把后端步骤转成本地可编辑行。 */
function stepToRow(s: FixtureDetail['steps'][number]): Row {
  return {
    key: nextKey(),
    step_type: s.step_type,
    name: s.name,
    on_failure: s.on_failure,
    provider_id: s.provider_id,
    config_text: s.config_json ? JSON.stringify(s.config_json, null, 2) : '',
  };
}

/** 把本地行转成提交入参；config_text 为空则 null，非空需是合法 JSON。解析失败抛错。 */
function rowToInput(r: Row, sort: number, phase: FixturePhase): FixtureStepInput {
  let configJson: Record<string, unknown> | null = null;
  const text = (r.config_text ?? '').trim();
  if (text) {
    configJson = JSON.parse(text) as Record<string, unknown>;
  }
  return {
    phase,
    step_type: r.step_type,
    name: r.name.trim(),
    sort,
    provider_id: r.provider_id ?? null,
    config_json: configJson,
    on_failure: r.on_failure,
  };
}

/**
 * 步骤列表。phase=GENERATE 为生成流程，phase=CLEANUP 由 FixtureCleanupList 复用。
 */
export function FixtureStepList({
  fixture,
  phase,
}: {
  fixture: FixtureDetail;
  phase: FixturePhase;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<Row[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<ModalValues>();

  // 仅在当前 phase 的步骤集合变化时重置本地行，避免编辑中被覆盖。
  useEffect(() => {
    setRows((fixture.steps ?? []).filter((s) => s.phase === phase).map(stepToRow));
  }, [fixture.steps, phase]);

  const swap = (i: number, j: number) => {
    setRows((rs) => {
      if (j < 0 || j >= rs.length) return rs;
      const next = [...rs];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const mutation = useMutation({
    mutationFn: (steps: FixtureStepInput[]) =>
      testDataApi.replaceSteps(fixture.id, { steps }),
    onSuccess: () => {
      message.success('步骤已保存');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixture', fixture.id] });
      queryClient.invalidateQueries({ queryKey: ['test-data', 'fixtures'] });
    },
    // 造数/步骤保存失败（含 FIXTURE_DEPENDENCY_CYCLE）展示后端 message。
    onError: (e) => message.error(getErrorMessage(e, '保存失败')),
  });

  const handleSave = () => {
    // 名称必填、不重复；config_text 非空需合法 JSON。
    const names = rows.map((r) => r.name.trim());
    if (names.some((n) => !n)) {
      message.error('每行步骤名称不能为空');
      return;
    }
    if (new Set(names).size !== names.length) {
      message.error('步骤名称不能重复');
      return;
    }
    let parsed: Row[] = [];
    try {
      parsed = rows.map((r) => {
        const text = (r.config_text ?? '').trim();
        if (text) JSON.parse(text); // 仅校验合法性
        return r;
      });
    } catch (err) {
      message.error('存在非法 JSON 配置：' + (err as Error).message);
      return;
    }
    // 当前 phase 行：重排 sort；另一 phase 步骤原样回传。
    const thisPhaseInputs = parsed.map((r, i) => rowToInput(r, i + 1, phase));
    const otherPhaseInputs: FixtureStepInput[] = (fixture.steps ?? [])
      .filter((s) => s.phase !== phase)
      .map((s) => ({
        phase: s.phase,
        step_type: s.step_type,
        name: s.name,
        sort: s.sort,
        provider_id: s.provider_id,
        config_json: s.config_json,
        on_failure: s.on_failure,
      }));
    mutation.mutate([...thisPhaseInputs, ...otherPhaseInputs]);
  };

  const handleAdd = async () => {
    const values = await form.validateFields();
    const configText = (values.config_text ?? '').trim();
    if (configText) {
      try {
        JSON.parse(configText);
      } catch (err) {
        message.error('config 不是合法 JSON：' + (err as Error).message);
        return;
      }
    }
    setRows((rs) => [
      ...rs,
      {
        key: nextKey(),
        step_type: values.step_type,
        name: values.name.trim(),
        on_failure: values.on_failure,
        provider_id: values.provider_id ? Number(values.provider_id) : null,
        config_text: configText,
      },
    ]);
    setModalOpen(false);
    form.resetFields();
  };

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button
          onClick={() => {
            form.resetFields();
            form.setFieldsValue({ on_failure: 'ABORT' });
            setModalOpen(true);
          }}
        >
          新增步骤
        </Button>
        <Button type="primary" loading={mutation.isPending} onClick={handleSave}>
          保存
        </Button>
      </Space>
      <Table<Row>
        rowKey="key"
        dataSource={rows}
        pagination={false}
        size="middle"
        columns={[
          { title: '#', width: 50, render: (_: unknown, __: Row, i: number) => i + 1 },
          {
            title: '类型',
            dataIndex: 'step_type',
            width: 130,
            render: (v: FixtureStepType) => <Tag>{labelOf(FIXTURE_STEP_TYPE_OPTIONS, v)}</Tag>,
          },
          { title: '名称', dataIndex: 'name' },
          {
            title: '失败策略',
            dataIndex: 'on_failure',
            width: 100,
            render: (v: FixtureOnFailure) => labelOf(FIXTURE_ON_FAILURE_OPTIONS, v),
          },
          {
            title: 'Provider',
            dataIndex: 'provider_id',
            width: 90,
            render: (v: number | null) => (v == null ? '-' : `#${v}`),
          },
          {
            title: '配置摘要',
            dataIndex: 'config_text',
            ellipsis: true,
            render: (v: string) => (v ? v.slice(0, 60) : '-'),
          },
          {
            title: '操作',
            width: 140,
            render: (_: unknown, r: Row, i: number) => (
              <Space size={2}>
                <a onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}>删除</a>
                <a onClick={() => swap(i, i - 1)} style={{ opacity: i === 0 ? 0.3 : 1 }}>
                  <UpOutlined />
                </a>
                <a
                  onClick={() => swap(i, i + 1)}
                  style={{ opacity: i === rows.length - 1 ? 0.3 : 1 }}
                >
                  <DownOutlined />
                </a>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        title="新增步骤"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleAdd}
        okText="添加"
        cancelText="取消"
        destroyOnClose
        width={560}
      >
        <Form<ModalValues> form={form} layout="vertical" initialValues={{ on_failure: 'ABORT' }}>
          <Form.Item
            name="step_type"
            label="步骤类型"
            rules={[{ required: true, message: '请选择步骤类型' }]}
          >
            <Select options={FIXTURE_STEP_TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入名称' }]}
          >
            <Input maxLength={200} />
          </Form.Item>
          <Form.Item name="on_failure" label="失败策略">
            <Select options={FIXTURE_ON_FAILURE_OPTIONS} />
          </Form.Item>
          <Form.Item name="provider_id" label="Provider ID（可选）">
            <Input placeholder="关联的 DataProvider id" />
          </Form.Item>
          <Form.Item
            name="config_text"
            label="config（JSON）"
            tooltip={'按步骤类型解释，如 FAKER: {"generator":"name"}；FIXTURE: {"fixture_key":"USER"}'}
          >
            <Input.TextArea rows={5} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
