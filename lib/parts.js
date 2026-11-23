'use client';

// Suppliers photograph an article in pieces and name the file accordingly —
// the pallu, the border, the clasp, a macro of the weave. Reading that name is
// the difference between a model assembling the real thing and inventing one.
//
// What those pieces are called depends on what the article is, so each kind
// carries its own labels and its own filename patterns. Sarees are what the
// brand sells today; the others are first drafts for when it sells them.
//
// THE LABELS HERE ARE A CONTRACT with the kinds in
// supabase/functions/launch-assist/index.ts, which holds what each label MEANS.
// A label offered here that the function does not know is explained to the
// model as "unlabelled" rather than failing, but it is still drift —
// qa/parts.py checks the two lists against each other.

const SAREE = {
  match: /saree|sari|lehenga|dupatta/i,
  options: ['Overall', 'Pallu', 'Border', 'Body', 'Blouse', 'Close-up', 'Draped', 'Unlabelled'],
  // Order matters: the first match wins per word, and longer phrases are
  // listed first so "border body" is not read as plain "body".
  patterns: [
    [/\boverall\b|\bfull[\s_-]?(?:view|length|shot)?\b|\bwhole\b|\bcomplete\b/i, 'Overall'],
    [/\bpallu\b|\bpalla\b|\baanchal\b|\banchal\b/i, 'Pallu'],
    [/\bborder\b|\bkinari\b|\bedge\b/i, 'Border'],
    [/\bblouse\b|\bcholi\b|\bblouse[\s_-]?piece\b/i, 'Blouse'],
    [/\bclose[\s_-]?up\b|\bcloseup\b|\bmacro\b|\bdetail\b|\bzoom\b/i, 'Close-up'],
    [/\bbody\b|\bfield\b|\bground\b|\bbuti\b|\bbooti\b/i, 'Body'],
    [/\bdrape\b|\bworn\b|\bmannequin\b|\bmodel\b/i, 'Draped'],
  ],
  // What the set as a whole is missing, so it can be fixed before paying for
  // generation rather than after looking at a bad result.
  wants: [
    [/overall|draped/, 'no overall shot, so the whole garment has to be inferred from the parts'],
    [/pallu/, 'no pallu'],
    [/border/, 'no border'],
  ],
};

const SHAWL = {
  match: /shawl|stole|pashmina|wrap/i,
  draft: true,
  options: ['Overall', 'Border', 'Body', 'Palla', 'Close-up', 'Draped', 'Unlabelled'],
  patterns: [
    [/\boverall\b|\bfull[\s_-]?(?:view|length|shot)?\b|\bwhole\b|\bopen(?:ed)?\b/i, 'Overall'],
    [/\bpalla\b|\bpallu\b|\bend[\s_-]?panel\b/i, 'Palla'],
    [/\bborder\b|\bhashiya\b|\bedge\b/i, 'Border'],
    [/\bclose[\s_-]?up\b|\bcloseup\b|\bmacro\b|\bdetail\b|\bzoom\b|\bsozni\b|\bkani\b/i, 'Close-up'],
    [/\bbody\b|\bfield\b|\bground\b/i, 'Body'],
    [/\bdrape\b|\bworn\b|\bmannequin\b|\bmodel\b/i, 'Draped'],
  ],
  wants: [
    [/overall|draped/, 'no overall shot, so the whole shawl has to be inferred from the parts'],
    [/border/, 'no border'],
  ],
};

const JEWELLERY = {
  match: /jewel|necklace|earring|bangle|bracelet|ring|jhumka|pendant|chain/i,
  draft: true,
  options: ['Overall', 'Detail', 'Clasp', 'Reverse', 'Close-up', 'Worn', 'Unlabelled'],
  patterns: [
    [/\boverall\b|\bfull\b|\bwhole\b|\bcomplete\b/i, 'Overall'],
    [/\bclasp\b|\bhook\b|\bfasten(?:ing|er)?\b|\block\b/i, 'Clasp'],
    [/\breverse\b|\bback\b|\bhallmark\b|\bstamp\b/i, 'Reverse'],
    [/\bclose[\s_-]?up\b|\bcloseup\b|\bmacro\b|\bzoom\b/i, 'Close-up'],
    [/\bdetail\b|\bsetting\b|\bstone\b|\bmeena\b|\bkundan\b|\bpolki\b/i, 'Detail'],
    [/\bworn\b|\bmodel\b|\bneck\b|\bear\b|\bwrist\b/i, 'Worn'],
  ],
  wants: [
    [/overall/, 'no overall shot, so the proportions have to be inferred'],
    [/worn/, 'nothing worn, so there is no sense of scale'],
  ],
};

// Anything with no entry yet. Invents no vocabulary it does not know, because a
// wrong part name is worse than no part name.
const GENERIC = {
  match: null,
  options: ['Overall', 'Detail', 'Close-up', 'Worn', 'Unlabelled'],
  patterns: [
    [/\boverall\b|\bfull\b|\bwhole\b|\bcomplete\b/i, 'Overall'],
    [/\bclose[\s_-]?up\b|\bcloseup\b|\bmacro\b|\bzoom\b/i, 'Close-up'],
    [/\bdetail\b|\bpart\b/i, 'Detail'],
    [/\bworn\b|\bmodel\b|\bin[\s_-]?use\b/i, 'Worn'],
  ],
  wants: [
    [/overall/, 'no overall shot, so the proportions have to be inferred'],
  ],
};

export const KINDS = [SAREE, SHAWL, JEWELLERY];

// Matched on the owner's own category text, so "Banarasi Saree", "Cotton Saree"
// and "saree" all land on the same entry. Mirrors kindOf() in launch-assist.
export function kindFor(piece) {
  const hay = `${piece?.category ?? ''} ${piece?.fabric ?? ''}`.toLowerCase();
  return KINDS.find((k) => k.match.test(hay)) || GENERIC;
}

export function partOptions(piece) {
  return kindFor(piece).options;
}

// A name can describe more than one thing: "border body" is the border where it
// meets the body. Keep every part found, in the order the list defines, so the
// label reads the way a person would say it.
export function partFromName(name, piece) {
  const kind = kindFor(piece);
  const base = String(name || '').replace(/\.[^.]+$/, '');
  // Only the label at the end counts. These names carry the product's own
  // description — "Open Zigzag Border With Mina Leaf Buti" — and matching the
  // whole string tags every photo in the set as a border shot.
  const parts = base.split(/[-_]/);
  const tail = (parts.length > 1 ? parts[parts.length - 1] : base).trim();
  const found = [];
  for (const [re, label] of kind.patterns) {
    if (re.test(tail) && !found.includes(label)) found.push(label);
  }
  if (!found.length) return 'Unlabelled';
  return found.slice(0, 2).join(' + ');
}

export function partGaps(parts, piece) {
  const kind = kindFor(piece);
  const all = parts.join(' ').toLowerCase();
  const gaps = [];
  for (const [re, said] of kind.wants) {
    if (!re.test(all)) gaps.push(said);
  }
  if (parts.some((p) => p === 'Unlabelled')) {
    gaps.push('some photos are unlabelled — set what they show below');
  }
  return gaps;
}
