// 组织管理：组织列表 + 成员/组织角色/模型授权管理。
import {
  App,
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Switch,
  Tag,
} from 'antd';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { organizationsApi } from '@/features/organizations/api/organizations';
import type { MemberGrant } from '@/features/organizations/contracts';
import type { Organization, OrganizationMember, OrganizationRole } from '@/features/organizations/contracts';

import { ErrorState, LoadingState, PageContainer } from '@/shared/ui/PageState';
import { OrgRoleTag } from '@/features/identity/components/RoleTag';
import { getErrorMessage } from '@/shared/api/client';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useAuth } from '@/app/providers/AuthProvider';
import { platformRoleLabel } from '@/features/identity/components/RoleTag';

// 组织角色下拉选项：owner > admin > member 三级
const ORG_ROLE_OPTIONS: { label: string; value: OrganizationRole }[] = [
  { label: '组织负责人', value: 'owner' },
  { label: '组织管理员', value: 'admin' },
  { label: '组织成员', value: 'member' },
];

/**
 * 组织管理页。
 *
 * 用途：管理全平台的组织列表与每个组织的成员/角色/模型授权。
 * 数据来源：organizationsApi.list 拉全部组织；选中组织后单独拉 members 与 availableModels。
 * 布局：左侧组织列表（默认选中第一个），右侧成员详情。
 * 是否发请求：是，列表 + 成员 + 可用模型三个查询；写操作走各 mutation。
 * 权限：非组织成员时「添加/更新成员」按钮 disabled；组织负责人不允许转移/移除。
 * 失败呈现：mutation 失败 message.error 折叠展示；查询失败整页 ErrorState。
 * 空态：组织无成员时列表显示「暂无成员」；无组织时右侧显示「请选择左侧组织」。
 */
export function AdminOrganizationsPage() {
  const { user } = useAuth();
  const canManage = user?.role === 'admin';
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  // 当前选中的组织 ID；null 表示尚未选中（默认回退到列表第一项）
  const [activeId, setActiveId] = useState<number | null>(null);
  // 新建组织弹窗开关
  const [creating, setCreating] = useState(false);
  // 新建组织表单
  const [createForm] = Form.useForm<{ name: string }>();
  // 成员抽屉状态：open 是否打开、editing 是否编辑已有成员
  const [memberDrawer, setMemberDrawer] = useState<{
    open: boolean;
    editing?: OrganizationMember | null;
  }>({ open: false });

  // 组织列表：全局一次请求
  const listQuery = useQuery({
    queryKey: ['organizations'],
    queryFn: () => organizationsApi.list(),
  });
  const effectiveOrgId = activeId ?? listQuery.data?.items[0]?.id ?? null;
  // 默认组织与成员、模型查询共用同一个有效 ID，避免首屏详情查询被跳过。
  const membersQuery = useQuery({
    queryKey: ['organizations', effectiveOrgId, 'members'],
    queryFn: () => organizationsApi.members(effectiveOrgId!),
    enabled: effectiveOrgId !== null,
  });
  // 可分配模型列表：给成员授权下拉用
  const modelsQuery = useQuery({
    queryKey: ['organizations', effectiveOrgId, 'models'],
    queryFn: () => organizationsApi.availableModels(effectiveOrgId!),
    enabled: effectiveOrgId !== null && canManage,
  });

  const createMutation = useMutation({
    mutationFn: organizationsApi.create,
    onSuccess: () => {
      message.success('组织已创建');
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
      setCreating(false);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  const upsertMutation = useMutation({
    // 成员 upsert：body 里带 orgId/memberId/grant 三件套
    mutationFn: (body: { orgId: number; memberId: number; grant: MemberGrant }) =>
      organizationsApi.upsertMember(body.orgId, body.memberId, body.grant),
    onSuccess: () => {
      message.success('成员已保存');
      queryClient.invalidateQueries({
        queryKey: ['organizations', effectiveOrgId, 'members'],
      });
      setMemberDrawer({ open: false });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  const removeMutation = useMutation({
    mutationFn: (body: { orgId: number; memberId: number }) =>
      organizationsApi.removeMember(body.orgId, body.memberId),
    onSuccess: () => {
      message.success('成员已移除');
      queryClient.invalidateQueries({
        queryKey: ['organizations', effectiveOrgId, 'members'],
      });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  const transferMutation = useMutation({
    mutationFn: (body: { orgId: number; memberId: number }) =>
      organizationsApi.transferOwnership(body.orgId, body.memberId),
    // 转移负责人后同时失效组织列表与当前组织成员（成员角色会变化）
    onSuccess: () => {
      message.success('负责人已转移');
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
      queryClient.invalidateQueries({
        queryKey: ['organizations', effectiveOrgId, 'members'],
      });
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id }: { id: number; nextId: number | null }) => organizationsApi.remove(id),
    onSuccess: (result, variables) => {
      message.success(`组织「${result.name}」已移入回收站，用户账号保留`);
      queryClient.setQueryData(['organizations'], (current: typeof listQuery.data | undefined) => current
        ? { ...current, items: current.items.filter((item) => item.id !== result.id), total: Math.max(current.total - 1, 0) }
        : current);
      setActiveId(variables.nextId);
      queryClient.invalidateQueries({ queryKey: ['organizations'] });
      queryClient.invalidateQueries({ queryKey: ['organizations', result.id] });
    },
    onError: (error) => message.error(getErrorMessage(error, '删除组织失败')),
  });

  // 加载中：整页 LoadingState；失败：整页 ErrorState + 重试
  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={listQuery.error} onRetry={listQuery.refetch} />
      </PageContainer>
    );

  const orgs = listQuery.data.items;
  // 默认回退：activeId 未选中或对应组织已删除时，取列表第一项
  const activeOrg = orgs.find((o) => o.id === effectiveOrgId) ?? null;
  const activeOrgId = activeOrg?.id ?? null;

  const confirmDelete = async (org: Organization) => {
    try {
      const impact = await organizationsApi.previewDelete(org.id);
      const index = orgs.findIndex((item) => item.id === org.id);
      const nextId = activeOrgId === org.id
        ? (orgs[index + 1]?.id ?? orgs[index - 1]?.id ?? null)
        : activeOrgId;
      modal.confirm({
        title: `删除组织「${impact.name}」？`,
        width: 560,
        content: <Space direction="vertical" style={{ width: '100%' }}>
          <p>成员关系将解除，用户账号保留。可在回收站恢复组织和成员关系。</p>
          <p>成员：{impact.member_count} 人；关联项目：{impact.project_count} 个</p>
          {impact.project_count > 0 ? <>
            <Alert type="warning" showIcon message="请先迁移或处理关联项目，避免项目归属丢失。当前不能删除此组织。" />
            <List size="small" dataSource={impact.projects} renderItem={(project) => (
              <List.Item>#{project.id} {project.name}{project.is_in_recycle_bin ? '（在回收站）' : ''}</List.Item>
            )} />
          </> : null}
        </Space>,
        okText: '移入回收站',
        okType: 'danger',
        okButtonProps: { disabled: impact.project_count > 0, loading: deleteMutation.isPending },
        cancelText: '取消',
        onOk: () => deleteMutation.mutateAsync({ id: org.id, nextId }),
      });
    } catch (error) {
      message.error(getErrorMessage(error, '无法获取组织删除影响'));
    }
  };

  return (
    <PageContainer>
      <PageHeader title="组织管理" subtitle="维护组织成员、角色与模型授权" />
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        {canManage && <Button type="primary" onClick={() => setCreating(true)}>新建组织</Button>}
      </Space>

      <div className="organization-layout">
        {orgs.length === 0 && !canManage ? (
          <div style={{ padding: 24, color: '#666' }}>等待平台管理员分配组织</div>
        ) : null}
        {/* 左侧：组织列表；点击选中高亮，切换右侧详情 */}
        <List
          className="organization-layout__list"
          bordered
          dataSource={orgs}
          renderItem={(org: Organization) => (
            <List.Item
              actions={canManage ? [<Button key="delete" size="small" danger type="link"
                onClick={(event) => { event.stopPropagation(); void confirmDelete(org); }}>
                删除组织
              </Button>] : undefined}
              style={{
                cursor: 'pointer',
                background:
                  org.id === activeOrgId ? 'rgba(24,144,255,0.08)' : undefined,
              }}
              onClick={() => setActiveId(org.id)}
            >
              <List.Item.Meta
                title={org.name}
                description={
                  <Space size="small">
                    <OrgRoleTag role={org.my_role ?? ''} />
                    <Tag>成员 {org.member_count}</Tag>
                  </Space>
                }
              />
            </List.Item>
          )}
        />

        <div style={{ minWidth: 0 }}>
          {activeOrg ? (
            <>
              <Space wrap className="ui-list-toolbar"
                style={{
                  marginBottom: 12,
                  justifyContent: 'space-between',
                  width: '100%',
                }}
              >
                <strong>{activeOrg.name}</strong>
                {/* 只有当前用户是该组织成员时才允许添加/更新成员 */}
                {canManage && <Button
                  onClick={() =>
                    setMemberDrawer({ open: true, editing: null })
                  }
                  disabled={!activeOrgId}
                >
                  添加/更新成员
                </Button>}
              </Space>
              <List
                bordered
                loading={membersQuery.isPending}
                dataSource={membersQuery.data?.items ?? []}
                locale={{ emptyText: '暂无成员' }}
                renderItem={(member: OrganizationMember) => (
                  <List.Item
                    /* 三个操作：编辑（任何成员都可以）、转为负责人、移除；后两者对组织负责人 disabled */
                    actions={canManage ? [
                      <Button
                        key="edit"
                        size="small"
                        onClick={() =>
                          setMemberDrawer({ open: true, editing: member })
                        }
                      >
                        编辑
                      </Button>,
                      <Button
                        key="transfer"
                        size="small"
                        disabled={member.is_org_owner}
                        onClick={() =>
                          transferMutation.mutate({
                            orgId: activeOrg.id,
                            memberId: member.user_id,
                          })
                        }
                      >
                        转为负责人
                      </Button>,
                      <Button
                        key="remove"
                        size="small"
                        danger
                        disabled={member.is_org_owner}
                        onClick={() =>
                          removeMutation.mutate({
                            orgId: activeOrg.id,
                            memberId: member.user_id,
                          })
                        }
                      >
                        移除
                      </Button>,
                    ] : []}
                  >
                    <List.Item.Meta
                      title={`用户 #${member.user_id}`}
                      description={
                        <Space size="small">
                          <OrgRoleTag role={member.role} />
                          {member.agent_enabled && <Tag color="purple">智能体开放</Tag>}

                          {member.is_org_owner && <Tag color="gold">负责人</Tag>}
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            </>
          ) : (
            <div style={{ color: '#999', padding: 24 }}>
              {orgs.length === 0 ? (canManage ? '暂无组织，请新建组织并添加成员。' : '等待平台管理员分配组织') : '请选择左侧组织'}
            </div>
          )}
        </div>
      </div>

      <Modal
        title="新建组织"
        open={creating}
        confirmLoading={createMutation.isPending}
        onCancel={() => setCreating(false)}
        onOk={() =>
          createForm.validateFields().then((v) => createMutation.mutate({ name: v.name }))
        }
      >
        <Form layout="vertical" form={createForm}>
          <Form.Item
            label="组织名称"
            name="name"
            required
            rules={[{ min: 2, max: 100, message: '组织名称 2-100 个字符' }]}
          >
            <Input placeholder="至少 2 个字符" />
          </Form.Item>
        </Form>
      </Modal>

      <MemberDrawer
        key={`${activeOrgId ?? 'none'}-${memberDrawer.editing?.user_id ?? 'new'}`}
        open={memberDrawer.open}
        editing={memberDrawer.editing}
        models={modelsQuery.data?.items ?? []}
        onCancel={() => setMemberDrawer({ open: false })}
        onSubmit={(grant) =>
          upsertMutation.mutate({
            orgId: activeOrgId!,
            memberId: grant.user_id,
            grant,
          })
        }
        loading={upsertMutation.isPending}
        orgId={activeOrgId}
      />
    </PageContainer>
  );
}

/**
 * 组织成员添加/编辑抽屉。
 *
 * 用途：新建时通过 onFindCandidate 查找用户名，找到后写入隐藏字段 user_id；
 *       编辑时直接把 editing.user_id 作为提交目标。
 * 是否发请求：本组件不发写请求；查找候选用户通过 onFindCandidate 回调触发。
 * 提交：收集 role/agent_enabled/allowed_model_ids，user_id 取 editing.user_id 或表单值。
 * 失败呈现：Form 就地展示 rules 提示；查找候选用户返回空 item 时保持「请先查找」提示。
 */
function MemberDrawer({
  open,
  editing,
  loading,
  onCancel,
  onSubmit,
  orgId,
}: {
  open: boolean;
  editing?: OrganizationMember | null;
  models: { domain_id: string; label: string }[];
  loading: boolean;
  onCancel: () => void;
  onSubmit: (grant: MemberGrant) => void;
  orgId: number | null;
}) {
  const [form] = Form.useForm<MemberGrant & { username: string }>();
  const [keyword, setKeyword] = useState('');
  const [selectedCandidate, setSelectedCandidate] = useState<{
    id: number; username: string; role: string; is_active: boolean; is_member: boolean;
  } | null>(null);
  const candidatesQuery = useInfiniteQuery({
    queryKey: ['organization-candidates', orgId, keyword],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => organizationsApi.listCandidates(orgId!, keyword, pageParam),
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: open && !editing && orgId != null,
  });
  const candidates = candidatesQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const options = [...candidates];
  if (selectedCandidate && !options.some((item) => item.id === selectedCandidate.id)) {
    options.unshift(selectedCandidate);
  }

  return (
    <Drawer
      title={editing ? '更新组织成员' : '添加组织成员'}
      open={open}
      onClose={onCancel}
      width={420}
      destroyOnClose
      extra={
        <Button
          type="primary"
          loading={loading}
          // 保存：优先使用 editing.user_id（编辑场景），否则用表单查找到的 user_id
          onClick={async () => {
            const values = await form.validateFields();
            onSubmit({
              user_id: editing?.user_id ?? values.user_id,
              role: values.role,
              agent_enabled: values.agent_enabled ?? false,
              allowed_model_ids: values.allowed_model_ids ?? [],
            });
          }}
        >
          保存
        </Button>
      }
    >
      <Form
        layout="vertical"
        form={form}
        // 默认角色 member、智能体关闭、无模型授权；编辑时回填当前值
        initialValues={{
          role: 'member',
          agent_enabled: editing?.agent_enabled ?? false,
          allowed_model_ids: editing?.allowed_model_ids ?? [],
          username: '',
        }}
      >
        {/* 仅新建时展示用户名查找；编辑时 user_id 由 editing 决定 */}
        {!editing && (
          <Form.Item label="人员" name="user_id" rules={[{ required: true, message: '请选择人员' }]}>
            <Select
              showSearch
              allowClear
              filterOption={false}
              placeholder="搜索并选择启用账号"
              loading={candidatesQuery.isFetching}
              options={options.map((item) => ({
                value: item.id,
                label: `${item.username} · ${platformRoleLabel(item.role)}${item.is_member ? ' · 已加入' : ''}`,
              }))}
              notFoundContent={candidatesQuery.isError ? '候选加载失败，请修改关键词重试' : candidatesQuery.isFetching ? '正在加载候选…' : '没有匹配的启用账号'}
              onPopupScroll={(event) => {
                const element = event.currentTarget;
                if (element.scrollTop + element.clientHeight >= element.scrollHeight - 24 && candidatesQuery.hasNextPage && !candidatesQuery.isFetchingNextPage) {
                  void candidatesQuery.fetchNextPage();
                }
              }}
              onSearch={(value) => {
                if (value !== selectedCandidate?.username) {
                  form.setFieldValue('user_id', undefined);
                  setSelectedCandidate(null);
                }
                setKeyword(value);
              }}
              onChange={(value) => {
                const candidate = candidates.find((item) => item.id === value) ?? null;
                setSelectedCandidate(candidate);
              }}
            />
          </Form.Item>
        )}
        {!editing && (
          <Form.Item shouldUpdate noStyle>
            {() => {
              const id = form.getFieldValue('user_id');
              const candidate = options.find((item) => item.id === id) ?? selectedCandidate;
              return candidate ? <Tag color="green">已选择：{candidate.username}</Tag> : <Tag>请选择一个人员</Tag>;
            }}
          </Form.Item>
        )}
        <Form.Item label="组织角色" name="role">
          <Select options={ORG_ROLE_OPTIONS} />
        </Form.Item>
        <Form.Item
          label="开放智能体能力"
          name="agent_enabled"
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

      </Form>
    </Drawer>
  );
}
