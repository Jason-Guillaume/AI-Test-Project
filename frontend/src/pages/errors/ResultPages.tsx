import { Result, Button } from 'antd';
import { Link } from 'react-router-dom';

/**
 * 403 无权限页。
 *
 * 纯展示组件，不发请求：由路由守卫或接口返回 403 时跳转渲染。
 * 只提供一个返回控制台的入口，避免用户卡在无权限状态。
 */
export function ForbiddenPage() {
  return (
    <Result
      status="403"
      title="403"
      subTitle="你没有访问该资源的权限。"
      extra={
        <Link to="/console">
          <Button type="primary">返回控制台</Button>
        </Link>
      }
    />
  );
}

/**
 * 404 页面不存在。
 *
 * 纯展示组件，不发请求：路由未匹配或资源已被删除时渲染。
 */
export function NotFoundPage() {
  return (
    <Result
      status="404"
      title="404"
      subTitle="页面不存在或已被移除。"
      extra={
        <Link to="/console">
          <Button type="primary">返回控制台</Button>
        </Link>
      }
    />
  );
}
