// 项目角色能力判定，与后端 PROJECT_ROLE_RANKS 对齐。
// 服务端鉴权为准；这里只用于前端按钮展示（隐藏无权限入口，不做真实拦截）。
//
// 等级数值越大权限越高，比较采用「>=」，因此高等级角色天然包含低等级能力。

/**
 * 项目角色等级表。
 *
 * 由展示代码与能力判定共用；新增角色时前后端都必须同步加值，
 * 否则 normalizeProjectRole 会把它降级成 viewer。
 */
export const PROJECT_ROLE_RANKS: Record<string, number> = {
  viewer: 0, // 只读：只能看，不能写
  member: 1, // 可写：能创建/修改项目内数据
  editor: 2, // 管理：可管理项目配置与资源
  owner: 3, // 负责人：可管理项目成员
  admin: 4, // 平台管理员在项目内的等价角色（最高）
};

/** 项目角色的中文展示名，供下拉、标签与表格渲染使用。 */
export const PROJECT_ROLE_LABELS: Record<string, string> = {
  viewer: '只读成员', // 只读成员
  member: '普通成员', // 普通成员
  editor: '项目管理员', // 项目管理员
  owner: '项目负责人', // 项目负责人
  admin: '平台管理员', // 平台管理员
};

/** 组织角色的中文展示名；platform_admin 是跨组织的平台级身份。 */
export const ORG_ROLE_LABELS: Record<string, string> = {
  owner: '组织负责人', // 组织负责人
  admin: '组织管理员', // 组织管理员
  member: '组织成员', // 组织成员
  platform_admin: '平台管理员', // 平台管理员
};

/**
 * 归一化项目角色字符串。
 *
 * 大小写不敏感，并把未知或缺失值统一降级为 'viewer'，
 * 这样调用方无需再判空或判未知枚举。
 *
 * @param role 后端返回的角色值，可能为 null / undefined / 大写形式
 * @returns 一定是 PROJECT_ROLE_RANKS 中存在的键
 */
export function normalizeProjectRole(role: string | null | undefined): string {
  // 空值先转成空串，避免对 null/undefined 调用 toLowerCase。
  const value = (role || '').toLowerCase();
  return value in PROJECT_ROLE_RANKS ? value : 'viewer';
}

/**
 * 判断当前角色是否达到指定角色等级。
 *
 * @param myRole 当前用户角色（可能为 null，视为不具备任何权限）
 * @param required 需要的最低角色等级
 * @returns myRole 为空返回 false；required 不在等级表中比较结果为 false
 */
export function hasProjectRole(
  myRole: string | null | undefined,
  required: string,
): boolean {
  if (!myRole) return false;
  return (
    PROJECT_ROLE_RANKS[normalizeProjectRole(myRole)] >=
    PROJECT_ROLE_RANKS[required]
  );
}

/**
 * 是否可管理项目（编辑项目级配置），门槛为 editor。
 *
 * @param myRole 当前用户角色
 * @returns editor 及以上返回 true
 */
export function canManageProject(myRole: string | null | undefined): boolean {
  return hasProjectRole(myRole, 'editor');
}

/**
 * 是否可管理项目成员（增删成员、改成员角色），门槛为 owner。
 *
 * @param myRole 当前用户角色
 * @returns owner 及以上返回 true
 */
export function canManageProjectMembers(
  myRole: string | null | undefined,
): boolean {
  return hasProjectRole(myRole, 'owner');
}

/**
 * 是否可写入项目数据，门槛为 member（viewer 为纯只读）。
 *
 * @param myRole 当前用户角色
 * @returns member 及以上返回 true
 */
export function canWriteProject(myRole: string | null | undefined): boolean {
  return hasProjectRole(myRole, 'member');
}
