/**
 * 商业六页公共布局：复用 AppShell（顶栏导航/内容宽度/窄屏），
 * 隐藏原项目页脚（含联系方式与微信，不再引入推广），保留许可证与来源。
 * 只做布局壳，不含业务逻辑；RequireAuth 由路由层继续负责。
 */
import type { ReactNode } from 'react'
import AppShell from '../../components/layout/AppShell'

export default function CommercialLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell hideFooter>
      {children}
    </AppShell>
  )
}

/** 商业页统一的标题区（复用 pf-section-head 层级与边距）。 */
export function CommercialPageHead({ title, desc, children }: {
  title: string; desc?: string; children?: ReactNode
}) {
  return (
    <div className="pf-section-head">
      <div>
        <h2>{title}</h2>
        {desc && <p>{desc}</p>}
      </div>
      {children}
    </div>
  )
}

/** 模拟模式提示：主文案用业务语言；技术详情可展开，不隐藏真实运行状态。 */
export function MockModeNote({ onToggleTech, techOpen }: { onToggleTech?: () => void; techOpen?: boolean }) {
  return (
    <div style={{ margin: '4px 0 12px' }}>
      <p className="pf-muted" style={{ fontSize: 12, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          display: 'inline-block', padding: '1px 8px', borderRadius: 999,
          background: '#fff3e0', color: '#b26a00', fontSize: 11,
        }}>测试模式</span>
        当前为本地演示：生成与费用均为模拟数据，正式效果需等真实联调。
        {onToggleTech && (
          <button type="button" onClick={onToggleTech}
            style={{ border: 'none', background: 'none', color: 'var(--pf-muted)', cursor: 'pointer',
                     fontSize: 12, textDecoration: 'underline', padding: 0 }}>
            {techOpen ? '收起技术详情' : '技术详情'}
          </button>
        )}
      </p>
      {techOpen && (
        <p className="pf-muted" style={{ fontSize: 12, margin: '6px 0 0', paddingLeft: 4 }}>
          解析 / 文案 / 报价 / 生成走本地 Mock；费用记入演示预算池（scope=mock），不构成真实付费授权；
          能力验证清单为空，真实付费执行保持关闭。
        </p>
      )}
    </div>
  )
}
