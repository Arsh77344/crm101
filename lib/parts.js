'use client';

// Suppliers photograph a saree in pieces — the pallu, the border, the body, a
// close-up of the weave — and name the file accordingly. Reading that name is
// the difference between a model assembling the real garment and inventing one.
// Order matters: the first match wins per word, and longer phrases are listed
// first so "border body" is not read as plain "body".
const PATTERNS = [
  [/\boverall\b|\bfull[\s_-]?(?:view|length|shot)?\b|\bwhole\b|\bcomplete\b/i, 'Overall'],
  [/\bpallu\b|\bpalla\b|\baanchal\b|\banchal\b/i, 'Pallu'],
  [/\bborder\b|\bkinari\b|\bedge\b/i, 'Border'],
  [/\bblouse\b|\bcholi\b|\bblouse[\s_-]?piece\b/i, 'Blouse'],
  [/\bclose[\s_-]?up\b|\bcloseup\b|\bmacro\b|\bdetail\b|\bzoom\b/i, 'Close-up'],
  [/\bbody\b|\bfield\b|\bground\b|\bbuti\b|\bbooti\b/i, 'Body'],
  [/\bdrape\b|\bworn\b|\bmannequin\b|\bmodel\b/i, 'Draped'],
];

export const PART_OPTIONS = [
  'Overall', 'Pallu', 'Border', 'Body', 'Blouse', 'Close-up', 'Draped', 'Unlabelled',
];

// A name can describe more than one thing: "border body" is the border where it
// meets the body. Keep every part found, in the order the list defines, so the
// label reads the way a person would say it.
export function partFromName(name) {
  const base = String(name || '').replace(/\.[^.]+$/, '');
  // Only the label at the end counts. These names carry the product's own
  // description — "Open Zigzag Border With Mina Leaf Buti" — and matching the
  // whole string tags every photo in the set as a border shot.
  const parts = base.split(/[-_]/);
  const tail = (parts.length > 1 ? parts[parts.length - 1] : base).trim();
  const found = [];
  for (const [re, label] of PATTERNS) {
    if (re.test(tail) && !found.includes(label)) found.push(label);
  }
  if (!found.length) return 'Unlabelled';
  return found.slice(0, 2).join(' + ');
}

// What the set as a whole is missing, so the person can fix it before paying for
// generation rather than after looking at a bad result.
export function partGaps(parts) {
  const all = parts.join(' ').toLowerCase();
  const gaps = [];
  if (!/overall|draped/.test(all)) {
    gaps.push('no overall shot, so the whole garment has to be inferred from the parts');
  }
  if (!/pallu/.test(all)) gaps.push('no pallu');
  if (!/border/.test(all)) gaps.push('no border');
  if (parts.some((p) => p === 'Unlabelled')) {
    gaps.push('some photos are unlabelled — set what they show below');
  }
  return gaps;
}
