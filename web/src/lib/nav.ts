/** Header navigation: the main destinations (ending with About), everything else under "More". */
/**
 * `fold`: when the desktop header row does not fit, main links move under More in this order
 * (1 first), as many as needed. Links without it always stay in the row.
 */
/** `divider`: a thin rule above the item in the More menu (reference pages above, announcements below). */
export interface NavItem { key: string; to: string; fold?: number; divider?: boolean }

export const mainNavItems: NavItem[] = [
  { key: 'nav.start', to: '/start' },
  { key: 'nav.rules', to: '/rules', fold: 2 },
  { key: 'nav.leaderboard', to: '/leaderboard', fold: 3 },
  { key: 'nav.teammates', to: '/teammates', fold: 1 },
  { key: 'nav.about', to: '/about', fold: 1 },
]

/** The fourth main item: the prominent Participate button in the header. */
export const participateItem: NavItem = { key: 'nav.submit', to: '/compete' }

export const moreNavItems: NavItem[] = [
  { key: 'nav.brief', to: '/brief' },
  { key: 'nav.cards', to: '/cards' },
  { key: 'nav.docs', to: '/docs' },
  { key: 'nav.cli', to: '/cli' },
  { key: 'nav.resources', to: '/resources' },
  { key: 'nav.faq', to: '/faq' },
  { key: 'nav.announcements', to: '/announcements', divider: true },
]

/** Highest `fold` level, i.e. how many steps the header can fold before only fixed links remain. */
export const maxFold = Math.max(0, ...mainNavItems.map(item => item.fold ?? 0))
