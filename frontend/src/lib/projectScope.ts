/** 项目范围开关：true=商业短视频模板工作台（本项目首版形态）。
 *
 * - 隐藏旧制作流程导航（漫剧/画布/科普短视频/代码生视频站外入口）；
 * - 关闭原项目社区推广浮窗（微信加群）；
 * - 登录后默认进入商业模板库。
 * 上游组件与历史数据保留，置 false 即恢复上游全量导航。
 */
export const COMMERCIAL_PROJECT = true

/** 商业域主导航（本项目核心六页）。 */
export const COMMERCIAL_NAV = [
  { key: 'cv-templates', path: '/commercial/templates', label: '商业模板库' },
  { key: 'cv-actors', path: '/commercial/actors', label: '达人库' },
  { key: 'cv-products', path: '/commercial/products', label: '商品库' },
  { key: 'cv-wardrobes', path: '/commercial/wardrobes', label: '服饰库' },
  { key: 'cv-studio', path: '/commercial/studio', label: '制作工作台' },
  { key: 'cv-tasks', path: '/commercial/tasks', label: '任务与作品' },
  { key: 'cv-settings', path: '/commercial/settings', label: '设置与费用' },
] as const

/** 商业项目登录后的默认落点。 */
export const COMMERCIAL_HOME = '/commercial/templates'
