// One standalone link, then sections that open and close. Seven sections;
// deeper nesting in a 216px rail costs a click to reach anything, which is the
// opposite of what was asked for.
//
// Marketing holds nine, two over the limit the rest of the rail keeps to. The
// occasions calendar had to sit beside the content calendar to make sense, and
// an unreachable page is worse than a long section. Retiring '/generate', which
// the campaign studio supersedes, would bring it back to seven.
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
    ['/social', 'Social', '◑'],
    ['/campaigns', 'Campaigns', '◈'],
    ['/generate', 'Build a campaign', '✧'],
    ['/calendar', 'Content calendar', '▦'],
    ['/occasions', 'Occasions', '❖'],
    ['/performance', 'Performance', '◢'],
    ['/links', 'Tracked links', '⇗'],
    ['/analytics', 'Website analytics', '◴'],
  ]],
  ['Messaging', [
    ['/inbox', 'Inbox', '✉'],
    ['/outreach', 'Outreach', '◉'],
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
