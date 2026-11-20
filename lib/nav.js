// One standalone link, then sections that open and close. Seven sections, none
// longer than seven pages: deeper nesting in a 216px rail costs a click to reach
// anything, which is the opposite of what was asked for.
export const HOME = ['/', 'Dashboard', '◉'];

export const NAV = [
  ['Catalogue', [
    ['/products', 'Products', '▣'],
    ['/collections', 'Collections', '❏'],
    ['/launch', 'Product launch', '✦'],
    ['/looks', 'Look library', '◇'],
  ]],
  ['Sales', [
    ['/orders', 'Orders', '⊞'],
    ['/showrooms', 'Showrooms', '◫'],
    ['/pipeline', 'Pipeline', '⇄'],
    ['/contacts', 'Contacts', '◐'],
    ['/companies', 'Companies', '⌂'],
    ['/activities', 'Activities', '✎'],
    ['/journey', 'Customer journey', '◎'],
  ]],
  ['Fulfilment', [
    ['/shipments', 'Shipments', '➤'],
    ['/payments', 'Payments', '₹'],
    ['/returns', 'Returns', '↩'],
  ]],
  ['Marketing', [
    ['/studio', 'Campaign studio', '✦'],
    ['/campaigns', 'Campaigns', '◈'],
    ['/generate', 'Build a campaign', '✧'],
    ['/calendar', 'Content calendar', '▦'],
    ['/performance', 'Performance', '◢'],
    ['/links', 'Tracked links', '⇗'],
    ['/analytics', 'Website analytics', '◴'],
  ]],
  ['Messaging', [
    ['/templates', 'Message templates', '▤'],
    ['/broadcasts', 'Broadcasts', '◉'],
    ['/consent', 'Consent centre', '⚖'],
  ]],
  ['Money', [
    ['/brands', 'Brand partners', '◧'],
    ['/payables', 'What you owe', '₹'],
    ['/suppliers', 'Service vendors', '⚒'],
    ['/expenses', 'Expenses', '⊟'],
    ['/finance', 'Profit & loss', '◪'],
  ]],
  ['Workspace', [
    ['/agents', 'Department agents', '✦'],
    ['/tasks', 'Tasks', '✓'],
    ['/automations', 'Automations', '⟳'],
    ['/integrations', 'Integrations', '⚯'],
    ['/team', 'Team & roles', '☰'],
    ['/settings', 'Settings', '⚙'],
  ]],
];

// Which section a path sits in, so the right one is open on arrival.
export function sectionOf(here) {
  const hit = NAV.find(([, items]) => items.some(([href]) => here.startsWith(href)));
  return hit ? hit[0] : null;
}

// Every page, flat, so the search can jump to one by name.
export const PAGES = [
  { href: HOME[0], label: HOME[1], group: 'Workspace' },
  ...NAV.flatMap(([group, items]) => items.map(([href, label]) => ({ href, label, group }))),
];
