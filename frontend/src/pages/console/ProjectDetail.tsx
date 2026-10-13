// 项目详情：当前用户可见项目及允许的管理操作（按 my_role 控制按钮）。
// 本模块导出 ConsoleProjectDetailPage，由路由 /console/projects/:id 挂载。
import { App, Button, Modal, Space, Table, Tag } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { projectsApi } from '@/api/projects';
import type { ProjectMember } from '@/types';
import {
  canManageProject,
  canManageProjectMembers,
} from '@/hooks/useCapabilities';
import { ErrorState, LoadingState, PageContainer } from '@/components/PageState';
import { ProjectRoleTag } from '@/components/RoleTag';
import { getErrorMessage } from '@/api/client';

/**
 * 用户控制台的项目详情页组件。
 *
 * 用途：展示单个项目的元信息与成员列表，并按当前用户的 my_role 决定可执行的管理操作。
 * 数据来源：projectsApi.get 单个项目详情，其中 my_role 是后端按当前用户计算出的角色。
 * 权限判定：canManageProject(myRole) 决定是否允许编辑项目；
 *       canManageProjectMembers(myRole) 决定是否允许增删成员。无权限时按钮禁用并给出提示。
 * 403/404 行为：后端对不可见项目返回 403/404 错误信封，前端不特判，
 *       统一落到 ErrorState 并允许重试（错误详情由 getErrorMessage 从信封中取出）。
 * 失败呈现：详情接口失败时整页换成可重试的 ErrorState；移除成员失败只弹 message.error。
 * 空态：项目无成员时表格显示「暂无成员」。
 */
export function ConsoleProjectDetailPage() {
  // 路由参数 id 是字符串，需要转成 number 才能拼进请求路径
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const { message } = App.useApp();
  // 用于在成功后刷新本项目详情缓存
  const queryClient = useQueryClient();
  // 待移除成员的用户 ID；非 null 时打开确认弹窗
  const [removingId, setRemovingId] = useState<number | null>(null);

  const detailQuery = useQuery({
    queryKey: ['project', projectId, 'detail'],
    queryFn: () => projectsApi.get(projectId),
    // 路径参数缺失（如手动访问空路径）时不发请求，避免出现 NaN 的无效调用
    enabled: !Number.isNaN(projectId),
  });

  const removeMemberMutation = useMutation({
    mutationFn: (memberId: number) => projectsApi.removeMember(projectId, memberId),
    onSuccess: () => {
      message.success('成员已移除');
      queryClient.invalidateQueries({
        queryKey: ['project', projectId, 'detail'],
      });
      // 成功后关闭确认弹窗
      setRemovingId(null);
    },
    onError: (e) => message.error(getErrorMessage(e)),
  });

  // 加载中：整页只放一个 LoadingState
  if (detailQuery.isPending) return <LoadingState />;
  // 失败（含后端 403/404 错误信封）：换成可重试的 ErrorState
  if (detailQuery.isError)
    return (
      <PageContainer>
        <ErrorState error={detailQuery.error} onRetry={detailQuery.refetch} />
      </PageContainer>
    );

  const project = detailQuery.data;
  // my_role 由后端返回，是前端所有权限判断的唯一依据，不在前端自行推断
  const myRole = project.my_role;
  const canManage = canManageProject(myRole);
  const canManageMembers = canManageProjectMembers(myRole);

  return (
    <PageContainer>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <div>
          <h2 style={{ margin: 0 }}>{project.name}</h2>
          <Space size="small" style={{ color: '#666' }}>
            <Tag /* 项目未挂到任何组织时 organization_name 为 null，展示「无」而非空串 */>组织：{project.organization_name ?? '无'}</Tag>
            <Tag>负责人：{project.owner_username ?? '未知'}</Tag>
            <span>我的角色：</span>
            <ProjectRoleTag role={myRole} />
          </Space>
        </div>
        <div>
          <strong>项目描述</strong>
          <p /* 描述可为空，用占位文案兜底 */ style={{ color: '#666' }}>{project.description ?? '（无）'}</p>
        </div>
        <div>
          <Space
            style={{
              justifyContent: 'space-between',
              width: '100%',
              marginBottom: 8,
            }}
          >
            <strong>项目成员</strong>
            {!canManageMembers && (
              <Tag /* 只读角色直接说明为什么不能管理成员，避免按钮静默禁用 */ color="orange">仅项目负责人可管理成员</Tag>
            )}
          </Space>
          <Table<ProjectMember>
            rowKey={(m) => m.user_id}
            size="small"
            pagination={false}
            dataSource={project.members ?? []}
            locale={{ emptyText: '暂无成员' }}
            columns={[
              { title: '用户ID', dataIndex: 'user_id', width: 80 },
              { title: '用户名', dataIndex: 'username' },
              { title: '角色', dataIndex: 'role', render: (v: string) => <ProjectRoleTag role={v} /> },
              { title: '负责人', dataIndex: 'is_owner', render: (v: boolean) => (v ? <Tag color="gold">是</Tag> : '否') },
              {
                title: '操作',
                key: 'actions',
                render: (_: unknown, m: ProjectMember) => (
                  <Button /* 双保险：无成员管理权限时禁用；负责人本人不可被移除 */ size="small"
                    danger
                    disabled={!canManageMembers || m.is_owner}
                    onClick={() => setRemovingId(m.user_id)}
                  >
                    移除
                  </Button>
                ),
              },
            ]}
          />
        </div>
        {!canManage && (
          <Tag /* 非管理员角色给出只读提示，说明还需要什么权限才能编辑 */ color="blue">
            当前为只读/普通成员视图，编辑项目需项目管理员及以上权限。
          </Tag>
        )}
      </Space>

      <Modal
        title="确认移除成员"
        open={removingId !== null}
        okText="移除"
        okButtonProps={{ danger: true }}
        onCancel={() => setRemovingId(null)}
        onOk={() => {
          // 防御性判断：removingId 可能在等待确认期间被置空
          if (removingId !== null) removeMemberMutation.mutate(removingId);
        }}
        /* 请求期间转圈，防止重复点击提交两次移除 */ confirmLoading={removeMemberMutation.isPending}
      >
        确定移除成员 #{removingId} 吗？该操作不可撤销。
      </Modal>
    </PageContainer>
  );
}
