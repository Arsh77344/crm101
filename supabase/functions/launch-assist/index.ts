import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { ...CORS, "Content-Type": "application/json" } });

const KEYS: Record<string, string> = {
  openai: Deno.env.get("OPENAI_API_KEY") ?? "",
  gemini: Deno.env.get("GEMINI_API_KEY") ?? "",
  anthropic: Deno.env.get("ANTHROPIC_API_KEY") ?? "",
  groq: Deno.env.get("GROQ_API_KEY") ?? "",
  nvidia: Deno.env.get("NVIDIA_API_KEY") ?? "",
};
const MODELS: Record<string, string> = {
  openai: Deno.env.get("OPENAI_MODEL") || "gpt-4o",
  gemini: Deno.env.get("GEMINI_MODEL") || "gemini-3.8-flash",
  anthropic: Deno.env.get("ANTHROPIC_MODEL") || "claude-sonnet-5-5",
  groq: Deno.env.get("GROQ_MODEL") || "qwen/qwen3.8-27b",
  // Checked against the key's own catalogue: this one answers in under a second
  // with no reasoning tokens. The nemotron models work too but spend 1500+
  // tokens thinking before they answer, and mistral-large never finishes.
  nvidia: Deno.env.get("NVIDIA_MODEL") || "minimaxai/minimax-m3.1-flash",
};
const GROQ_SEARCH = Deno.env.get("GROQ_SEARCH_MODEL") || "groq/compound";
const GROQ_MAX = Math.max(256, Number(Deno.env.get("GROQ_MAX_TOKENS") || 900));
const IMAGE_MODEL = Deno.env.get("GEMINI_IMAGE_MODEL") || "gemini-nano-banana-2.1";
// The check reads two photographs closely and decides whether a customer would
// feel misled. That is worth a stronger model than the writing steps use.
const CHECK_MODEL = Deno.env.get("GEMINI_CHECK_MODEL") || Deno.env.get("GEMINI_MODEL")
  || "gemini-3.8-flash";
const LABEL: Record<string, string> = {
  openai: "ChatGPT", gemini: "Gemini", anthropic: "Claude", groq: "Groq", nvidia: "NVIDIA",
};
const SECRET: Record<string, string> = {
  openai: "OPENAI_API_KEY", gemini: "GEMINI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY", groq: "GROQ_API_KEY", nvidia: "NVIDIA_API_KEY",
};
const PROVIDERS = ["openai", "gemini", "anthropic", "groq", "nvidia"];

// A supplier usually sends crops, not a whole garment: the pallu in one frame, the
// border in another, a macro of the field. Up to this many go to the model in one
// call, in the order the owner uploaded them, each named by its kind's part list.
const MAX_SOURCES = 4;

// What differs between the kinds of article the brand sells. Everything else in
// this file is about photography and holds whatever is in front of the camera.
// Sarees are what is sold today; the other entries are first drafts, written to
// be corrected by someone who knows the article, not to be trusted as they are.
// Adding a kind is adding an entry here.
type Kind = {
  whole: string;        // what one of them is called
  parts: Record<string, string>;  // what a supplied photograph can be of
  layout: string;       // the ordinary arrangement, when no photo shows the whole
  copy: string[];       // what must be reproduced exactly
  holder: string;       // what it is displayed on when nobody is wearing it
  flat: string;         // how it lies for a flat study
  angles: string[];     // the camera positions worth shooting
  draft?: boolean;      // true where the vocabulary has not been checked by the owner
};

const KINDS: Record<string, Kind> = {
  saree: {
    whole: "saree",
    parts: {
      Overall: "the whole piece laid out or draped, so the proportions and the layout are visible",
      Pallu: "the pallu \u2014 the decorated end that falls over the shoulder",
      Border: "the border running along the edge",
      Body: "the body or field of the piece, with its repeating motif",
      Blouse: "the blouse piece that comes with it",
      "Close-up": "a close macro of the weave, for texture and thread colour only, not proportion",
      Draped: "the piece draped or worn, for shape",
    },
    layout: "the field carrying the repeating motif, the border along the edges, the pallu at one end",
    copy: [
      "the colour and its saturation, including how it shifts between the body and the border",
      "the weave, the thread, the sheen and the texture at the scale the photographs show",
      "the border: its width relative to the garment, its pattern, and where it runs",
      "every motif: its shape, its size, its spacing and where it sits",
      "the pallu: its pattern and how it differs from the body",
      "anything that comes with it, such as a blouse piece, as photographed",
    ],
    holder: "a plain matte dress form in a single neutral colour, faceless and without hair, "
      + "standing on its stand, the kind a shop uses",
    flat: "unfolded along the surface and allowed to lie the way heavy silk lies, in a few soft "
      + "natural folds rather than pressed flat, so its length reads across the frame and the "
      + "border runs with it. Arrange it so three things are readable in one photograph: the "
      + "field of the cloth, the border along its edge, and the pallu",
    angles: [
      "Straight on from the front, the whole piece square to camera.",
      "Turned about forty-five degrees, so the drape and the side of the fall read as depth.",
      "Full profile from the side, showing how it hangs along the body.",
      "From behind, showing the back and the fall of the pallu.",
      "A close frame on the border and the pallu, filling most of the image with the weave.",
    ],
  },
  shawl: {
    whole: "shawl",
    draft: true,
    parts: {
      Overall: "the whole shawl opened out, so its proportions and layout are visible",
      Border: "the border running along the edge",
      Body: "the field of the shawl, with its ground and any repeating motif",
      Palla: "the decorated end panel",
      "Close-up": "a close macro of the weave or the embroidery, for texture only, not proportion",
      Draped: "the shawl worn over the shoulders, for shape and fall",
    },
    layout: "the field carrying the ground and any motif, the border along the edges, "
      + "the decorated panels at the ends",
    copy: [
      "the colour and its saturation, including how it shifts between the field and the border",
      "the weave or embroidery, the thread, and the texture at the scale the photographs show",
      "the border: its width relative to the shawl, its pattern, and where it runs",
      "every motif: its shape, its size, its spacing and where it sits",
      "the fringe or finish at the ends, exactly as photographed",
    ],
    holder: "a plain matte dress form in a single neutral colour, faceless and without hair, "
      + "standing on its stand",
    flat: "opened out on the surface with one corner turned back, so the field, the border and "
      + "the end panel are all readable in one photograph",
    angles: [
      "Straight on, the whole shawl opened out and square to camera.",
      "Turned about forty-five degrees, the fabric falling into soft folds.",
      "Worn over the shoulders, three-quarter length, showing how it falls.",
      "A close frame on the border and the end panel, filling most of the image.",
    ],
  },
  jewellery: {
    whole: "piece of jewellery",
    draft: true,
    parts: {
      Overall: "the whole piece, so its proportions and how it sits are visible",
      Detail: "a close frame on the setting, the stones or the metalwork",
      Clasp: "the clasp, the hook or the fastening",
      Reverse: "the back of the piece, showing the finish and any hallmark",
      "Close-up": "a close macro of the surface, for metal colour and stone clarity only",
      Worn: "the piece worn, for scale against a body",
    },
    layout: "the central element with whatever hangs or extends from it, in the proportion "
      + "the photographs show",
    copy: [
      "the colour of the metal and its finish, polished, matte or oxidised",
      "every stone: its colour, its cut, its size relative to the piece, and where it sits",
      "the setting and the metalwork at the scale the photographs show",
      "the length, the drop and the proportion of each element to the others",
      "the clasp or fastening, as photographed",
    ],
    holder: "a plain neutral bust, stand or tray of the kind a jeweller uses, with nothing "
      + "else on it",
    flat: "laid on the surface and arranged so its full length and every element read at once, "
      + "with any chain falling in a natural curve rather than pulled straight",
    angles: [
      "Straight on, the whole piece square to camera and lit to show the metal.",
      "A close frame on the central element, filling most of the image.",
      "Turned slightly, so the depth of the setting and the stones read.",
      "Worn, three-quarter, for scale against a body.",
    ],
  },
};

// Anything the brand sells that has no entry yet. Deliberately plain: it says
// what is true of every article and invents no vocabulary for one it does not
// know, because a wrong part name is worse than no part name.
const GENERIC: Kind = {
  whole: "piece",
  parts: {
    Overall: "the whole piece, so its proportions and layout are visible",
    Detail: "a close frame on one part of it",
    "Close-up": "a close macro of the surface, for texture and colour only, not proportion",
    Worn: "the piece worn or in use, for scale and shape",
  },
  layout: "the arrangement the photographs show, and no more than they show",
  copy: [
    "the colour and its saturation, and how it shifts across the piece",
    "the material, its texture and its finish at the scale the photographs show",
    "every pattern or decorative element: its shape, its size, its spacing and where it sits",
    "the proportion of each part of the piece to the others",
    "anything that comes with it, as photographed",
  ],
  holder: "a plain neutral stand or form of the kind a shop uses, with nothing else on it",
  flat: "laid out on the surface so that as much of it as possible is readable in one photograph",
  angles: [
    "Straight on, the whole piece square to camera.",
    "Turned about forty-five degrees, so its depth reads.",
    "A close frame on its most distinctive part, filling most of the image.",
    "From another side, showing what the first frame could not.",
  ],
};

// Matched loosely on the owner's own category text, so "Banarasi Saree",
// "Cotton Saree" and "saree" all land on the same entry.
function kindOf(piece: any): Kind {
  const hay = `${piece?.category ?? ""} ${piece?.fabric ?? ""}`.toLowerCase();
  if (/saree|sari|lehenga|dupatta/.test(hay)) return KINDS.saree;
  if (/shawl|stole|pashmina|wrap/.test(hay)) return KINDS.shawl;
  if (/jewel|necklace|earring|bangle|bracelet|ring|jhumka|pendant|chain/.test(hay)) {
    return KINDS.jewellery;
  }
  return GENERIC;
}

function parseJson(text: string): any {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const raw = fenced ? fenced[1] : text;
  const a = raw.indexOf("{"), b = raw.lastIndexOf("}");
  if (a === -1 || b === -1) throw new Error("The model did not return JSON.");
  return JSON.parse(raw.slice(a, b + 1));
}

function b64(buf: Uint8Array) {
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

async function asInline(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not read the photo (${res.status}).`);
  const buf = new Uint8Array(await res.arrayBuffer());
  if (buf.length > 4_000_000) {
    throw new Error("That photo is too large to send to the model. Re-upload it; photos are "
      + "shrunk on upload now, so an older full-size one needs replacing.");
  }
  return { mime: res.headers.get("content-type") || "image/jpeg", data: b64(buf) };
}

async function brandContext(admin: any) {
  const { data } = await admin.from("settings").select("setting_key,setting_value");
  const s: Record<string, string> = {};
  (data ?? []).forEach((r: any) => { s[r.setting_key] = r.setting_value ?? ""; });
  const lines = [
    s.brand_name ? `The brand is called ${s.brand_name}.` : "The brand's name has not been set yet, so never invent one.",
    s.brand_sells ? `It sells: ${s.brand_sells}` : "",
    s.brand_audience ? `Its customers: ${s.brand_audience}` : "",
    s.brand_voice ? `How it writes: ${s.brand_voice}` : "",
  ].filter(Boolean);
  return { text: lines.join("\n"), settings: s };
}

const NEVER = `Never invent a fact that is not given to you. If you do not know something, leave it out.
Do not name a material, a technique, a place or a person unless it appears in the notes or is plainly
visible in the photographs.`;

// What each supplied photograph is of, in the order they are attached. Without this
// the model treats a macro of a border as the whole piece and the result is a saree
// made entirely of border.
const UNLABELLED = "an unlabelled photograph — work out which part of the piece it shows";

function partLines(parts: unknown, n: number, kind: Kind) {
  const list = Array.isArray(parts) ? parts : [];
  const rows: string[] = [];
  for (let i = 0; i < n; i++) {
    const raw = String(list[i] ?? "Unlabelled").trim() || "Unlabelled";
    // A label may be combined, e.g. "Border + Body"; explain each half it knows.
    const notes = raw.split("+").map((x) => x.trim())
      .map((x) => kind.parts[x] ?? (x === "Unlabelled" ? UNLABELLED : ""))
      .filter(Boolean).join(", and ");
    rows.push(`Photograph ${i + 1}: ${raw}${notes ? ` — ${notes}` : ""}`);
  }
  return rows.join("\n");
}

function partsBlock(parts: unknown, n: number, kind: Kind) {
  if (n <= 1) return "";
  const labels = (Array.isArray(parts) ? parts : []).slice(0, n)
    .map((x) => String(x ?? "").trim());
  const hasOverall = labels.some((x) => /overall|draped/i.test(x));
  return `\n\nAll ${n} photographs are of ONE single ${kind.whole}, not ${n} different pieces. They are
different parts of it, shot separately:
${partLines(parts, n, kind)}

Put them together into the one garment they came from. A photograph of the border tells you what
the border looks like and nothing about the rest; a macro tells you the thread and the texture and
nothing about scale. Keep every part exactly as it was photographed, in the place on the garment
where that part belongs.${hasOverall
    ? ""
    : `\n\nNo photograph shows the whole piece, so its overall layout has to be inferred: assume the
ordinary arrangement for this kind of article — ${kind.layout} — and build it from the parts you
were given. Do not invent a motif, a colour or a detail that is in none of the photographs.`}`;
}

const COPY_RULES = (b: string, hasMarket: boolean, tight: boolean) => `${b}

You are writing a product listing from photographs of one real piece.\n${NEVER}
Return only JSON:
{"title": string, "description": string, "highlights": string[4], "tags": string[6],
 "observed": {"category": string, "fabric": string, "colour": string, "weave_or_motif": string},
 "uncertain": string[]}
The title is under 70 characters. The description is ${tight ? "50 to 80" : "60 to 110"} words.
"observed" is only what the photographs actually show. A material cannot be identified from a
photograph with certainty, so give your best reading and list anything you are unsure of in
"uncertain". Use "" for any field the photographs do not show clearly rather than guessing.
The description must not state a material or technique that is listed in "uncertain".${
  tight ? `\nKeep every highlight to a few words. Completing the JSON matters more than length.` : ""}${
  hasMarket ? `\n\nYou are also given what comparable pieces are selling for elsewhere. Use it only to judge how
plainly or richly to write and which details buyers in this bracket care about. Do not mention
prices, competitors, sellers or "comparable pieces" anywhere in the description, and do not
borrow their wording or copy their claims about materials.` : ""}`;

const PRICE_RULES = (b: string, tight: boolean) => `${b}\n\nYou research what comparable pieces sell for online right now.
Search for items of the same material, technique and quality. Prefer the brand's own market.
Return only JSON: {"suggested": number, "low": number, "high": number, "currency": "INR",
"reasoning": string, "comparables": [{"name": string, "price": number, "seller": string, "url": string}]}
Give ${tight ? "three" : "at least three"} comparables with real working links. Prices as plain numbers.${
  tight ? ` Keep "reasoning" to one sentence.` : ""}`;

const CAMPAIGN_RULES = (b: string) => `${b}\n\nYou plan a marketing campaign for specific pieces.\n${NEVER}
Write posts a small team can actually shoot and publish. Each post names what to show, then the caption.
Vary the posts: do not write the same idea four ways. Mix close detail, the making, styling, and the offer.
Captions are 20 to 60 words, in the brand's voice, with a clear next step.
Return only JSON:
{"campaign_name": string, "objective": string, "brief": string, "offer": string,
 "posts": [{"channel": string, "title": string, "body": string, "hashtags": string,
            "day_offset": number, "product": string}]}
"title" is the shot direction. "body" is the caption. "day_offset" counts days from the start, from 0.`;

const LOOK_RULES = (known: string[]) => `You are a photographer breaking down one reference
photograph so a similar shot could be directed from your notes alone, without seeing it again.
Describe only what is in the frame. Do not guess a brand, a location name, or a person's identity,
and never describe the identity or face of the person in it beyond what a casting note would say.
Return only JSON:
{"framing": string, "subject": string, "pose": string, "setting": string,
 "light": string, "palette": string, "mood": string, "avoid": string,
 "name": string, "summary": string, "category": string}
"category" is what kind of reference this is, in two or three words, so a growing library can be
sorted by it. Judge it by what the photograph is useful FOR, not by what happens to be in it: a
room photographed for its wall and light is a location reference even if someone is standing in it.
${known.length
  ? `These categories are already in use in this library:\n${known.map((c) => `- ${c}`).join("\n")}
Reuse one of them word for word whenever it fits, even loosely. Coin a new one only when none of
them could reasonably cover this photograph, because two names for one idea make the library
impossible to sort.`
  : `Nothing is categorised yet, so choose a plain, reusable name that would still make sense as
the hundredth reference in the library — the kind of word a photographer would use for a whole
shelf of references, not a description of this one picture.`}
"framing" is shot length, orientation and where the subject sits in frame.
"pose" is body, arms, head and gaze.
"setting" is the kind of place and what is behind the subject, not a named place.
"light" is direction, hardness and time of day.
"avoid" is what would make a recreation look wrong or cheap.
"name" is a short memorable label for this look, under five words.
"summary" is one plain sentence under twenty words naming what is in the frame, the way one person
would describe the photograph to another: what the subject is wearing, what they are doing, and
where. Lead with whatever makes this shot recognisable at a glance — the cigarette, the petals, the
boats — not with the mood or the lighting. For example: "Teal silk saree, seated on sandstone steps
with a cigarette, carved doorway behind."`;

const FIDELITY = (kind: Kind) => `The photographs show one real ${kind.whole} that a customer will
actually be sent, and they will hold this image against the parcel. Treat it as a thing to be
copied, not designed.

Copy exactly, from the photographs:
${kind.copy.map((c) => `- ${c}`).join("\n")}

Do not redraw a detail "in the same style", do not regularise spacing, do not tidy a pattern, do not
enrich or simplify it, do not add or remove decoration, and do not shift the colour warmer, cooler
or more saturated. Where a part of it is not in any photograph, leave it plain rather than inventing
it. An invented detail makes this image useless, so when in doubt reproduce what is photographed and
nothing more.
No text, no watermark, no logo, no brand name anywhere in the image.`;

// One run is one shoot. The owner's non-editorial shots share a set, so the
// clean, mannequin, model and detail frames sit together on a page instead of
// looking like four shoots of the same piece. Similar, not identical: the
// camera and the placement move, the room does not.
const SETS: Record<string, string> = {
  stone: "a warm off-white plaster wall with a pale sand-coloured floor, daylight from one side",
  linen: "a smooth pale oat-coloured linen backdrop, even diffused light, no visible seam",
  grey: "a seamless light grey studio backdrop with a soft gradient, even studio light",
  warm: "a soft ivory backdrop with a gentle warm cast, light falling from the upper left",
};
const SET_NAME: Record<string, string> = {
  stone: "Warm stone", linen: "Oat linen", grey: "Studio grey", warm: "Soft ivory",
};

const PROPS: string[] = [
  "folded once over the back of a simple wooden chair, the fall of it reaching the floor",
  "laid along a low stone ledge, one end spilling over the edge",
  "draped over a cane stool, the pallu hanging down one side",
  "spread across a linen-covered table, gathered into soft folds at one corner",
  "folded in a neat stack on a plain bench, the border showing along the top edge",
  "hung from a plain wooden rail, falling straight with one corner turned back",
];

function propFor(i: number) {
  return PROPS[i % PROPS.length];
}

// The set a look implies, in the same words a set is written in. The editorial
// frames are built from the look's own breakdown; these lines let the studio
// stills stand in the same place, so a page of them reads as one shoot rather
// than a location shoot next to a studio one.
function lookSet(look: any) {
  const parts = [look?.setting, look?.light, look?.palette]
    .map((x: unknown) => String(x ?? "").trim()).filter(Boolean);
  return parts.length ? parts.join(", ") : "";
}

// Consistency across a run comes from a picture, not a paragraph. Once the
// first frame exists it is attached to every later one, and this says what to
// take from it. The distinction matters: the place comes from the anchor, the
// garment always comes from the owner's own photographs, because the anchor is
// itself generated and any drift in it must not be copied forward.
function anchorBlock(mode: string) {
  const change = mode === "Model"
    ? `Keep the same woman, the same styling and the same hair as that frame. Change the camera, `
      + `her position in the scene and her pose.`
    : mode === "Mannequin"
      ? `Put the dress form in that same place. There is no person in this frame.`
      : `This frame is a still life: no person and no mannequin. Put the cloth down somewhere in `
        + `that same place \u2014 on a step, a ledge, a wall, whatever that scene already has.`;
  return `\n\nThe FINAL photograph attached is another frame from this same shoot, already taken. `
    + `This frame must look like it was taken minutes later in the same place: the same location, `
    + `the same wall, floor and props, the same palette, the same time of day. The light may shift `
    + `a little and the camera may move, but a viewer putting the two side by side must see one `
    + `shoot. ${change}\n\nTake the PLACE from that final photograph and the GARMENT from the `
    + `owner's own photographs above it. If the garment in that final photograph differs at all `
    + `from the owner's photographs, the owner's photographs are right and that one is wrong \u2014 `
    + `never copy the garment from it.`;
}

function setBlock(line: string, mode: string, cutoutOnWhite: boolean, fromLook = false) {
  if (!line) return "";
  if (mode === "Clean" && cutoutOnWhite) {
    return `\n\nBackground: a plain pure-white sweep, because this frame is a catalogue cut-out `
      + `for a marketplace listing. The garment lies flat and square to camera, evenly lit, with `
      + `only the faintest contact shadow. No props, no furniture, nothing else in the frame.`;
  }
  if (fromLook) {
    // What stands in that place depends on the shot. Telling a mannequin frame
    // it is a still life of the cloth is how the dress form goes missing.
    const who = mode === "Model"
      ? `The woman wearing it stands in that place.`
      : mode === "Mannequin"
        ? `There is no person in this frame: the dress form stands in that place, with the `
          + `garment draped on it.`
        : `There is no person and no mannequin in this frame — it is a still life of the cloth `
          + `in that place.`;
    return `\n\nThis frame belongs to one shoot with the editorial frames being made in this run, `
      + `and must look like it was taken in the same place on the same day. That place is `
      + `${line}. Keep the same background, the same palette and the same quality and direction `
      + `of light. ${who} Use a quiet corner of it rather than the full scene, and let the `
      + `background fall soft and out of focus behind the subject. Do not restage it as a white `
      + `studio.`;
  }
  return `\n\nThis frame belongs to one shoot with the others being made in this run. `
    + `The set for all of them is ${line}. Keep that same wall, floor, palette and quality of `
    + `light. Move the camera, the distance and where the piece sits in the frame so the frames `
    + `are not copies of each other, but do not change the room, the colour of the background or `
    + `the direction of the light.`;
}

const SHOT = (kind: Kind): Record<string, string> => {
  const F = FIDELITY(kind);
  return {
    Clean: `${F}\nA styled studio still of the ${kind.whole} itself, no person and no mannequin:
the whole of it in frame, arranged so its most distinctive parts are readable. Shot like a catalogue
photographer would shoot it — one soft key light with a gentle falloff, a soft shadow beneath it so
it sits on the surface rather than floating, no harsh highlight.`,
    Mannequin: `${F}\nDisplayed on ${kind.holder}, visibly there and standing on its stand. The
piece is on that form and takes its shape from it, fully supported. It must not float, hover or hold
a shape with nothing inside it, and there must be no empty gap where a body should be. Show the
stand. Full length in frame, soft lighting; the set described below decides where it stands.`,
    Model: `${F}\nWorn by a woman in a relaxed, natural pose, full length in frame, soft daylight.
Unless the set or the casting note below says otherwise, put her against a plain neutral studio
background. Keep the ${kind.whole} the subject of the photograph.`,
    Fabric: `${F}\nThe ${kind.whole} itself, laid out and nobody wearing it: no person, no
mannequin, no form. It is ${kind.flat}. Shot slightly from above, the whole arrangement in frame,
one soft key light raking low across it so the texture catches, with a gentle shadow where it meets
the surface. This is a study of the thing itself, so it fills most of the frame and the setting is
only the ground it rests on.`,
    Detail: `${F}\nA close macro filling the frame: whichever part the photographs show best. Close
enough that the material, the making and the texture read clearly, with a shallow depth of field so
the far side softens. One soft light raking across it, so the texture catches. This frame exists to
prove what the thing is made of, so every part of it must be what the photographs show.`,
  };
};

// Free-text direction from the owner, for this shoot only. It is fenced so it can
// steer the scene without ever being able to restyle the garment — that is the one
// thing a customer checks the photograph against when the parcel arrives.
function tweakBlock(tweak: unknown) {
  const t = String(tweak ?? "").trim().slice(0, 700);
  if (!t) return "";
  return `\n\nThe owner asked for these changes to this particular shot:\n${t}\n\n`
    + `Apply them to the setting, the background, the props, the styling around the garment, the `
    + `mood, the light and the camera. They must not change the garment itself: its colour, weave, `
    + `border and motifs still have to match the photographs exactly. If part of the request would `
    + `alter the garment, ignore that part and carry out the rest. Still no text, logo or watermark `
    + `anywhere in the image.`;
}

function angleFor(i: number, given: string[] | undefined, kind: Kind) {
  if (given && given[i]) return given[i];
  return kind.angles[i % kind.angles.length];
}

function lookBrief(look: any) {
  return [
    look.framing && `Framing: ${look.framing}`,
    look.subject && `Subject: ${look.subject}`,
    look.pose && `Pose: ${look.pose}`,
    look.setting && `Setting: ${look.setting}`,
    look.light && `Light: ${look.light}`,
    look.palette && `Palette: ${look.palette}`,
    look.mood && `Mood: ${look.mood}`,
    look.avoid && `What would make it look wrong: ${look.avoid}`,
    look.notes && `From the owner: ${look.notes}`,
  ].filter(Boolean).join("\n");
}

const FOUND_GUARD = `This reference was photographed by someone else. Take only the general
direction from it: the kind of pose, the quality of the light, the sort of place, the mood.
Do not recreate it. Change the camera angle, the exact location and what is in the background,
the styling around the garment and the arrangement of the frame, so the result is plainly a
different photograph that happens to share a mood. Invent a different woman. Never include text,
a logo, a watermark or anything identifying another brand.`;

const OWN_GUARD = `This reference is the brand's own photograph, so the shot may follow it closely.
Still invent a different woman unless told otherwise.`;

function editorialInstruction(look: any, angleLine: string, piece: any, first: boolean,
                              tweak: unknown, parts: unknown, sourceCount: number, kind: Kind) {
  return [
    FIDELITY(kind),
    partsBlock(parts, sourceCount, kind), "",
    `The ${kind.whole} above is the subject. Place it in a photograph built to this direction:`,
    lookBrief(look) || "No direction recorded for this look.", "",
    look.source === "Own" ? OWN_GUARD : FOUND_GUARD, "",
    first
      ? `Camera: ${angleLine}`
      : `This is a later frame from the same shoot. The final photograph attached is the first `
        + `frame of it — keep the same woman, the same styling, the same location and the same `
        + `light as that one, and keep the garment matched to the other photographs. Change only `
        + `the camera: ${angleLine}`,
    "",
    "Photographic, not illustrated. Natural skin and fabric. No text anywhere in the image.",
    piece?.public_product_name ? `The piece is described as: ${piece.public_product_name}` : "",
  ].filter(Boolean).join("\n") + tweakBlock(tweak);
}

function describe(piece: any, brief: string) {
  return [
    piece?.public_product_name && `Working name: ${piece.public_product_name}`,
    piece?.category && `Category: ${piece.category}`,
    piece?.fabric && `Material: ${piece.fabric}`,
    piece?.colour && `Colour: ${piece.colour}`,
    piece?.weave_or_motif && `Technique or motif: ${piece.weave_or_motif}`,
    piece?.retail_price && `Retail price: ${piece.retail_price}`,
    piece?.description && `Existing description: ${piece.description}`,
    brief && `Must mention: ${brief}`,
  ].filter(Boolean).join("\n");
}

function marketLines(research: any) {
  const rows = (research?.comparables ?? []).slice(0, 6)
    .map((c: any) => `- ${c.name}${c.seller ? ` (${c.seller})` : ""}: ${c.price}`).join("\n");
  if (!rows) return "";
  return `\n\nWhat comparable pieces sell for, found by searching just now:\n${rows}`
    + (research?.suggested ? `\nA sensible asking price looks like ${research.suggested}.` : "");
}

function describeCampaign(p: any) {
  const pieces = (p.products ?? []).map((x: any, i: number) =>
    `${i + 1}. ${[x.public_product_name, x.fabric, x.colour, x.weave_or_motif,
      x.retail_price ? `priced ${x.retail_price}` : ""].filter(Boolean).join(" · ")}`).join("\n");
  return [
    p.collection ? `Collection: ${p.collection.name}${p.collection.description ? ` — ${p.collection.description}` : ""}` : "",
    pieces ? `The pieces:\n${pieces}` : "",
    `Goal: ${p.objective ?? "Sales"}`,
    `Audience: ${p.audience ?? "All"}`,
    `Channels to use: ${(p.channels ?? ["Instagram"]).join(", ")}`,
    `Length: ${p.days ?? 14} days`,
    `How many posts: ${p.post_count ?? 6}`,
    p.budget ? `Budget: ${p.budget}` : "",
    p.offer ? `The offer: ${p.offer}` : "Decide whether an offer helps; if not, return an empty string.",
    p.brief ? `From the owner: ${p.brief}` : "",
  ].filter(Boolean).join("\n");
}

async function openaiChat(system: string, user: string, images: string[] = []) {
  const content: any[] = [{ type: "text", text: user }];
  images.slice(0, MAX_SOURCES).forEach((url) => content.push({ type: "image_url", image_url: { url } }));
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.openai}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.openai, response_format: { type: "json_object" },
      messages: [{ role: "system", content: system }, { role: "user", content }] }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `OpenAI returned ${res.status}.`);
  return { data: parseJson(b.choices[0].message.content), usage: b.usage, model: MODELS.openai };
}

async function openaiSearch(prompt: string) {
  const res = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.openai}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.openai, tools: [{ type: "web_search_preview" }], input: prompt }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `OpenAI returned ${res.status}.`);
  const text = b.output_text ??
    (b.output ?? []).flatMap((o: any) => (o.content ?? []).map((c: any) => c.text ?? "")).join("\n");
  return { data: parseJson(text), usage: b.usage, model: MODELS.openai };
}

async function groqCall(system: string, user: string, images: string[], search: boolean) {
  const model = search ? GROQ_SEARCH : MODELS.groq;
  const content: any[] = [{ type: "text", text: user }];
  for (const url of images.slice(0, 3)) {
    if (/^https:\/\//i.test(url)) {
      content.push({ type: "image_url", image_url: { url } });
    } else {
      const im = await asInline(url);
      content.push({ type: "image_url",
        image_url: { url: `data:${im.mime};base64,${im.data}` } });
    }
  }
  const body: any = {
    model, max_completion_tokens: GROQ_MAX,
    messages: [{ role: "system", content: system },
               { role: "user", content: images.length ? content : user }],
  };
  if (!search) body.response_format = { type: "json_object" };
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.groq}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `Groq returned ${res.status}.`;
    if (/invalid image|image data|unsupported image/i.test(m)) {
      throw new Error(`Groq would not read the photo ("${m}"). It is sent as a link to the stored `
        + `file, so this usually means the format is one Groq does not take — try a JPEG or PNG, `
        + `or read this piece with Gemini, which accepts more formats.`);
    }
    if (/output tokens per minute|OTPM/i.test(m)) {
      throw new Error(`Groq's plan allows fewer output tokens per minute than this asks for `
        + `(currently requesting ${GROQ_MAX}). Lower GROQ_MAX_TOKENS, wait a minute, or add a card `
        + `for the Developer tier. Groq's words: ${m}`);
    }
    if (/tokens per minute|TPM|rate limit|429/i.test(m)) {
      throw new Error(`Groq is rate-limiting this key — wait a minute and try again. ${m}`);
    }
    throw new Error(/decommission|not exist|does not exist|model_not_found/i.test(m)
      ? `${m} Groq retires models often — set GROQ_MODEL (or GROQ_SEARCH_MODEL) to a current one.`
      : m);
  }
  const choice = b.choices?.[0];
  if (choice?.finish_reason === "length") {
    throw new Error(`Groq hit the ${GROQ_MAX}-token output cap before finishing, so the reply was `
      + `incomplete. Raise GROQ_MAX_TOKENS if the plan allows, or use another model for this step.`);
  }
  return { data: parseJson(choice.message.content), usage: b.usage, model };
}

async function geminiCall(prompt: string, images: string[], search: boolean) {
  const parts: any[] = [{ text: prompt }];
  for (const url of images.slice(0, MAX_SOURCES)) {
    const im = await asInline(url);
    parts.push({ inline_data: { mime_type: im.mime, data: im.data } });
  }
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${MODELS.gemini}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({ contents: [{ role: "user", parts }],
        ...(search ? { tools: [{ google_search: {} }] } : {}) }) },
  );
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `Gemini returned ${res.status}.`;
    throw new Error(res.status === 404
      ? `${m} The model name "${MODELS.gemini}" may have been retired — set GEMINI_MODEL to a current one.`
      : m);
  }
  const text = (b.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("\n");
  return { data: parseJson(text), usage: b.usageMetadata, model: MODELS.gemini };
}

async function claudeCall(system: string, user: string, images: string[], search: boolean) {
  const content: any[] = [];
  for (const url of images.slice(0, MAX_SOURCES)) {
    const im = await asInline(url);
    content.push({ type: "image", source: { type: "base64", media_type: im.mime, data: im.data } });
  }
  content.push({ type: "text", text: user });
  const body: any = { model: MODELS.anthropic, max_tokens: 4096, system,
                      messages: [{ role: "user", content }] };
  if (search) body.tools = [{ type: "web_search_20250305", name: "web_search", max_uses: 6 }];
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": KEYS.anthropic, "anthropic-version": "2023-06-01",
               "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Claude returned ${res.status}.`);
  const text = (b.content ?? []).filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n");
  return { data: parseJson(text),
           usage: { prompt_tokens: b.usage?.input_tokens, completion_tokens: b.usage?.output_tokens },
           model: MODELS.anthropic };
}

async function nvidiaCall(system: string, user: string) {
  const res = await fetch("https://integrate.api.nvidia.com/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.nvidia}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.nvidia, response_format: { type: "json_object" },
      messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
  });
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `NVIDIA returned ${res.status}.`;
    throw new Error(/not found|does not exist|invalid model|unknown model/i.test(m)
      ? `${m} NVIDIA's catalogue changes often — set NVIDIA_MODEL to a model id your key can use.`
      : m);
  }
  return { data: parseJson(b.choices[0].message.content), usage: b.usage, model: MODELS.nvidia };
}

async function ask(provider: string, system: string, user: string,
                   images: string[], search: boolean) {
  if (provider === "gemini") return geminiCall(`${system}\n\n${user}`, images, search);
  if (provider === "anthropic") return claudeCall(system, user, images, search);
  if (provider === "groq") return groqCall(system, user, images, search);
  if (provider === "nvidia") return nvidiaCall(system, user);
  return search ? openaiSearch(`${system}\n\n${user}`) : openaiChat(system, user, images);
}

type Inline = { mime: string; data: string };

async function oneImage(instruction: string, sources: Inline[]) {
  const parts: any[] = [{ text: instruction }];
  sources.forEach((im) => parts.push({ inline_data: { mime_type: im.mime, data: im.data } }));
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${IMAGE_MODEL}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({ contents: [{ role: "user", parts }] }) });
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `Gemini returned ${res.status}.`;
    throw new Error(res.status === 404
      ? `${m} The image model "${IMAGE_MODEL}" may have been retired — set GEMINI_IMAGE_MODEL to a current one.`
      : m);
  }
  const out = (b.candidates?.[0]?.content?.parts ?? [])
    .find((p: any) => p.inline_data?.data || p.inlineData?.data);
  if (!out) {
    const said = (b.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join(" ").trim();
    throw new Error(said
      ? `The model returned words instead of an image: ${said.slice(0, 240)}`
      : "The model returned no image and said nothing.");
  }
  const inline = out.inline_data ?? out.inlineData;
  return { data: inline.data as string, mime: (inline.mime_type ?? inline.mimeType ?? "image/png") as string };
}

// A generated photograph is only worth having if the garment in it is the
// garment in the parcel. This reads the two side by side and says where they
// differ, so a wrong one can be thrown away instead of sold from.
const CHECK_RULES = `You are checking a photograph a model generated against photographs of the real
garment, before it is used to sell that garment.

The real garment is in the first photographs. The generated one is the LAST photograph.
Compare only the garment. The background, the pose, the mannequin, the model and the framing are
meant to differ — ignore them completely.

Return only JSON:
{"match": boolean, "confidence": "high" | "medium" | "low", "differences": string[]}

"match" is false if a customer holding the real piece beside this image would feel misled: a
different colour, a border of a different width or pattern, motifs of a different shape, size or
spacing, detail that is not on the real piece, or detail on the real piece that is missing.
List each difference in one short plain sentence, naming the part. An empty list means it matches.
Judge only what the photographs let you see; say "low" confidence rather than guessing.`;

async function checkOne(sources: Inline[], made: Inline, parts: unknown, kind: Kind) {
  const model = CHECK_MODEL;
  const text = `These are photographs of one real ${kind.whole}.${partsBlock(parts, sources.length, kind)}

The last photograph is the generated one. Does the ${kind.whole} in it match the real one?`;
  const payload: any[] = [{ text }];
  [...sources, made].forEach((im) =>
    payload.push({ inline_data: { mime_type: im.mime, data: im.data } }));
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({ contents: [{ role: "user", parts: payload }],
        systemInstruction: { parts: [{ text: CHECK_RULES }] } }) });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Gemini returned ${res.status}.`);
  const said = (b.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("\n");
  const out = parseJson(said);
  return { match: out.match !== false, confidence: out.confidence ?? "low",
           differences: Array.isArray(out.differences) ? out.differences.slice(0, 4) : [] };
}

async function store(admin: any, folder: string, label: string, i: number,
                     made: { data: string; mime: string }, extra: Record<string, unknown>) {
  const ext = made.mime.includes("jpeg") ? "jpg" : "png";
  const path = `generated/${folder}/${label}-${i + 1}.${ext}`;
  const bytes = Uint8Array.from(atob(made.data), (c) => c.charCodeAt(0));
  const up = await admin.storage.from("product-images")
    .upload(path, bytes, { contentType: made.mime, upsert: false });
  if (up.error) throw new Error(up.error.message);
  const pub = admin.storage.from("product-images").getPublicUrl(path);
  return { url: pub.data.publicUrl, path, bytes: bytes.length, ...extra };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = Deno.env.get("SUPABASE_URL")!;
  const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const asUser = createClient(url, anon, {
    global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } } });
  const { data: { user } } = await asUser.auth.getUser();
  if (!user) return json({ error: "Sign in first." }, 401);

  let p: any = {};
  try { p = await req.json(); } catch { /* health */ }
  const action = p.action ?? "health";
  const admin = createClient(url, service);

  if (action === "health") {
    const { settings } = await brandContext(admin);
    return json({
      openai: Boolean(KEYS.openai), gemini: Boolean(KEYS.gemini),
      anthropic: Boolean(KEYS.anthropic), groq: Boolean(KEYS.groq), nvidia: Boolean(KEYS.nvidia),
      models: { ...MODELS, groq_search: GROQ_SEARCH }, groq_max_tokens: GROQ_MAX,
      image_model: IMAGE_MODEL, check_model: CHECK_MODEL,
      sets: Object.keys(SETS).map((id) => ({ id, name: SET_NAME[id], line: SETS[id] })),
      images_ready: Boolean(KEYS.gemini),
      brand_set: Boolean(settings.brand_name && settings.brand_sells),
    });
  }

  const provider = PROVIDERS.includes(p.provider) ? p.provider : "openai";
  if (!KEYS[provider]) {
    return json({ error: `No ${LABEL[provider]} key is set. Add ${SECRET[provider]} to this project's Edge Function secrets.` }, 400);
  }
  const tight = provider === "groq" && GROQ_MAX < 1200;

  const { text: brand, settings } = await brandContext(admin);
  if (!settings.brand_name || !settings.brand_sells) {
    return json({ error: "Fill in the brand name and what it sells on the Settings page first, so nothing gets invented." }, 400);
  }

  const started = await admin.from("ai_runs").insert({
    job_id: p.job_id ?? null, kind: action, provider, status: "Running",
    request: { images: (p.images ?? []).length, products: (p.products ?? []).length,
               mode: p.mode ?? null, count: p.count ?? null, look_id: p.look_id ?? null,
               parts: Array.isArray(p.parts) ? p.parts.slice(0, MAX_SOURCES) : null,
               set_id: p.set_id ?? null, checked: p.check !== false,
               anchored: Boolean(p.anchor_url),
               tweak: String(p.tweak ?? "").trim().slice(0, 700) || null,
               with_market: Boolean(p.research?.comparables?.length) },
  }).select("run_id").maybeSingle();
  const runId = started.data?.run_id;

  try {
    let out;
    const images = p.images ?? [];

    if (action === "look") {
      if (!p.reference_url) return json({ error: "Give the reference image first." }, 400);
      const seen = await admin.from("looks").select("category")
        .not("category", "is", null).limit(300);
      const known = [...new Set((seen.data ?? [])
        .map((r: any) => String(r.category ?? "").trim()).filter(Boolean))].sort();
      out = await ask(provider, LOOK_RULES(known), "Break this reference down.",
                      [p.reference_url], false);
      if (runId) {
        await admin.from("ai_runs").update({ status: "Done", model: out.model, response: out.data })
          .eq("run_id", runId);
      }
      if (p.look_id) {
        const d = out.data || {};
        await admin.from("looks").update({
          framing: d.framing ?? null, subject: d.subject ?? null, pose: d.pose ?? null,
          setting: d.setting ?? null, light: d.light ?? null, palette: d.palette ?? null,
          mood: d.mood ?? null, avoid: d.avoid ?? null, status: "Ready",
          category: String(d.category ?? "").trim().slice(0, 40) || null,
        }).eq("look_id", p.look_id);
      }
      return json({ ok: true, provider, model: out.model, result: out.data });
    }

    if (action === "images") {
      if (!KEYS.gemini) {
        return json({ error: "Generated imagery needs a Gemini key (GEMINI_API_KEY). ChatGPT, Claude, Groq and NVIDIA do not produce images." }, 400);
      }
      const mode = String(p.mode ?? "Clean");
      // Which kind of article this is decides the part names, what must be
      // copied, what it is displayed on and how it lies for a flat study.
      const kind = kindOf(p.piece ?? {});
      const shots = SHOT(kind);
      const wantCheck = p.check !== false;
      const editorial = mode === "Editorial";
      if (!editorial && !shots[mode]) return json({ error: `Unknown imagery style "${mode}".` }, 400);
      if (!images.length) return json({ error: "Upload at least one photo of the piece first." }, 400);

      // A look is loaded whenever one is named. An editorial run needs it; a
      // studio still wants it only when the owner asked for the set to match,
      // so the two kinds of frame come out of the same room.
      const matchLook = String(p.set_id ?? "") === "look";
      let look: any = null;
      if (editorial || (matchLook && p.look_id)) {
        if (editorial && !p.look_id) return json({ error: "Pick a look for an editorial shoot." }, 400);
        const got = await admin.from("looks").select("*").eq("look_id", p.look_id).maybeSingle();
        if (!got.data) return json({ error: "That look no longer exists." }, 400);
        look = got.data;
        if (!lookBrief(look)) {
          return json({ error: `"${look.name}" has not been read yet. Open it and read the reference first.` }, 400);
        }
      }
      if (matchLook && !look) {
        return json({ error: "Pick a look to match, or choose one of the studio sets." }, 400);
      }

      const setLine = matchLook ? lookSet(look) : (SETS[String(p.set_id ?? "")] || "");
      if (matchLook && !setLine) {
        return json({ error: `"${look.name}" records no setting, light or palette to match. `
          + `Read the reference again, or pick one of the studio sets.` }, 400);
      }
      const scene = setBlock(setLine, mode, p.cutout_on_white !== false, matchLook);

      const count = Math.max(1, Math.min(4, Number(p.count) || 1));
      const sources: Inline[] = [];
      for (const u of images.slice(0, MAX_SOURCES)) sources.push(await asInline(u));

      // A frame from earlier in this same run. A white cut-out is deliberately
      // not of the scene, so it never takes one.
      const wantsAnchor = Boolean(p.anchor_url)
        && !(mode === "Clean" && p.cutout_on_white !== false);
      let anchor: Inline | null = null;
      if (wantsAnchor) {
        try { anchor = await asInline(String(p.anchor_url)); }
        catch { anchor = null; }   // a missing anchor must not fail the frame
      }
      const assemble = partsBlock(p.parts, sources.length, kind);
      const folder = crypto.randomUUID();
      const made: any[] = [];
      const failed: string[] = [];

      if (editorial) {
        let firstShot: Inline | null = null;
        for (let i = 0; i < count; i++) {
          const angle = angleFor(i, p.angles, kind);
          try {
            const instruction = editorialInstruction(look, angle, p.piece,
                                                     i === 0 || !firstShot, p.tweak,
                                                     p.parts, sources.length, kind);
            const withPrev = firstShot ? [...sources, firstShot] : sources;
            const img = await oneImage(instruction, withPrev);
            if (!firstShot) firstShot = { mime: img.mime, data: img.data };
            const verdict = wantCheck
              ? await checkOne(sources, img, p.parts, kind).catch((e) => ({
                  match: true, confidence: "unchecked",
                  differences: [`Could not check this one: ${e instanceof Error ? e.message : e}`] }))
              : null;
            made.push(await store(admin, folder, "editorial", i, img,
              { mode, shot_angle: angle, look_id: look.look_id, look_name: look.name,
                set_id: null, check: verdict }));
          } catch (e) {
            failed.push(e instanceof Error ? e.message : String(e));
          }
        }
        if (made.length) {
          await admin.from("looks").update({
            times_used: (look.times_used ?? 0) + 1, last_used_at: new Date().toISOString(),
          }).eq("look_id", look.look_id);
        }
      } else {
        const results = await Promise.allSettled(
          Array.from({ length: count }, (_, i) =>
            oneImage(`${shots[mode]}${assemble}${scene}${anchor ? anchorBlock(mode) : ""}`
              + ((mode === "Clean" && p.cutout_on_white !== false)
                ? ""
                : (mode === "Clean" || mode === "Detail" || mode === "Fabric")
                  ? (matchLook
                      // A borrowed set is a real place, so the piece rests on what that place
                      // already has. Carrying in the studio's chair or stool would give away
                      // that this frame was staged somewhere else.
                      ? `\n\nHow it sits in the frame: resting on whatever surface that place `
                        + `itself offers — a step, a ledge, a sill, a low wall, bare wood or `
                        + `stone. Bring no furniture or props into it that were not already `
                        + `there. Nothing patterned, nothing that competes with the cloth, `
                        + `nothing branded.`
                      : `\n\nHow it sits in the frame: ${propFor(i + (p.prop_from ?? 0))}. `
                        + `Whatever it rests on is plain and belongs to this set — bare wood, `
                        + `stone, cane or undyed linen, nothing patterned, nothing that competes `
                        + `with the cloth and nothing branded.`)
                  : `\n\nCamera: ${angleFor(i, p.angles, kind)}`)
              + `\n\nWhat the piece is:\n`
              + (describe(p.piece ?? {}, "") || "Not described.") + tweakBlock(p.tweak),
              anchor ? [...sources, anchor] : sources)));
        for (let i = 0; i < results.length; i++) {
          const r = results[i];
          if (r.status === "rejected") {
            failed.push(r.reason instanceof Error ? r.reason.message : String(r.reason));
            continue;
          }
          try {
            const verdict = wantCheck
              ? await checkOne(sources, r.value, p.parts, kind).catch((e) => ({
                  match: true, confidence: "unchecked",
                  differences: [`Could not check this one: ${e instanceof Error ? e.message : e}`] }))
              : null;
            made.push(await store(admin, folder, mode.toLowerCase(), i, r.value,
              { mode, shot_angle: mode === "Detail" ? "Close macro of the cloth"
                        : angleFor(i, p.angles, kind),
                look_id: matchLook ? look.look_id : null,
                look_name: matchLook ? look.name : null,
                set_id: p.set_id ?? null, check: verdict }));
          } catch (e) { failed.push(e instanceof Error ? e.message : String(e)); }
        }
      }

      if (matchLook && look && made.length) {
        await admin.from("looks").update({
          times_used: (look.times_used ?? 0) + 1, last_used_at: new Date().toISOString(),
        }).eq("look_id", look.look_id);
      }

      if (!made.length) throw new Error(failed[0] || "No images came back.");
      if (runId) {
        await admin.from("ai_runs").update({
          status: "Done", model: IMAGE_MODEL, response: { made: made.length, failed },
        }).eq("run_id", runId);
      }
      if (p.job_id) {
        await admin.from("launch_jobs").update({
          stage: "Copy", status: "Queued", last_error: failed[0] ?? null,
          message: `${made.length} × ${editorial ? `editorial (${look.name})` : mode.toLowerCase()}`
            + ` image${made.length === 1 ? "" : "s"} generated.`,
          updated_at: new Date().toISOString(),
        }).eq("job_id", p.job_id);
      }
      return json({ ok: true, provider: "gemini", model: IMAGE_MODEL, images: made, failed,
                    // The first frame of this call, for the next call in the run to anchor to.
                    anchor_url: made[0]?.url ?? null,
                    anchored: Boolean(anchor) });
    }

    if (action === "copy") {
      const market = marketLines(p.research);
      const seen = Math.min(images.length, MAX_SOURCES);
      const body = (describe(p.piece ?? {}, p.brief ?? "")
        || "Nothing typed in yet — read the photographs.")
        + partsBlock(p.parts, seen, kindOf(p.piece ?? {})) + market;
      out = await ask(provider, COPY_RULES(brand, Boolean(market), tight),
                      `The piece:\n${body}`, images, false);
    } else if (action === "price") {
      out = await ask(provider, PRICE_RULES(brand, tight),
                      `The piece:\n${describe(p.piece, p.brief ?? "")}`, [], true);
    } else if (action === "campaign") {
      out = await ask(provider, CAMPAIGN_RULES(brand), describeCampaign(p), images, false);
    } else {
      return json({ error: `Unknown action "${action}".` }, 400);
    }

    if (runId) {
      await admin.from("ai_runs").update({
        status: "Done", model: out.model, response: out.data,
        tokens_in: out.usage?.prompt_tokens ?? out.usage?.promptTokenCount ?? null,
        tokens_out: out.usage?.completion_tokens ?? out.usage?.candidatesTokenCount ?? null,
      }).eq("run_id", runId);
    }

    if (p.job_id && action !== "campaign") {
      const patch: Record<string, unknown> = { updated_at: new Date().toISOString(), last_error: null };
      if (action === "copy") {
        patch.generated_title = out.data.title ?? null;
        patch.generated_description = out.data.description ?? null;
        patch.generated_highlights = (out.data.highlights ?? []).join("\n");
        patch.generated_tags = (out.data.tags ?? []).join(", ");
      } else {
        patch.suggested_price = out.data.suggested ?? null;
        patch.price_low = out.data.low ?? null;
        patch.price_high = out.data.high ?? null;
        patch.price_research = out.data.comparables ?? [];
      }
      await admin.from("launch_jobs").update(patch).eq("job_id", p.job_id);
    }

    return json({ ok: true, provider, model: out.model, result: out.data });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (runId) await admin.from("ai_runs").update({ status: "Failed", error: message }).eq("run_id", runId);
    if (p.job_id) await admin.from("launch_jobs").update({ last_error: message }).eq("job_id", p.job_id);
    return json({ error: message }, 502);
  }
});
