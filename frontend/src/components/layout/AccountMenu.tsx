import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { COMMERCIAL_PROJECT } from '../../lib/projectScope'
import { Images, ListTodo, LogOut, Settings2, Store, UserRound, Wallet } from 'lucide-react'
import type { User } from '../../api'
import { useI18n } from '../../i18n'
import { PERSONAL_NAV } from '../../lib/siteNavigation'
import UserAvatar from '../UserAvatar'

type Props = {
  user: User | null
  open: boolean
  marketplaceEnabled: boolean
  onOpenChange: (open: boolean) => void
  onNavigate: () => void
  onLogout: () => void
}

/** 头像展开个人入口；支持键盘、点击外部关闭及焦点返回。 */
export default function AccountMenu({ user, open, marketplaceEnabled, onOpenChange, onNavigate, onLogout }: Props) {
  const { t } = useI18n()
  /* wrapper 判断外部点击，button 负责关闭后的键盘焦点，panel 提供首个入口。 */
  const wrapperRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const frame = window.requestAnimationFrame(() => panelRef.current?.querySelector<HTMLElement>('a[href]')?.focus())
    /** 外部点击保持点击目标的默认焦点。 */
    function closeOutside(event: PointerEvent) {
      if (event.target instanceof Node && !wrapperRef.current?.contains(event.target)) onOpenChange(false)
    }
    /** Escape 收起个人菜单并返回头像。 */
    function closeWithEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      onOpenChange(false)
      buttonRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeWithEscape)
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeWithEscape)
    }
  }, [open, onOpenChange])

  if (!user) return <Link to="/auth?next=/" className="pf-topbar-account" title={t('nav.login')} aria-label={t('nav.login')}><UserRound size={18} aria-hidden /></Link>

  return <div ref={wrapperRef} className="pf-topbar-account-wrap" onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) onOpenChange(false)
  }}>
    <button ref={buttonRef} type="button" className={`pf-topbar-account${open ? ' is-active' : ''}`} title={`${user.nickname} · ${t('nav.accountMenu')}`} aria-label={t('nav.accountMenu')} aria-expanded={open} aria-controls="pf-account-menu" onClick={() => onOpenChange(!open)} onKeyDown={(event) => {
      if (event.key === 'ArrowDown') { event.preventDefault(); onOpenChange(true) }
    }}><UserAvatar user={user} size="sm" /></button>
    {open && <div ref={panelRef} id="pf-account-menu" className="pf-topbar-account-panel">
      <div className="pf-topbar-account-heading"><strong>{user.nickname || t('common.creator')}</strong><span>{user.email}</span></div>
      <nav aria-label={t('nav.accountMenu')}>
        <div className="pf-topbar-account-group" role="group" aria-label={t('nav.myCreation')}>
          <span>{t('nav.myCreation')}</span>
          {!COMMERCIAL_PROJECT && PERSONAL_NAV.map((item) => {
            const Icon = item.key === 'tasks' ? ListTodo : Images
            return <Link key={item.key} to={item.path} onClick={onNavigate}><Icon size={17} aria-hidden /><span>{t(item.label)}</span></Link>
          })}
          {COMMERCIAL_PROJECT && <Link to="/commercial/tasks" onClick={onNavigate}><ListTodo size={17} aria-hidden /><span>商业作品</span></Link>}
          {marketplaceEnabled && <Link to="/marketplace/mine" onClick={onNavigate}><Store size={17} aria-hidden /><span>{t('nav.myPublishing')}</span></Link>}
        </div>
        <div className="pf-topbar-account-group" role="group" aria-label={t('nav.accountManagement')}>
          <span>{t('nav.accountManagement')}</span>
          <Link to="/settings" onClick={onNavigate}><Settings2 size={17} aria-hidden /><span>{t('nav.profile')}</span></Link>
          {!COMMERCIAL_PROJECT && <Link to="/settings?tab=subscription" onClick={onNavigate}><Wallet size={17} aria-hidden /><span>{t('nav.balanceBilling')}</span></Link>}
        </div>
      </nav>
      <button type="button" className="pf-topbar-account-logout" onClick={onLogout}><LogOut size={17} aria-hidden /><span>{t('settings.logout')}</span></button>
    </div>}
  </div>
}
