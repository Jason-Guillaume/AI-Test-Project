// Data Provider 新增/编辑弹窗：按 provider_type 切换子表单。
//
// §7.4：ProviderModal 用 provider_type 切换子表单。公共字段：name、provider_type、
// risk_level、enabled、description；config_json 由对应子表单维护。
// ENVIRONMENT 无独立配置文件，在此内联（环境键名选择）。
//
// 编辑态：config_json 从 editing 回填；切换 provider_type 会清空 config（避免旧类型残留键）。
import { useEffect, useState } from 'react';
import { App, Form, Input, Modal, Select, Switch } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { testDataApi } from '@/api/testData';
import { getErrorMessage } from '@/api/client';
import { PROVIDER_TYPE_OPTIONS, RISK_LEVEL_OPTIONS } from './constants';
import { ProviderConfigApi } from './ProviderConfigApi';
import { ProviderConfigBusiness } from './ProviderConfigBusiness';
import { ProviderConfigDatabase } from './ProviderConfigDatabase';
import { ProviderConfigFaker } from './ProviderConfigFaker';
import { ProviderConfigPool } from './ProviderConfigPool';
import { ProviderConfigStatic } from './ProviderConfigStatic';
import type { DataProvider, DataProviderCreate, DataProviderUpdate, ProviderType } from '@/types';

const ENV_KEY_OPTIONS = ['base_url', 'gateway_prefix', 'default_headers'].map((k) => ({
  label: k,
  value: k,
}));

/**
 * Provider 新增/编辑弹窗。editing 为 null 表示新增。
 */
export function ProviderModal({
  open,
  onClose,
  projectId,
  editing,
}: {
  open: boolean;
  onClose: () => void;
  projectId: number;
  editing: DataProvider | null;
}) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [providerType, setProviderType] = useState<ProviderType | null>(null);
  const [riskLevel, setRiskLevel] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [config, setConfig] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setName(editing.name);
      setProviderType(editing.provider_type);
      setRiskLevel(editing.risk_level);
      setDescription(editing.description ?? '');
      setEnabled(editing.enabled);
      setConfig({ ...(editing.config_json ?? {}) });
    } else {
      setName('');
      setProviderType(null);
      setRiskLevel(null);
      setDescription('');
      setEnabled(true);
      setConfig({});
    }
  }, [open, editing]);

  const createMutation = useMutation({
    mutationFn: (body: DataProviderCreate) => testDataApi.createProvider(projectId, body),
    onSuccess: () => {
      message.success('Provider 已创建');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'providers'] });
      onClose();
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  const updateMutation = useMutation({
    mutationFn: (body: DataProviderUpdate) => testDataApi.updateProvider(editing!.id, body),
    onSuccess: () => {
      message.success('Provider 已更新');
      queryClient.invalidateQueries({ queryKey: ['test-data', 'providers'] });
      onClose();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  const handleOk = () => {
    if (!name.trim()) {
      message.error('请输入名称');
      return;
    }
    if (!providerType) {
      message.error('请选择类型');
      return;
    }
    const common = {
      name: name.trim(),
      provider_type: providerType,
      config_json: config,
      enabled,
      risk_level: (riskLevel ?? null) as DataProviderCreate['risk_level'],
      description: description || null,
    };
    if (editing) {
      updateMutation.mutate(common);
    } else {
      createMutation.mutate(common);
    }
  };

  const renderConfig = () => {
    if (!providerType) return null;
    const props = { value: config, onChange: setConfig, projectId };
    switch (providerType) {
      case 'STATIC':
        return <ProviderConfigStatic {...props} />;
      case 'FAKER':
        return <ProviderConfigFaker {...props} />;
      case 'API_CREATE':
        return <ProviderConfigApi {...props} />;
      case 'BUSINESS_ACTION':
        return <ProviderConfigBusiness {...props} mode="action" />;
      case 'BUSINESS_FLOW':
        return <ProviderConfigBusiness {...props} mode="flow" />;
      case 'EXISTING_POOL':
        return <ProviderConfigPool {...props} />;
      case 'DATABASE_INSERT':
      case 'DATABASE_PATCH':
        return <ProviderConfigDatabase {...props} />;
      case 'ENVIRONMENT':
        return (
          <Form.Item label="环境键名" required tooltip="取项目环境的 base_url / gateway_prefix / default_headers">
            <Select
              value={(config.env_key as string) ?? undefined}
              onChange={(v) => setConfig({ env_key: v })}
              options={ENV_KEY_OPTIONS}
              placeholder="选择环境键名"
            />
          </Form.Item>
        );
      default:
        return null;
    }
  };

  const pending = createMutation.isPending || updateMutation.isPending;

  return (
    <Modal
      title={editing ? '编辑 Data Provider' : '新增 Data Provider'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={pending}
      okText="保存"
      cancelText="取消"
      destroyOnClose
      width={640}
    >
      <Form layout="vertical">
        <Form.Item label="名称" required>
          <Input
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 创建用户"
          />
        </Form.Item>
        <Form.Item label="类型" required>
          <Select
            value={providerType ?? undefined}
            onChange={(v: ProviderType) => {
              setProviderType(v);
              setConfig({}); // 切换类型清空配置，避免旧键残留被 extra=forbid 拒绝
            }}
            options={PROVIDER_TYPE_OPTIONS}
            placeholder="选择类型"
            disabled={!!editing}
          />
        </Form.Item>
        <Form.Item label="风险等级" tooltip="DATABASE 类由后端强制提升；此处可留空交后端推断">
          <Select
            allowClear
            value={(riskLevel as string) ?? undefined}
            onChange={(v) => setRiskLevel((v as string) ?? null)}
            options={RISK_LEVEL_OPTIONS}
            placeholder="留空由后端按类型推断"
          />
        </Form.Item>
        <Form.Item label="启用" valuePropName="checked">
          <Switch checked={enabled} onChange={setEnabled} />
        </Form.Item>
        <Form.Item label="描述">
          <Input.TextArea rows={2} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Form.Item>
        <div style={{ borderTop: '1px solid #f0f0f0', margin: '8px 0 16px', paddingTop: 16 }}>
          <strong>类型配置</strong>
          {renderConfig()}
        </div>
      </Form>
    </Modal>
  );
}
