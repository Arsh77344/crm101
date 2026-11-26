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
};
const MODELS: Record<string, string> = {
  openai: Deno.env.get("OPENAI_MODEL") || "gpt-4o",
  gemini: Deno.env.get("GEMINI_MODEL") || "gemini-3.8-flash",
  anthropic: Deno.env.get("ANTHROPIC_MODEL") || "claude-sonnet-5-5",
  groq: Deno.env.get("GROQ_SEARCH_MODEL") || "groq/compound",
};
// Which providers can look at the live web while they answer. This matters more
// here than anywhere else in the workspace: a hashtag set written from memory is
// worthless, so a provider that cannot search is not allowed to invent one.
const CAN_SEARCH: Record<string, boolean> = {
  openai: true, gemini: true, anthropic: true, groq: true,
};
const LABEL: Record<string, string> = {
  openai: "ChatGPT", gemini: "Gemini", anthropic: "Claude", groq: "Groq",
};
const SECRET: Record<string, string> = {
  openai: "OPENAI_API_KEY", gemini: "GEMINI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY", groq: "GROQ_API_KEY",
};
const PROVIDERS = ["openai", "gemini", "anthropic", "groq"];

function parseJson(text: string): any {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const raw = fenced ? fenced[1] : text;
  const a = raw.indexOf("{"), b = raw.lastIndexOf("}");
  if (a === -1 || b === -1) throw new Error("The model did not return JSON.");
  return JSON.parse(raw.slice(a, b + 1));
}

async function brandContext(admin: any) {
  const { data } = await admin.from("settings").select("setting_key,setting_value");
  const s: Record<string, string> = {};
  (data ?? []).forEach((r: any) => { s[r.setting_key] = r.setting_value ?? ""; });
  return {
    text: [
      s.brand_name ? `The brand is ${s.brand_name}.` : "",
      s.brand_sells ? `It sells: ${s.brand_sells}` : "",
      s.brand_audience ? `Its customers: ${s.brand_audience}` : "",
      s.brand_voice ? `How it writes: ${s.brand_voice}` : "",
      s.storefront_url ? `Its storefront: ${s.storefront_url}` : "",
    ].filter(Boolean).join("\n"),
    settings: s,
  };
}

// What the agent may know. Everything else it has to ask for or leave out.
async function workspace(admin: any) {
  const since = new Date(Date.now() - 45 * 86400000).toISOString();
  const [products, posts, occasions, looks, templates, plans, campaigns] = await Promise.all([
    admin.from("products")
      .select("product_id,public_product_name,category,fabric,colour,weave_or_motif,retail_price,"
        + "stock_qty,story,product_images(image_id,generated,is_primary),brands(name,city,story)")
      .eq("status", "Published").order("created_at", { ascending: false }).limit(40),
    // What has gone out lately, so the plan does not say the same thing again.
    admin.from("campaign_posts").select("title,body,channel,placement,scheduled_for,status")
      .gte("created_at", since).order("scheduled_for", { ascending: false }).limit(60),
    admin.from("occasions_upcoming")
      .select("occasion_id,name,occasion_date,until_date,date_basis,kind,region,meaning,"
        + "what_sells,avoid,days_away,days_until_promote,promote_from")
      .gte("days_away", 0).order("occasion_date").limit(8),
    admin.from("looks").select("look_id,look_no,name,summary,source,use_for")
      .eq("status", "Ready").order("look_no").limit(20),
    admin.from("message_templates").select("name,channel,category,provider_status")
      .eq("provider_status", "Approved").limit(40),
    admin.from("social_plans").select("title,starts_on,days,market,status")
      .order("starts_on", { ascending: false }).limit(6),
    // The campaigns themselves, not just the posts they produced. Reading the
    // posts tells this agent what was said; reading the campaign tells it what
    // the campaign is FOR -- and without that it can only avoid clashing with a
    // campaign, never carry it.
    admin.from("campaigns")
      .select("campaign_id,campaign_name,objective,status,start_date,end_date,offer,brief,"
        + "art_direction,audience_note,market,ad_plan")
      .order("start_date", { ascending: false }).limit(8),
  ]);
  return {
    products: products.data ?? [], posts: posts.data ?? [],
    occasions: occasions.data ?? [], looks: looks.data ?? [],
    templates: templates.data ?? [], plans: plans.data ?? [],
    campaigns: campaigns.data ?? [],
  };
}

// A piece with no photographs cannot carry a post this week, however good the
// idea is. Saying so is more useful than planning a post that cannot be shot.
function imageryOf(x: any) {
  const shots = x.product_images ?? [];
  if (!shots.length) return "NO PHOTOGRAPHS - cannot be posted until it is shot";
  const own = shots.filter((i: any) => !i.generated).length;
  const made = shots.length - own;
  return `${shots.length} image${shots.length === 1 ? "" : "s"}`
    + ` (${[own ? `${own} the owner's own` : "", made ? `${made} generated` : ""]
        .filter(Boolean).join(", ")})`;
}

function catalogueLines(w: any) {
  const pieces = w.products.slice(0, 25).map((x: any) =>
    `- ${x.public_product_name} · ${[x.category, x.colour, x.fabric, x.weave_or_motif]
      .filter(Boolean).join(", ")}`
    + ` · ${x.retail_price ?? "unpriced"} · ${x.stock_qty ?? 0} in stock`
    + ` · ${imageryOf(x)} [id ${x.product_id}]`
    + (x.story ? `\n    its story (recorded, true): ${x.story}` : `\n    its story: NOT RECORDED`)
    + (x.brands?.story
        ? `\n    the workshop: ${x.brands.name}${x.brands.city ? ` in ${x.brands.city}` : ""} — ${x.brands.story}`
        : "")).join("\n");
  return pieces || "Nothing published in the catalogue yet.";
}

function recentLines(w: any) {
  if (!w.posts.length) return "Nothing has been posted or planned in the last six weeks.";
  return w.posts.slice(0, 30).map((p: any) =>
    `- ${p.scheduled_for ? String(p.scheduled_for).slice(0, 10) : "unscheduled"}`
    + ` · ${p.channel}${p.placement ? ` / ${p.placement}` : ""} · ${p.status}`
    + ` · ${p.title}`).join("\n");
}

function occasionLines(w: any) {
  if (!w.occasions.length) {
    return "Nothing on the occasions calendar. If timing matters, say so and ask the owner to add "
      + "it on the Occasions page rather than guessing a date.";
  }
  return w.occasions.map((o: any) => {
    const lead = o.days_until_promote <= 0
      ? `run-up is ON NOW, ${o.days_away} days to the day itself`
      : `run-up starts in ${o.days_until_promote} days`;
    return `- ${o.name} · ${o.kind}${o.region ? ` · ${o.region}` : ""}`
      + ` · ${o.occasion_date}${o.until_date ? ` to ${o.until_date}` : ""}`
      + ` · ${o.date_basis === "Approximate" ? "DATE APPROXIMATE" : `date ${String(o.date_basis).toLowerCase()}`}`
      + ` · ${lead} [id ${o.occasion_id}]`
      + (o.meaning ? `\n    what it means: ${o.meaning}` : "")
      + (o.what_sells ? `\n    what sells: ${o.what_sells}` : "")
      + (o.avoid ? `\n    WHAT WOULD BE WRONG: ${o.avoid}` : "");
  }).join("\n");
}

// A campaign that is running, or about to, changes this agent's job entirely:
// the week stops being its own idea and becomes the drumbeat under the
// campaign. The owner asked for exactly this -- what the campaign manager
// decides should reach the social manager and get promoted -- and the spine is
// the thing that has to carry across, not the posts.
function campaignLines(w: any) {
  const today = new Date().toISOString().slice(0, 10);
  const soon = new Date(Date.now() + 21 * 86400000).toISOString().slice(0, 10);
  const live = (w.campaigns ?? []).filter((c: any) => {
    if (String(c.status ?? "").toLowerCase() === "ended") return false;
    const a = c.start_date ?? "", b = c.end_date ?? "";
    // Running now, or starting inside the next three weeks.
    return (a <= today && (!b || b >= today)) || (a > today && a <= soon);
  });
  if (!live.length) {
    const recent = (w.campaigns ?? []).slice(0, 2).map((c: any) =>
      `- ${c.campaign_name} (${c.status}) ${c.start_date ?? "?"} to ${c.end_date ?? "?"}`)
      .join("\n");
    return `\nNo campaign is running or about to start, so this week is yours to decide.`
      + (recent ? `\n\nThe last campaigns, for continuity — pick up a thread rather than
starting from nothing:\n${recent}` : "");
  }
  const rows = live.map((c: any) => {
    const spine = c.brief || c.audience_note || "";
    const when = c.start_date && c.start_date > new Date().toISOString().slice(0, 10)
      ? `starts ${c.start_date}` : `running now, to ${c.end_date ?? "no end set"}`;
    return `- ${c.campaign_name} · ${c.objective ?? "no objective set"} · ${when}`
      + (c.market ? ` · aimed at ${c.market}` : "")
      + (spine ? `\n    what it is about: ${spine}` : "")
      + (c.offer ? `\n    its offer: ${c.offer}` : "")
      + (c.art_direction ? `\n    its art direction: ${c.art_direction}` : "")
      + ` [campaign_id ${c.campaign_id}]`;
  }).join("\n");
  return `\nA CAMPAIGN IS IN PLAY. This changes what this week is for:
${rows}

Your week carries that campaign rather than competing with it. Say the same thing the campaign
says, in the places and the register a feed uses rather than an advertisement: the campaign makes
the argument, these posts make it familiar. Concretely:

- Build the week on the campaign's own spine. Do not invent a second story running alongside it —
  two stories in one week is how a small brand sounds confused.
- Each post takes a different part of that spine, in the campaign's own art direction so the feed
  and the campaign look like one thing.
- Where the campaign has an offer, mention it plainly once across the whole week, not in every
  post. A feed that repeats an offer reads as a sale.
- Do not re-plan a day the campaign already has a post on — they are in the list of what has gone
  out above. Fill the gaps between its posts, which is what keeps a campaign alive between beats.
- Say in "say" which campaign you are carrying and how this week serves it.`;
}

function guardLines(settings: Record<string, string>, w: any) {
  const approved = (w.templates ?? []).filter((t: any) => /whats/i.test(t.channel ?? ""));
  const qs = settings.guard_quiet_start, qe = settings.guard_quiet_end;
  return `WHAT THIS WORKSPACE WILL ACTUALLY SEND:

- Posting on Instagram messages nobody, so it counts against nothing. Plan freely there.
- A WhatsApp broadcast or a marketing email does count. The cap is
  ${settings.guard_max_marketing_per_week || "not set"} per person per week, and quiet hours are
  ${qs && qe ? `${qs}:00 to ${qe}:00` : "not set"}. Keep the whole week inside that and say in
  "say" what it comes to.
- A WhatsApp message the brand starts needs a template the provider approved in advance.
  ${approved.length
    ? `Approved now: ${approved.map((t: any) => `"${t.name}"`).join(", ")}.`
    : `There are none approved yet, so do not plan a WhatsApp broadcast this week. Say that a
  template has to be written on the Message templates page and approved first.`}`;
}

const SHAPE = `{
  "say": string,
  "title": string,
  "occasion_id": string | null,
  "carries_campaign": null | { "campaign_id": string, "name": string, "how": string },
  "research": [{
    "what": string, "found": string, "where": string,
    "kind": "hashtag" | "format" | "conversation" | "timing"
  }],
  "posts": [{
    "day_offset": number,
    "channel": string,
    "placement": string,
    "title": string,
    "body": string,
    "hashtags": string,
    "hashtag_note": string,
    "cta": string,
    "product_id": string | null,
    "art_direction": string,
    "teaches": string
  }],
  "replies": [{ "question": string, "answer": string }],
  "needs_shooting": [{ "product_id": string, "why": string }]
}`;

// The rule that decides whether this is worth having. A luxury house that
// chases a format because it is trending reads as a brand with nothing of its
// own; one that ignores what is being watched entirely talks to nobody. The
// test is whether the trend can carry the craft.
const TRENDS = `WHAT TO DO WITH A TREND. You can search the web this turn, so find out what is
actually being watched, worn and talked about right now in this market — and then apply one test
to everything you find:

CAN THIS TREND CARRY THE CRAFT? If a format, sound or conversation gives you a way to show the
loom, the motif, the hand, the drape or the person who made it, use it. If using it would mean the
piece is incidental — a dance, a meme, a template where the saree is just a costume — leave it
out and say why in "say". A house at this price is not competing for a trend; it is borrowing a
format people already know how to watch. Chasing one it cannot carry is the fastest way to look
like a reseller.

HASHTAGS ARE RESEARCHED, NEVER REMEMBERED. Hashtag sizes and which communities use them change
constantly, and a tag you recall from training is worse than no tag: it puts the brand in a feed
nobody reads, or in one so large it vanishes. For every set you give:
- look them up this turn, and put what you found in "research" with where you found it;
- in "hashtag_note", say roughly how big each important tag is and who posts in it, so the owner
  can see the reasoning rather than a wall of words;
- mix sizes deliberately: a few large ones for reach, several mid-sized where the brand can
  actually rank, and one or two the brand could own over time;
- if you could not verify a tag, leave it out. An unverified hashtag goes in "say" as something to
  check, not in "hashtags".

If your search returns nothing solid, say so plainly and give the week without hashtags rather than
filling the gap. The owner would rather post with none than post into the wrong room.`;

const VOICE = `HOW IT IS WRITTEN.

- Every word in English. The owner has decided this and it is not yours to revisit. A proper noun
  is not a translation, so Margazhi stays Margazhi, Aadi stays Aadi, and a weave keeps its own
  name — then make the sentence around it carry the meaning for someone who does not know the word.
- TEACH SOMETHING IN EVERY POST. "teaches" says what the reader learns. A post that teaches
  nothing is filler, and this is a feed people follow to learn to read cloth. What a shikargah
  depicts, how kadhua differs from a cutwork copy, why a naqsha is drawn before a thread is
  thrown, how to tell a real zari — that is the material.
- Motif and technique lore is general knowledge and you may use it. What is specific to a piece —
  days on the loom, a weaver's name, a number of generations, a village, a GI claim — must be in
  the piece's recorded story above. Where it is not, ask for it in "say"; never invent it.
- BANNED WORDS: exquisite, timeless, elegant, luxurious, heirloom, masterpiece, curated,
  handcrafted with love, epitome, unparalleled, regal, royal elegance.
- No urgency, no countdowns, no "don't miss out", no emoji, no exclamation marks. State a price or
  an offer plainly once if at all. Scarcity here is the scarcity of the skill.
- Captions run 25 to 70 words. Long enough to say something true, short enough to be read.`;

const RULES = (brand: string, catalogue: string, recent: string, occasions: string,
               guards: string, campaigns: string, market: string, days: number,
               search: boolean) => `${brand}

You run this brand's social media between campaigns. Not a campaign — the weekly drumbeat that
keeps the feed alive and the content calendar full. You are talking to the owner, who will shoot
and publish this himself, so be concrete and brief.

WHAT IS TRUE RIGHT NOW. Everything below was read from the owner's own workspace a moment ago.
Use only these pieces and these numbers. Never invent a product, a price, a stock figure or a
past result.

The catalogue, published and sellable:
${catalogue}

What has gone out lately — do not repeat an idea that is already here, and do not reuse a piece
that was the subject of a post in the last fortnight:
${recent}

${campaigns}

What is coming up, from the owner's own calendar:
${occasions}
Where a row says WHAT WOULD BE WRONG, that is the owner's own warning and it overrides anything
you would otherwise have planned. Where a date is marked DATE APPROXIMATE you may plan to it but
no caption may print that date to a customer: write "this Diwali", not the day.

${guards}

${market
  ? `THE MARKET: ${market}. Everything is for a buyer there — what the occasion is called there,
what the garment is called there, what they would notice first.`
  : `No market named, so write for the brand's whole audience and say in "say" that naming one
would sharpen the plan considerably.`}

${TRENDS}

${VOICE}

THE WEEK. Plan ${days} days. Four to seven posts — fewer, better. Vary the format: a still of the
piece, something in motion, a close detail, the making, the person who made it, how it is worn.
"day_offset" counts from the start, from 0. "product_id" is one of the ids above or null; null is
right for a post about the craft rather than a piece. Only plan a post around a piece that has
photographs — anything you want to use that has none goes in "needs_shooting" instead, with why.

"replies" is four to eight questions that actually arrive under a post of this kind — is it
available, what is the blouse length, is the zari real, how do I care for it, can it reach me by
Friday — answered in the brand's voice from what is above. Where an answer depends on something
you were not given, say so in the answer rather than guessing.

${search ? "" : `YOU CANNOT SEARCH THE WEB THIS TURN. So give no hashtags at all, leave "research"
empty, and say in "say" that the week needs its tags checked before it goes out. Do not write
hashtags from memory.`}

Return only JSON of exactly this shape:
${SHAPE}

"say" is a few plain sentences: what the week does, the two or three judgements you made, what you
found that changed the plan, and anything you need from the owner.
"title" names the week in a few words.
Dates are ISO (YYYY-MM-DD). Today is ${new Date().toISOString().slice(0, 10)}.`;

function flatten(system: string, user: string) {
  return `${system}\n\n---\n${user}\n\nAnswer with the JSON.`;
}

async function openaiCall(system: string, user: string, search: boolean) {
  if (search) {
    const res = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: { Authorization: `Bearer ${KEYS.openai}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODELS.openai, tools: [{ type: "web_search_preview" }],
        input: flatten(system, user) }),
    });
    const b = await res.json();
    if (!res.ok) throw new Error(b?.error?.message || `OpenAI returned ${res.status}.`);
    const text = b.output_text ?? (b.output ?? [])
      .flatMap((o: any) => (o.content ?? []).map((c: any) => c.text ?? "")).join("\n");
    return { data: parseJson(text), usage: b.usage, model: MODELS.openai };
  }
  const res = await fetch("https://api.openai.com/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.openai}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.openai, response_format: { type: "json_object" },
      messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `OpenAI returned ${res.status}.`);
  return { data: parseJson(b.choices[0].message.content), usage: b.usage, model: MODELS.openai };
}

async function geminiCall(prompt: string, search: boolean) {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${MODELS.gemini}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({ contents: [{ role: "user", parts: [{ text: prompt }] }],
        ...(search ? { tools: [{ google_search: {} }] } : {}) }) });
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `Gemini returned ${res.status}.`;
    throw new Error(res.status === 404
      ? `${m} The model name "${MODELS.gemini}" may have been retired — set GEMINI_MODEL.` : m);
  }
  const text = (b.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("\n");
  return { data: parseJson(text), usage: b.usageMetadata, model: MODELS.gemini };
}

async function claudeCall(system: string, user: string, search: boolean) {
  const body: any = { model: MODELS.anthropic, max_tokens: 8000, system,
                      messages: [{ role: "user", content: user }] };
  if (search) {
    body.tools = [{ type: "web_search_20250305", name: "web_search", max_uses: 6 }];
  }
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": KEYS.anthropic, "anthropic-version": "2023-06-01",
               "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Claude returned ${res.status}.`);
  const text = (b.content ?? []).filter((c: any) => c.type === "text")
    .map((c: any) => c.text).join("\n");
  return { data: parseJson(text),
           usage: { prompt_tokens: b.usage?.input_tokens, completion_tokens: b.usage?.output_tokens },
           model: MODELS.anthropic };
}

async function groqCall(system: string, user: string) {
  const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { Authorization: `Bearer ${KEYS.groq}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.groq,
      messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Groq returned ${res.status}.`);
  const choice = b.choices?.[0];
  if (choice?.finish_reason === "length") {
    throw new Error("Groq ran out of output budget before finishing the week. A week of posts is "
      + "a long answer — use Gemini, ChatGPT or Claude for this page.");
  }
  return { data: parseJson(choice.message.content), usage: b.usage, model: MODELS.groq };
}

async function ask(provider: string, system: string, user: string, search: boolean) {
  const live = search && CAN_SEARCH[provider];
  if (provider === "gemini") return geminiCall(flatten(system, user), live);
  if (provider === "anthropic") return claudeCall(system, user, live);
  if (provider === "groq") return groqCall(system, user);
  return openaiCall(system, user, live);
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
      anthropic: Boolean(KEYS.anthropic), groq: Boolean(KEYS.groq),
      models: MODELS, can_search: CAN_SEARCH,
      brand_set: Boolean(settings.brand_name && settings.brand_sells),
    });
  }
  if (action !== "plan") return json({ error: `Unknown action "${action}".` }, 400);

  const provider = PROVIDERS.includes(p.provider) ? p.provider : "openai";
  if (!KEYS[provider]) {
    return json({ error: `No ${LABEL[provider]} key is set. Add ${SECRET[provider]} to this `
      + `project's Edge Function secrets.` }, 400);
  }

  const { text: brand, settings } = await brandContext(admin);
  if (!settings.brand_name || !settings.brand_sells) {
    return json({ error: "Fill in the brand name and what it sells on the Settings page first, "
      + "so nothing gets invented." }, 400);
  }

  const started = await admin.from("ai_runs").insert({
    kind: "social-agent", provider, status: "Running",
    request: { days: p.days ?? 7, market: p.market ?? null, search: p.search !== false },
  }).select("run_id").maybeSingle();
  const runId = started.data?.run_id;

  try {
    const w = await workspace(admin);
    const days = Math.max(3, Math.min(14, Number(p.days) || 7));
    const market = String(p.market ?? "").trim().slice(0, 120);
    const wantSearch = p.search !== false && CAN_SEARCH[provider];
    const said = String(p.brief ?? "").trim().slice(0, 2000);

    const system = RULES(brand, catalogueLines(w), recentLines(w), occasionLines(w),
                         guardLines(settings, w), campaignLines(w), market, days, wantSearch);
    const out = await ask(provider, system,
      said || `Plan the next ${days} days.`, wantSearch);
    const d = out.data || {};

    // The ids it hands back have to be real, or approval writes rubbish.
    const known = new Set(w.products.map((x: any) => x.product_id));
    const knownOcc = new Set(w.occasions.map((x: any) => x.occasion_id));
    d.posts = (Array.isArray(d.posts) ? d.posts : []).slice(0, 12).map((x: any) => ({
      ...x, product_id: known.has(x?.product_id) ? x.product_id : null,
    }));
    d.needs_shooting = (Array.isArray(d.needs_shooting) ? d.needs_shooting : [])
      .filter((x: any) => known.has(x?.product_id)).slice(0, 10);
    d.research = (Array.isArray(d.research) ? d.research : []).slice(0, 20);
    d.replies = (Array.isArray(d.replies) ? d.replies : []).slice(0, 10);
    if (!knownOcc.has(d.occasion_id)) d.occasion_id = null;
    const knownCamp = new Set(w.campaigns.map((x: any) => x.campaign_id));
    if (!d.carries_campaign || !knownCamp.has(d.carries_campaign.campaign_id)) {
      d.carries_campaign = null;
    }

    // A plan that could not search has no business carrying hashtags, whatever
    // the model decided to write. This is enforced here rather than trusted to
    // the prompt, because an invented tag is the one failure the owner cannot
    // spot by reading.
    if (!wantSearch) {
      d.posts = d.posts.map((x: any) => ({
        ...x, hashtags: "",
        hashtag_note: "No tags: the model could not search this turn, so none were verified.",
      }));
      d.research = [];
    }

    if (runId) {
      await admin.from("ai_runs").update({
        status: "Done", model: out.model, response: d,
        tokens_in: out.usage?.prompt_tokens ?? out.usage?.promptTokenCount ?? null,
        tokens_out: out.usage?.completion_tokens ?? out.usage?.candidatesTokenCount ?? null,
      }).eq("run_id", runId);
    }

    return json({ ok: true, provider, model: out.model, searched: wantSearch,
                  plan: { ...d, days, market: market || null } });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (runId) {
      await admin.from("ai_runs").update({ status: "Failed", error: message }).eq("run_id", runId);
    }
    return json({ error: message }, 502);
  }
});
