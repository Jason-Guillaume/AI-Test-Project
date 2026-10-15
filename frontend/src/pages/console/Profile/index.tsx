// 个人中心：当前账号信息、所属组织、通知统计，以及修改密码。
// 修改密码成功后后端会递增 token_version 使旧令牌失效，因此前端主动退出并重新登录。
// 本模块导出 ConsoleProfilePage，由路由 /console/profile 挂载。
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Table,
  Tag,
} from 'antd';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '@/api/auth';
import { organizationsApi } from '@/api/organizations';
import { notificationsApi } from '@/api/notifications';
import { getErrorMessage } from '@/api/client';
import type { NotificationSummary, Organization } from '@/types';
import { useAuth } from '@/hooks/useAuth';
import { OrgRoleTag, PlatformRoleTag } from '@/components/RoleTag';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageContainer,
} from '@/components/PageState';

/**
 * 修改密码弹窗的表单数据结构。
 */
interface PasswordForm {
  // 旧密码，后端用于校验当前身份
  old_password: string;
  // 新密码，前端限制 12-100 字符
  new_password: string;
  // 二次确认密码，仅前端比对，不会随请求发送
  confirm: string;
}

/**
 * 用户控制台个人中心页组件。
 *
 * 用途：展示当前账号信息与所属组织列表，并提供修改密码、退出登录入口。
 * 数据来源：账号信息取自 useAuth().user（不发额外请求）；所属组织来自
 *       organizationsApi.list；通知统计来自 notificationsApi.summary。
 * 修改密码：成功后后端递增 token_version，当前 JWT 立即失效，
 *       因此前端主动 logout 并跳回 /login 重新登录。
 * 失败呈现：三个查询各自独立展示 LoadingState/ErrorState/EmptyState；
 *       改密失败只弹 message.error，弹窗保持打开便于重试。
 * 空态：用户未登录时整个组件返回 null；无组织/无通知统计时展示 EmptyState。
 */
export function ConsoleProfilePage() {
  // user 为空表示未登录；logout 会清掉本地 token 并通知 react-query 失效
  const { user, logout } = useAuth();
  // 从 antd App 上下文取 message，保证主题与 ConfigProvider 配置一致
  const { message } = App.useApp();
  // 用于改密成功、退出登录后跳转
  const navigate = useNavigate();
  // 修改密码弹窗的开关
  const [passwordOpen, setPasswordOpen] = useState(false);
  // 受控表单实例，用于提交与重置字段
  const [passwordForm] = Form.useForm<PasswordForm>();

  // 当前用户所属组织列表
  const orgsQuery = useQuery({
    queryKey: ['organizations'],
    queryFn: () => organizationsApi.list(),
  });
  // 通知统计摘要（总数与未读数）
  const summaryQuery = useQuery({
    queryKey: ['notifications', 'summary'],
    queryFn: () => notificationsApi.summary(),
  });

  // 修改密码的 mutation：请求体只含 old_password / new_password，成功后必须重新登录
  const changePasswordMutation = useMutation({
    mutationFn: authApi.changePassword,
    // 成功后依次：提示 → 关闭弹窗 → 清空表单 → 退出 → 跳登录
    onSuccess: async () => {
      message.success('密码已修改，请使用新密码重新登录');
      setPasswordOpen(false);
      passwordForm.resetFields();
      // 后端已递增 token_version，本地旧令牌随后端校验一起失效
      await logout();
      // replace: true 覆盖个人中心，避免返回键回到需重新登录的页面
      navigate('/login', { replace: true });
    },
    // 改密失败：只提示不关弹窗，用户可直接修改后重试
    onError: (e) => message.error(getErrorMessage(e)),
  });

  // 表单提交回调：先做前端二次确认，再把有效字段交给 mutation
  const onSubmitPassword = async (values: PasswordForm) => {
    // 前端先做二次确认比对，减少一次注定失败的网络往返
    if (values.new_password !== values.confirm) {
      message.error('两次输入的新密码不一致');
      return;
    }
    // confirm 不传给后端，只提交 old_password 与 new_password
    changePasswordMutation.mutate({
      old_password: values.old_password,
      new_password: values.new_password,
    });
  };

  // 未登录时不渲染任何内容（理论上路由守卫会先拦住，这里作为防御）
  if (!user) return null;

  // 归一化为三态：null 表示已加载但无数据（区别于 isPending 的加载中）
  const summary: NotificationSummary | null = summaryQuery.data ?? null;
  // 列表接口返回的是分页结构，这里只取 items 用于展示
  const orgs = orgsQuery.data?.items ?? [];

  return (
    // 页面整体布局：上排两列（账号信息 + 通知统计，窄屏堆叠 xs=24，中屏 md=14/10），
    // 下方「我的组织」表格，以及始终挂载的「修改密码」弹窗（open 控制显隐）。
    <PageContainer>
      <Row gutter={[16, 16]}>
        <Col xs={24} md={14}>
          <Card
            title="账号信息"
            extra={
              <Space>
                <Button
                  size="small"
                  onClick={() => {
                    // 打开弹窗前先清空旧值，避免上一次未提交的输入残留
                    passwordForm.resetFields();
                    setPasswordOpen(true);
                  }}
                >
                  修改密码
                </Button>
                <Button
                  size="small"
                  danger
                  onClick={async () => {
                    // 退出登录：清掉本地 token 后跳回登录页
                    await logout();
                    navigate('/login', { replace: true });
                  }}
                >
                  退出登录
                </Button>
              </Space>
            }
          >
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="用户ID">{user.id}</Descriptions.Item>
              <Descriptions.Item label="用户名">{user.username}</Descriptions.Item>
              <Descriptions.Item label="平台角色">
                <PlatformRoleTag role={user.role} />
              </Descriptions.Item>
              <Descriptions.Item label="账号状态">
                {user.is_active ? <Tag color="blue">正常</Tag> : <Tag>已禁用</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="注册时间">{user.created_at}</Descriptions.Item>
              <Descriptions.Item label="最近更新">{user.updated_at}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} md={10}>
          <Card title="通知统计">
            {summaryQuery.isPending ? (
              <LoadingState tip="加载统计…" />
            ) : summaryQuery.isError ? (
              <ErrorState
                error={summaryQuery.error}
                onRetry={summaryQuery.refetch}
              />
            ) : summary ? (
              <Descriptions column={1} size="small">
                <Descriptions.Item label="通知总数">{summary.total}</Descriptions.Item>
                <Descriptions.Item label="未读">
                  {summary.unread_total}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <EmptyState description="暂无通知统计" />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="我的组织" style={{ marginTop: 16 }}>
        {orgsQuery.isPending ? (
          <LoadingState tip="加载组织…" />
        ) : orgsQuery.isError ? (
          <ErrorState error={orgsQuery.error} onRetry={orgsQuery.refetch} />
        ) : orgs.length === 0 ? (
          <EmptyState description="暂无所属组织" />
        ) : (
          <Table<Organization>
            rowKey={(o) => o.id}
            size="small"
            // 关闭分页：账号通常只归属少量组织，一页内展示即可
            pagination={false}
            dataSource={orgs}
            columns={[
              // 组织名称，来自 organization.name
              { title: '组织', dataIndex: 'name' },
              // my_role 为 null 表示在该组织中不是成员（如仅通过平台角色可见），此时显示「无」
              { title: '组织角色', dataIndex: 'my_role', render: (v: string | null) => (v ? <OrgRoleTag role={v} /> : <Tag>无</Tag>) },
              // 组织当前成员总数，含管理员与普通成员
              { title: '成员数', dataIndex: 'member_count' },
              // 组织创建时间（后端已格式化为可读字符串）
              { title: '创建时间', dataIndex: 'created_at' },
            ]}
          />
        )}
      </Card>

      <Modal
        title="修改密码"
        open={passwordOpen}
        // 点右上角关闭或遮罩，仅收起弹窗，不重置表单（重置在打开前做）
        onCancel={() => setPasswordOpen(false)}
        // 走 Form 的校验流程，校验通过才会回调 onSubmitPassword
        onOk={() => passwordForm.submit()}
        // confirmLoading 绑定 mutation 状态，按钮转圈期间 onOk 不会重复触发提交
        confirmLoading={changePasswordMutation.isPending}
        // 关闭即销毁 DOM，确保下次打开表单是全新实例
        destroyOnClose
      >
        <Form<PasswordForm>
          form={passwordForm}
          layout="vertical"
          onFinish={onSubmitPassword}
        >
          <Form.Item
            name="old_password"
            label="旧密码"
            // 长度校验比新密码宽松（6-30）：兼容用户设置的弱旧密码，长度校验交给后端最终判定
            rules={[
              { required: true, message: '请输入旧密码' },
              { min: 6, max: 30, message: '旧密码 6-30 个字符' },
            ]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            // 新密码强制 12-100 字符，与后端策略一致
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 12, max: 100, message: '新密码 12-100 个字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认新密码"
            // 仅前端二次确认用，不参与提交；字符数需与新密码一致，长度下限同步为 12
            rules={[
              { required: true, message: '请再次输入新密码' },
              { min: 12, max: 100, message: '新密码 12-100 个字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </PageContainer>
  );
}
