// 测试结果与疑似问题的缺陷关联；只提交人工填写的信息，不复制证据。
import { useState } from 'react';
import { Alert, App, Button, Form, Input, Modal, Select, Space, Typography } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { bugsApi, type DefectSourceType } from '@/api/defects';
import { getErrorMessage } from '@/api/client';

/** 展示来源关联并允许用户明确创建或选择同项目缺陷。 */
export function DefectSourceLinks({ sourceType, sourceId }: { sourceType: DefectSourceType; sourceId: number }) {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [requestKey, setRequestKey] = useState('');
  const [form] = Form.useForm<{ mode: 'create' | 'link'; title?: string; description?: string; bug_id?: number }>();
  const mode = Form.useWatch('mode', form) ?? 'create';
  const context = useQuery({ queryKey: ['defect-source-context', sourceType, sourceId], queryFn: () => bugsApi.sourceContext(sourceType, sourceId) });
  const links = useQuery({ queryKey: ['defect-source-links', sourceType, sourceId], queryFn: () => bugsApi.sources(sourceType, sourceId) });
  const bugs = useQuery({ queryKey: ['defect-source-options', context.data?.project_id], queryFn: () => bugsApi.list({ project_id: context.data!.project_id, page: 1, page_size: 100 }), enabled: open && mode === 'link' && !!context.data });
  const mutation = useMutation({
    mutationFn: (values: { mode: 'create' | 'link'; title?: string; description?: string; bug_id?: number }) => bugsApi.linkSource({
      source_type: sourceType, source_id: sourceId, request_key: requestKey,
      ...(values.mode === 'link' ? { bug_id: values.bug_id } : { bug: { project_id: context.data!.project_id, title: values.title!, description: values.description } }),
    }),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['defect-source-links', sourceType, sourceId] }), queryClient.invalidateQueries({ queryKey: ['bugs'] })]);
      setOpen(false);
      message.success('缺陷关联已保存');
    },
    onError: error => message.error(getErrorMessage(error, '缺陷关联失败')),
  });
  if (context.isLoading || links.isLoading) return null;
  if (context.isError || links.isError) return <Alert type="warning" showIcon message="缺陷来源暂不可用或无权查看" />;
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Space wrap><Typography.Text strong>关联缺陷</Typography.Text>
      {(links.data ?? []).map(link => <Link key={link.id} to={`/console/defects?bugId=${link.bug_id}`}>缺陷 #{link.bug_id}</Link>)}
      {(links.data?.length ?? 0) === 0 && <Typography.Text type="secondary">暂无</Typography.Text>}
      <Button size="small" onClick={() => { form.resetFields(); setRequestKey(crypto.randomUUID()); setOpen(true); }}>创建或关联缺陷</Button>
    </Space>
    <Modal title="确认缺陷关联" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={mutation.isPending} destroyOnClose>
      <Alert type="info" showIcon message={sourceType === 'SECURITY_FINDING' ? '来源为安全疑似问题，关联缺陷不会自动确认漏洞。' : '来源为失败的用例执行。'} description="不会自动复制请求、凭据或证据；请人工填写可安全展示的信息。" />
      <Form form={form} layout="vertical" initialValues={{ mode: 'create' }} onFinish={values => mutation.mutate(values)}>
        <Form.Item name="mode" label="操作"><Select options={[{ value: 'create', label: '新建缺陷' }, { value: 'link', label: '关联已有缺陷' }]} /></Form.Item>
        {mode === 'create' ? <>
          <Form.Item name="title" label="缺陷标题" rules={[{ required: true, whitespace: true, max: 200 }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={1000} /></Form.Item>
        </> : <Form.Item name="bug_id" label="同项目缺陷" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" loading={bugs.isLoading} options={(bugs.data?.items ?? []).map(bug => ({ value: bug.id, label: `#${bug.id} ${bug.title}` }))} /></Form.Item>}
      </Form>
    </Modal>
  </Space>;
}
