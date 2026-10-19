// Web 附件查看器：认证下载截图和本地动作 Trace，离开组件时释放 Blob URL。
import { useEffect, useState } from 'react';
import { App, Button, Empty, Image, Modal, Space, Table, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { webUIApi } from '@/api/webUI';
import { getErrorMessage } from '@/api/client';
import type { WebArtifact } from '@/types';

/** 展示历史或报告中的截图、Trace 与步骤日志；原始凭据不会进入此组件。 */
export function WebArtifacts({ snapshot }: { snapshot: unknown }) {
  const web = (snapshot as { web?: { artifacts?: WebArtifact[]; steps?: Record<string, unknown>[] } } | null)?.web;
  const { message } = App.useApp();
  const [selected, setSelected] = useState<WebArtifact | null>(null);
  const [imageUrl, setImageUrl] = useState<string>();
  const trace = useQuery({ queryKey: ['web-trace', selected?.id], queryFn: () => webUIApi.trace(selected!.id), enabled: selected?.kind === 'TRACE' });
  useEffect(() => {
    let active = true;
    let url: string | undefined;
    setImageUrl(undefined);
    if (selected && selected.kind !== 'TRACE') {
      webUIApi.artifact(selected.id).then(blob => {
        url = URL.createObjectURL(blob);
        if (active) setImageUrl(url); else URL.revokeObjectURL(url);
      }).catch(error => { if (active) void message.error(getErrorMessage(error)); });
    }
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [selected, message]);
  /** 保持附件在本机，下载后及时释放内存 URL。 */
  async function download(artifact: WebArtifact) {
    try {
      const blob = await webUIApi.artifact(artifact.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `${artifact.id}.${artifact.kind === 'TRACE' ? 'zip' : 'png'}`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { void message.error(getErrorMessage(error)); }
  }
  if (!web) return <Empty description="此执行没有 Web 附件" />;
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Space wrap>{web.artifacts?.map(a => <Space key={a.id}>
      <Button onClick={() => setSelected(a)}>{a.kind === 'TRACE' ? '查看 Trace' : a.kind === 'FAILURE_SCREENSHOT' ? '失败截图' : '执行截图'}</Button>
      <Button type="link" onClick={() => void download(a)}>下载</Button>
    </Space>)}</Space>
    <Table size="small" rowKey={(_, i) => String(i)} dataSource={web.steps ?? []} pagination={false}
      columns={[{ title: '步骤', dataIndex: 'step' }, { title: '名称', dataIndex: 'name' },
        { title: '操作', dataIndex: 'operation' }, { title: '状态', dataIndex: 'status' },
        { title: '耗时(ms)', dataIndex: 'duration_ms' }, { title: '事件', dataIndex: 'event' }]} />
    <Modal title={selected?.kind === 'TRACE' ? 'Trace 动作时序（已移除 DOM、网络正文与敏感值）' : '执行截图'} open={!!selected}
      onCancel={() => setSelected(null)} footer={null} width={1000} destroyOnClose>
      {selected?.kind === 'TRACE' ? <>
        {trace.isError && <Typography.Text type="danger">{getErrorMessage(trace.error)}</Typography.Text>}
        <Table rowKey={(_, i) => String(i)} loading={trace.isPending} size="small" scroll={{ x: 800 }}
          dataSource={trace.data?.events ?? []} pagination={{ pageSize: 20 }}
          columns={[{ title: '事件', dataIndex: 'type', width: 130 }, { title: '方法', dataIndex: 'method', width: 160 },
            { title: '详情', render: (_, row) => <Typography.Text code style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(row)}</Typography.Text> }]} />
      </> : imageUrl ? <Image src={imageUrl} alt="已遮蔽输入信息的浏览器截图" /> : <Typography.Text>正在加载截图…</Typography.Text>}
    </Modal>
  </Space>;
}
