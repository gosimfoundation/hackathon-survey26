/** Header navigation of the benchmark view (see composables/useView.ts). `href` marks static pages outside the app. */
/**
 * `fold`: when the desktop header row does not fit, links move under More in this order (1 first),
 * as many as needed - same rule as the competition header (lib/nav.ts). Links without it always stay.
 */
export interface BenchNavItem { en: string; zh: string; to?: string; href?: string; external?: boolean; fold?: number }

export const benchmarkNavItems: BenchNavItem[] = [
  { en: 'Benchmark', zh: '基准', to: '/benchmark' },
  { en: 'Tasks', zh: '任务', to: '/benchmark/tasks', fold: 4 },
  { en: 'Leaderboards', zh: '排行榜', to: '/benchmark/leaderboard', fold: 3 },
  { en: 'Survey26 test', zh: 'Survey26 检验', to: '/benchmark/survey26', fold: 2 },
  { en: 'Open track', zh: '开放赛道', to: '/open' },
  { en: 'Human console', zh: '人类操作台', href: 'console/index.html', fold: 1 },
  { en: 'Paper', zh: '论文', href: 'https://s26-agents-8ebd56.vercel.app/paper/', external: true, fold: 1 },
]

export const benchmarkSubmit: BenchNavItem = { en: 'Submit', zh: '提交', to: '/benchmark/submit' }

/** Highest `fold` level of the benchmark header. */
export const benchMaxFold = Math.max(0, ...benchmarkNavItems.map(item => item.fold ?? 0))
