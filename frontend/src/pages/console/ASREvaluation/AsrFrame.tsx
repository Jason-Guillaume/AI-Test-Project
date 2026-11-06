// ASR 工作区外壳：保留平台导航和项目范围，在域内提供音频、任务与实验入口。
import { Alert, Button, Card, Flex, Typography } from 'antd';
import { AudioOutlined, ExperimentOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { Link, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import './asr-evaluation.css';

const { Title, Text } = Typography;

const ASR_TABS = [
  { path: '/console/asr/audio', label: '音频列表', icon: <AudioOutlined /> },
  { path: '/console/asr/jobs', label: '评测任务', icon: <UnorderedListOutlined /> },
  { path: '/console/asr/comparisons', label: '识别对比', icon: <UnorderedListOutlined /> },
  { path: '/console/asr/experiments', label: '参数实验', icon: <ExperimentOutlined /> },
  { path: '/console/asr/funasr', label: 'AI 分析与调优', icon: <ExperimentOutlined /> },
];

/** ASR 页面导航与项目提示；内容区由各个域内页面提供。 */
export function AsrFrame({ title, children, projectId }: { title: string; children: ReactNode; projectId?: number }) {
  const location = useLocation();
  const { currentProjectId } = useConsoleScope();
  const displayedProject = projectId ?? currentProjectId;
  return (
    <div className="asr-page">
      <Flex className="asr-page-heading" justify="space-between" align="center" wrap="wrap" gap="middle">
        <div>
          <Text className="asr-eyebrow">语音识别评测</Text>
          <Title level={2}>{title}</Title>
        </div>
        <Text type="secondary">
          {displayedProject ? '项目 ' + displayedProject : '请先在顶部选择项目'}
        </Text>
      </Flex>
      <Flex className="asr-tabs" gap="small" wrap="wrap">
        {ASR_TABS.map((tab) => {
          const active = location.pathname.startsWith(tab.path);
          return (
            <Link key={tab.path} to={tab.path}>
              <Button type={active ? 'primary' : 'default'} icon={tab.icon}>
                {tab.label}
              </Button>
            </Link>
          );
        })}
      </Flex>
      {!displayedProject && (
        <Alert
          className="asr-scope-alert"
          type="info"
          showIcon
          message="先选择项目"
          description="音频、任务和复核记录按当前项目隔离；模型资源由平台管理员在管理后台维护。"
        />
      )}
      <Card className="asr-content-card" bordered={false}>
        {children}
      </Card>
    </div>
  );
}
