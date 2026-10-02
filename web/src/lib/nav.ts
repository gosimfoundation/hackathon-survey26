/** Header navigation: four main destinations, everything else under "More". */
export interface NavItem { key: string; to: string }

export const mainNavItems: NavItem[] = [
  { key: 'nav.start', to: '/start' },
  { key: 'nav.rules', to: '/rules' },
  { key: 'nav.leaderboard', to: '/leaderboard' },
  { key: 'nav.teammates', to: '/teammates' },
]

/** The fourth main item: the prominent Participate button in the header. */
export const participateItem: NavItem = { key: 'nav.submit', to: '/compete' }

export const moreNavItems: NavItem[] = [
  { key: 'nav.brief', to: '/brief' },
  { key: 'nav.cards', to: '/cards' },
  { key: 'nav.docs', to: '/docs' },
  { key: 'nav.resources', to: '/resources' },
  { key: 'nav.faq', to: '/faq' },
  { key: 'nav.announcements', to: '/announcements' },
]
