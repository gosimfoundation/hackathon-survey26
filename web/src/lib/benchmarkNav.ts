/** Header navigation of the benchmark view (see composables/useView.ts). `href` marks static pages outside the app. */
export interface BenchNavItem { en: string; zh: string; to?: string; href?: string }

export const benchmarkNavItems: BenchNavItem[] = [
  { en: 'Benchmark', zh: '基准', to: '/benchmark' },
  { en: 'Tasks', zh: '任务', to: '/benchmark/tasks' },
  { en: 'Leaderboards', zh: '排行榜', to: '/benchmark/leaderboard' },
  { en: 'Survey26 test', zh: 'Survey26 检验', to: '/benchmark/survey26' },
]

export const benchmarkSubmit: BenchNavItem = { en: 'Submit', zh: '提交', to: '/benchmark/submit' }
