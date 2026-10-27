import type { ReactNode } from 'react';

export function AuthFrame({
  children,
  variant = 'login',
}: {
  children: ReactNode;
  variant?: 'login' | 'register';
}) {
  return (
    <main className="auth-page">
      <div className={`auth-card auth-card--${variant}`}>
        <aside className="auth-visual" aria-label="测试开发平台介绍">
          <img
            className="auth-visual-image"
            src="/login-visual.svg"
            alt="由接口、自动化和质量检查组成的测试工作流插画"
          />
          <div className="auth-visual-copy">
            <span className="auth-visual-kicker">QUALITY ENGINEERING</span>
            <h2>让质量保障融入<br />每一次交付</h2>
            <p>从测试资产到执行协作，在一个清晰的工作空间里推进质量工程。</p>
          </div>
        </aside>
        <section className="auth-content">
          <div className="auth-brand">
            <span className="auth-brand-mark" aria-hidden="true">Q</span>
            <span>测试开发平台</span>
          </div>
          {children}
        </section>
      </div>
    </main>
  );
}
