// ASR 工作区外壳：保留平台导航和项目范围，在域内提供音频、任务与实验入口。
import { Alert, Flex, Tabs, Typography, theme } from 'antd';
import { AudioOutlined, ExperimentOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import type { CSSProperties, ReactNode } from 'react';
import { useConsoleScope } from '@/app/providers/ConsoleScopeProvider';
import { PageContainer } from '@/shared/ui/PageState';
import './asr-evaluation.css';

const { Text } = Typography;

const ASR_TABS = [
  { path: '/console/asr/audio', label: '音频资产', icon: <AudioOutlined /> },
  { path: '/console/asr/jobs', label: '评测任务', icon: <UnorderedListOutlined /> },
  { path: '/console/asr/comparisons', label: '结果对比', icon: <UnorderedListOutlined /> },
  { path: '/console/asr/experiments', label: '参数实验', icon: <ExperimentOutlined /> },
  { path: '/console/asr/funasr', label: 'AI 分析与调优', icon: <ExperimentOutlined /> },
];

/** ASR 页面导航与项目提示；内容区由各个域内页面提供。 */
export function AsrFrame({ title, children, projectId }: { title: string; children: ReactNode; projectId?: number }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentProjectId } = useConsoleScope();
  const { token } = theme.useToken();
  const displayedProject = projectId ?? currentProjectId;
  const activeKey = ASR_TABS.find((tab) => location.pathname.startsWith(tab.path))?.path
    ?? (location.pathname.startsWith('/console/asr/runs/') ? '/console/asr/jobs'
      : location.pathname.startsWith('/console/asr/connections') ? '/console/asr/funasr' : '/console/asr/audio');
  return (
    <PageContainer>
      <div className="asr-page" style={{
        '--asr-surface': token.colorBgContainer,
        '--asr-surface-secondary': token.colorFillQuaternary,
        '--asr-border': token.colorBorderSecondary,
        '--asr-text': token.colorText,
        '--asr-text-secondary': token.colorTextSecondary,
        '--asr-primary': token.colorPrimary,
        '--asr-primary-bg': token.colorPrimaryBg,
        '--asr-highlight': token.colorWarningBg,
      } as CSSProperties}>
        <Flex className="asr-page-heading" justify="space-between" align="end" wrap="wrap" gap="middle">
          <div>
            <Typography.Title level={2}>ASR 评测</Typography.Title>
            {title !== 'ASR 评测' && <Text type="secondary">{title}</Text>}
          </div>
        </Flex>
        <Tabs
          className="asr-tabs"
          activeKey={activeKey}
          onChange={(key) => navigate(key)}
          items={ASR_TABS.map((tab) => ({ key: tab.path, label: <span>{tab.icon} {tab.label}</span> }))}
        />
        {!displayedProject && (
          <Alert
            className="asr-scope-alert"
            type="info"
            showIcon
            message="先选择项目"
            description="音频、任务和复核记录按当前项目隔离；模型资源由平台管理员在管理后台维护。"
          />
        )}
        {children}
      </div>
    </PageContainer>
  );
}
