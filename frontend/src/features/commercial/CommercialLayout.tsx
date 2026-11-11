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

/** 模拟模式全局提示条：置底、不打断操作。 */
export function MockModeNote() {
  return (
    <p className="pf-muted" style={{ fontSize: 12, margin: '4px 0 12px' }}>
      开发模拟模式：解析 / 文案 / 报价 / 生成为本地 Mock，费用为演示池（scope=mock），不代表真实模型效果与真实付费授权。
    </p>
  )
}
