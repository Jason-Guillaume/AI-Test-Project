import { useEffect, useState } from 'react';
import { App, Form, Modal, Space, Switch, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { securityApi } from '@/features/security-testing/api/securityTesting';
import { getErrorMessage } from '@/shared/api/client';
import { LoadingState } from '@/shared/ui/PageState';

/** 环境开关弹窗：allow_production 恒禁用。用本地 state 承载开关，不污染缓存对象。 */
export function SettingModal({ projectId, onCancel }: { projectId: number; onCancel: () => void }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const settingQuery = useQuery({
    queryKey: ['security-setting', projectId],
    queryFn: () => securityApi.getSetting(projectId),
  });
  const [dev, setDev] = useState(false);
  const [test, setTest] = useState(false);
  const [staging, setStaging] = useState(false);
  const [revision, setRevision] = useState<number>(1);

  // 拿到后端初值后写一次本地 state（避免直接 mutate 缓存对象）。
  useEffect(() => {
    const s = settingQuery.data;
    if (!s) return;
    setDev(s.allow_dev);
    setTest(s.allow_test);
    setStaging(s.allow_staging);
    setRevision(s.revision);
  }, [settingQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (body: Parameters<typeof securityApi.updateSetting>[1]) =>
      securityApi.updateSetting(projectId, body),
    onSuccess: () => {
      message.success('环境开关已更新');
      queryClient.invalidateQueries({ queryKey: ['security-setting', projectId] });
      onCancel();
    },
    onError: (e) => message.error(getErrorMessage(e, '更新失败')),
  });

  return (
    <Modal
      title="安全测试环境开关"
      open
      onCancel={onCancel}
      confirmLoading={updateMutation.isPending}
      okText="保存"
      cancelText="取消"
      onOk={() =>
        updateMutation.mutate({
          allow_dev: dev,
          allow_test: test,
          allow_staging: staging,
          // allow_production 故意不提交：前端恒禁用，生产永远拒绝（后端 gate 强制）。
          revision,
        })
      }
    >
      {settingQuery.isLoading ? (
        <LoadingState />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text>
            仅勾选的环境允许发起安全变异请求。生产环境恒为关闭，不可开启。
          </Typography.Text>
          <Form layout="vertical">
            <Form.Item label="开发环境（DEV）">
              <Switch checked={dev} onChange={setDev} />
            </Form.Item>
            <Form.Item label="测试环境（TEST）">
              <Switch checked={test} onChange={setTest} />
            </Form.Item>
            <Form.Item label="预发环境（STAGING）">
              <Switch checked={staging} onChange={setStaging} />
            </Form.Item>
            <Form.Item label="生产环境（PRODUCTION）">
              <Switch checked={false} disabled />
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                恒不生效（安全红线）
              </Typography.Text>
            </Form.Item>
          </Form>
        </Space>
      )}
    </Modal>
  );
}
