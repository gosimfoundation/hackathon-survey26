/** Header navigation: the main destinations (ending with About), everything else under "More". */
/** `wide`: in the header row only from 1280px; narrower desktop headers list it under More instead. */
export interface NavItem { key: string; to: string; wide?: boolean }

export const mainNavItems: NavItem[] = [
  { key: 'nav.start', to: '/start' },
  { key: 'nav.rules', to: '/rules' },
  { key: 'nav.leaderboard', to: '/leaderboard' },
  { key: 'nav.teammates', to: '/teammates', wide: true },
  { key: 'nav.about', to: '/about', wide: true },
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
