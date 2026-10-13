// 角色标签：平台角色、组织角色、项目角色统一展示。
import { Tag } from 'antd';
import { PROJECT_ROLE_LABELS, ORG_ROLE_LABELS } from '@/hooks/useCapabilities';
import type { PlatformRole } from '@/types';

// 平台角色的中文展示文案。
const PLATFORM_ROLE_LABELS: Record<PlatformRole, string> = {
  admin: '平台管理员',
  test: '测试工程师',
  dev: '开发工程师',
};

// 平台角色对应的标签配色：与展示文案一一对应，改文案时同步改这里。
const PLATFORM_ROLE_COLORS: Record<PlatformRole, string> = {
  admin: 'magenta',
  test: 'blue',
  dev: 'cyan',
};

/**
 * 平台角色标签。
 *
 * 纯展示组件，不发请求。role 取值见 PlatformRole；
 * 文案或配色缺失时兜底显示原始 role 值，避免渲染成空白。
 */
export function PlatformRoleTag({ role }: { role: PlatformRole }) {
  return (
    <Tag color={PLATFORM_ROLE_COLORS[role] ?? 'default'}>
      {PLATFORM_ROLE_LABELS[role] ?? role}
    </Tag>
  );
}

/**
 * 组织角色标签。
 *
 * 纯展示组件，不发请求。role 为后端返回的字符串角色名，
 * owner / platform_admin / admin 三种高亮，其余统一灰色。
 */
export function OrgRoleTag({ role }: { role: string }) {
  const color =
    role === 'owner' || role === 'platform_admin'
      ? 'gold'
      : role === 'admin'
        ? 'geekblue'
        : 'default';
  // 文案映射缺项时直接展示后端原始值，便于发现后端新增角色。
  return <Tag color={color}>{ORG_ROLE_LABELS[role] ?? role}</Tag>;
}

/**
 * 项目角色标签。
 *
 * 纯展示组件，不发请求。role 可能为 null/undefined（当前用户在项目外），
 * 此时显示灰色“-”而不是空标签，让权限缺口一眼可见。
 */
export function ProjectRoleTag({ role }: { role: string | null | undefined }) {
  if (!role) return <span style={{ color: '#999' }}>-</span>;
  const color =
    role === 'admin'
      ? 'magenta'
      : role === 'owner'
        ? 'gold'
        : role === 'editor'
          ? 'geekblue'
          : role === 'member'
            ? 'blue'
            : 'default';
  return <Tag color={color}>{PROJECT_ROLE_LABELS[role] ?? role}</Tag>;
}
