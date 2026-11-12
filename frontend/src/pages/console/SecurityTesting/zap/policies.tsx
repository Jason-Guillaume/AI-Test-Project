// 扫描策略与认证子 Tab。
import { Tabs } from 'antd';
import { ProfilesBlock } from './ScanProfiles';
import { AuthProfilesBlock } from './AuthProfiles';

export function PoliciesSubTab({ projectId }: { projectId: number }) {
  return (
    <Tabs
      size="small"
      defaultActiveKey="profiles"
      items={[
        { key: 'profiles', label: '扫描策略', children: <ProfilesBlock projectId={projectId} /> },
        { key: 'auth', label: '认证配置', children: <AuthProfilesBlock projectId={projectId} /> },
      ]}
    />
  );
}
