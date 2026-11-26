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
  nvidia: Deno.env.get("NVIDIA_MODEL") || "minimaxai/minimax-m3.1-flash",
};
const GROQ_MAX = Math.max(256, Number(Deno.env.get("GROQ_MAX_TOKENS") || 900));
const GROQ_SEARCH = Deno.env.get("GROQ_SEARCH_MODEL") || "groq/compound";
// Which providers can look at the live web while they answer. NVIDIA's catalogue
// has no search-grounded chat model, so it drafts from the workspace alone.
const CAN_SEARCH: Record<string, boolean> = {
  openai: true, gemini: true, anthropic: true, groq: true, nvidia: false,
};
const LABEL: Record<string, string> = {
  openai: "ChatGPT", gemini: "Gemini", anthropic: "Claude", groq: "Groq", nvidia: "NVIDIA",
};
const SECRET: Record<string, string> = {
  openai: "OPENAI_API_KEY", gemini: "GEMINI_API_KEY", anthropic: "ANTHROPIC_API_KEY",
  groq: "GROQ_API_KEY", nvidia: "NVIDIA_API_KEY",
};
const PROVIDERS = ["openai", "gemini", "anthropic", "groq", "nvidia"];

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
      s.whatsapp_number ? `It takes orders on WhatsApp.` : "",
      s.default_currency ? `It prices in ${s.default_currency}.` : "",
    ].filter(Boolean).join("\n"),
    settings: s,
  };
}

// What the agent is allowed to know: the real catalogue, the real looks, what
// the last campaigns actually did. Everything else it must ask for.
async function workspace(admin: any) {
  const [products, collections, looks, past, orders, occasions, templates,
         plans, booked] = await Promise.all([
    admin.from("products")
      .select("product_id,public_product_name,category,fabric,colour,weave_or_motif,retail_price,"
        + "stock_qty,status,story,description,"
        + "product_images(image_id,generated,shot_angle,is_primary),"
        + "brands(name,city,story)")
      .eq("status", "Published").order("created_at", { ascending: false }).limit(40),
    admin.from("collections").select("collection_id,name,kind,description,status").limit(20),
    admin.from("looks").select("look_id,look_no,name,summary,source,use_for,status")
      .eq("status", "Ready").order("look_no").limit(30),
    admin.from("campaigns")
      .select("campaign_name,objective,channel,audience_type,budget,spend,start_date,end_date,offer")
      .order("created_at", { ascending: false }).limit(8),
    admin.from("orders").select("total,ordered_at,first_touch_campaign")
      .order("ordered_at", { ascending: false }).limit(60),
    // The occasions calendar, with the run-up already worked out by the view so
    // the agent and the browser cannot disagree about what "coming up" means.
    admin.from("occasions_upcoming")
      .select("occasion_id,name,occasion_date,until_date,date_basis,lead_weeks,kind,region,"
        + "meaning,what_sells,avoid,note,promote_from,days_away,days_until_promote")
      .gte("days_away", 0).order("occasion_date").limit(12),
    // A WhatsApp message the brand starts needs a template the provider already
    // approved, so the agent may only plan around the ones that exist.
    admin.from("message_templates").select("name,channel,category,provider_status")
      .eq("provider_status", "Approved").limit(40),
    // What the social agent has already planned. Without this a campaign gets
    // built straight over a week somebody already committed to, and the owner
    // finds out when two sets of posts land on the same days.
    admin.from("social_plans").select("plan_id,title,starts_on,days,market,status,say")
      .order("starts_on", { ascending: false }).limit(5),
    // Days that already have something on them, campaign or always-on.
    admin.from("campaign_posts").select("title,channel,placement,scheduled_for,status,plan_id")
      .gte("scheduled_for", new Date().toISOString())
      .order("scheduled_for").limit(60),
  ]);
  const p = products.data ?? [];
  const sold = (orders.data ?? []);
  const revenue = sold.reduce((n: number, o: any) => n + Number(o.total || 0), 0);
  return {
    products: p, collections: collections.data ?? [], looks: looks.data ?? [],
    past: past.data ?? [],
    occasions: occasions.data ?? [], templates: templates.data ?? [],
    plans: plans.data ?? [], booked: booked.data ?? [],
    trade: { orders: sold.length, revenue,
             average: sold.length ? Math.round(revenue / sold.length) : null },
  };
}

function imageryOf(x: any) {
  const shots = x.product_images ?? [];
  if (!shots.length) return "no photographs at all";
  const made = shots.filter((i: any) => i.generated).length;
  const own = shots.length - made;
  const parts = [
    own ? `${own} of the owner's own` : "",
    made ? `${made} generated` : "",
  ].filter(Boolean).join(", ");
  return `${shots.length} image${shots.length === 1 ? "" : "s"} (${parts})`;
}

function catalogueLines(w: any) {
  const pieces = w.products.slice(0, 25).map((x: any) =>
    `- ${x.public_product_name} · ${[x.category, x.colour, x.fabric, x.weave_or_motif].filter(Boolean).join(", ")}`
    + ` · ${x.retail_price ?? "unpriced"} · ${x.stock_qty ?? 0} in stock`
    + ` · imagery: ${imageryOf(x)} [id ${x.product_id}]`
    + (x.story ? `\n    its story (recorded, true): ${x.story}` : `\n    its story: NOT RECORDED`)
    + (x.brands?.story
        ? `\n    the workshop that made it: ${x.brands.name}${x.brands.city ? ` in ${x.brands.city}` : ""} — ${x.brands.story}`
        : x.brands?.name
          ? `\n    the workshop that made it: ${x.brands.name}${x.brands.city ? ` in ${x.brands.city}` : ""}, no story recorded`
          : "")).join("\n");
  const looks = w.looks.map((l: any) =>
    `- #${l.look_no} ${l.name}: ${l.summary ?? "no description"} (${l.source === "Own" ? "ours, may follow closely" : "found, direction only"}) [id ${l.look_id}]`).join("\n");
  const past = w.past.map((c: any) =>
    `- ${c.campaign_name} · ${c.objective} · ${c.channel} · budget ${c.budget ?? "none"} · spent ${c.spend ?? 0}`).join("\n");
  return [
    pieces ? `Pieces in the catalogue, published and sellable:\n${pieces}` : "Nothing published in the catalogue yet.",
    looks ? `\nLooks already read in the library, usable as art direction:\n${looks}` : "\nNo looks read yet.",
    past ? `\nWhat has been run before:\n${past}` : "\nNo campaigns run before.",
    `\nTrade so far: ${w.trade.orders} orders, ${w.trade.revenue} total, average order ${w.trade.average ?? "unknown"}.`,
  ].join("\n");
}

// What is coming up, and how long until its run-up starts. The owner's rule is
// that promotion begins about three weeks out, so `days_until_promote` is the
// number that decides whether an occasion is in play, not `days_away`.
//
// Dates are carried with their basis. A lunar festival is published differently
// by different panchangs -- Holi 2027 appears as both 22 and 23 March -- so an
// unconfirmed date must never reach a customer as fact.
function occasionLines(w: any) {
  const list = w.occasions ?? [];
  if (!list.length) {
    return "\nNo occasions on the calendar. If timing matters to this campaign, say so and ask the "
      + "owner to add the occasion on the Occasions page rather than guessing a date.";
  }
  const rows = list.map((o: any) => {
    const span = o.until_date && o.until_date !== o.occasion_date
      ? `${o.occasion_date} to ${o.until_date}` : o.occasion_date;
    const lead = o.days_until_promote <= 0
      ? `run-up is ON NOW, ${o.days_away} days until the day itself`
      : `run-up starts in ${o.days_until_promote} days (from ${o.promote_from})`;
    return `- ${o.name} · ${o.kind}${o.region ? ` · ${o.region}` : ""} · ${span}`
      + ` · ${o.date_basis === "Approximate" ? "DATE APPROXIMATE" : `date ${o.date_basis.toLowerCase()}`}`
      + ` · ${lead} [id ${o.occasion_id}]`
      + (o.meaning ? `\n    what it means: ${o.meaning}` : "")
      + (o.what_sells ? `\n    what sells: ${o.what_sells}` : "")
      + (o.avoid ? `\n    WHAT WOULD BE WRONG: ${o.avoid}` : "");
  }).join("\n");
  return `\nWhat is coming up, from the owner's own calendar:\n${rows}

Use this rather than your own idea of when a festival falls. Where an occasion is in its run-up or
about to be, say in "say" whether this campaign should be built on it, and set "occasion" to it if
it should. Where a row says WHAT WOULD BE WRONG, that is the owner's own warning and it overrides
anything you would otherwise have planned for that market.

NEVER PRINT AN UNCONFIRMED DATE. Where a date is marked DATE APPROXIMATE you may plan to it, but no
caption, email, headline or message may state that date to a customer. Write "this Diwali" or "the
week of the festival", not the day. Say in "say" which date the owner should confirm. A date marked
confirmed or fixed may be printed.`;
}

// The workspace's own sending rules. An omni-channel plan that breaks them
// cannot actually be run, so the agent is told them rather than being left to
// invent a cadence.
// What the always-on social side has already committed to. A campaign that
// ignores it collides with it: two sets of posts on the same days, two stories
// in one week, and the owner discovering both only when the calendar fills up.
function calendarLines(w: any) {
  const plans = (w.plans ?? []).filter((x: any) =>
    String(x.status ?? "").toLowerCase() !== "cancelled");
  const booked = w.booked ?? [];
  if (!plans.length && !booked.length) {
    return "\nThe content calendar ahead is empty, so this campaign has it to itself.";
  }
  const planRows = plans.slice(0, 4).map((x: any) =>
    `- ${x.title} · ${x.days} days from ${x.starts_on} · ${x.status}`
    + (x.market ? ` · ${x.market}` : "")).join("\n");
  const byDay: Record<string, number> = {};
  booked.forEach((p: any) => {
    const d = String(p.scheduled_for ?? "").slice(0, 10);
    if (d) byDay[d] = (byDay[d] ?? 0) + 1;
  });
  const days = Object.entries(byDay).slice(0, 21)
    .map(([d, n]) => `${d} (${n})`).join(", ");
  return `\nWHAT IS ALREADY ON THE CALENDAR. The social side plans the weeks between campaigns,
and some of it is already committed:
${planRows || "- no weeks planned"}
${days ? `\nDays that already carry something: ${days}` : ""}

Plan around it rather than over it:
- Do not put a post on a day that already has two or more. Say in "say" where you had to move.
- If a social week overlaps this campaign's window, that is not a clash to avoid — it is the
  drumbeat under the campaign, and it will be rewritten to carry this campaign's spine once this
  is approved. Say in "say" which weeks that will affect, so the owner knows to re-plan them.
- Where a social week has a story of its own that this campaign contradicts, say so plainly. Two
  stories running at once is the thing to avoid, and the owner decides which one survives.`;
}

function guardLines(settings: Record<string, string>, w: any) {
  const approved = (w.templates ?? []).filter((t: any) => /whats/i.test(t.channel ?? ""));
  const names = approved.map((t: any) => `"${t.name}" (${t.category})`).join(", ");
  const maxWeek = settings.guard_max_marketing_per_week;
  const qs = settings.guard_quiet_start, qe = settings.guard_quiet_end;
  return `WHAT THIS WORKSPACE WILL ACTUALLY SEND. These are the owner's own rules, already enforced
by the system, so a plan that breaks them cannot be run:

- Marketing messages per person per week: ${maxWeek || "not set"}. Count every WhatsApp broadcast
  and marketing email in your plan against that ceiling, per person, and say in "say" what the
  plan comes to. Instagram posts do not count: nobody is messaged.
- Quiet hours: ${qs && qe ? `nothing marketing goes out between ${qs}:00 and ${qe}:00` : "not set"}.
- A WhatsApp message the brand starts must use a template the provider approved in advance.
  ${approved.length
    ? `Approved and usable now: ${names}. Plan around these.`
    : `There are no approved WhatsApp templates yet. You may still plan the WhatsApp step, but say
  plainly that a template has to be written on the Message templates page and approved before it
  can go out, and do not imply it can be sent this week.`}
- Replies inside a conversation someone started are free of all of the above. Lean on that: a
  story that makes someone message first is worth more than a broadcast.`;
}

const BRIEFING_ASK = `Nobody is at the screen. Look at the week ahead on your own and propose the
one campaign worth running next.

Start from what is actually here: which pieces are in stock and have not been pushed, what was run
before and how it went, and what is coming up in the next three or four weeks that this brand's
customers care about. Search for the dates rather than assuming them.

Pick one campaign, draft it in full, and in "say" lead with why this one and why now, in two or
three sentences. If the honest answer is that nothing is worth running this week — no stock, nothing
coming up — say that instead and leave "proposal" null. An unnecessary campaign costs real money.`;

const SHAPE = `{
  "say": string,
  "ask": string | null,
  "ready": boolean,
  "options": [{
    "name": string, "spine": string, "why": string,
    "trade_off": string, "recommended": boolean
  }],
  "proposal": null | {
    "campaign_name": string,
    "objective": string,
    "audience_note": string,
    "channel": string,
    "start_date": string,
    "end_date": string,
    "budget": number | null,
    "offer": string,
    "brief": string,
    "spine": string,
    "occasion": null | { "occasion_id": string | null, "name": string, "why": string },
    "channel_plan": [{
      "channel": string, "role": string, "cadence": string,
      "first_move": string, "hands_off_to": string
    }],
    "six_cs": [{ "c": string, "verdict": "met" | "weak", "note": string }],
    "art_direction": string,
    "casting": string,
    "look_id": string | null,
    "pieces": [{
      "product_id": string, "why": string,
      "imagery": "ready" | "needs a shoot" | "worth reshooting"
    }],
    "posts": [{
      "channel": string, "placement": string, "title": string, "body": string,
      "hashtags": string, "cta": string, "day_offset": number,
      "product_id": string | null, "art_direction": string
    }],
    "ad_plan": {
      "daily_budget": number | null,
      "ad_sets": [{
        "name": string, "platforms": string, "placements": string,
        "audience": string, "age": string, "interests": string, "geography": string,
        "budget_share": string, "primary_text": string, "headline": string,
        "description": string, "cta_button": string
      }],
      "measurement": string
    }
  }
}`;

// A Banarasi piece sells into Tamil Nadu and into Punjab, but not with the same
// words, the same festival or the same casting. This is the difference between
// a campaign that reads as local and one that reads as imported.
const marketBlock = (market: string) => market
  ? `\n\nTHE MARKET THIS IS FOR: ${market}.
Everything you write is for a buyer there, and a campaign that could run anywhere has failed.

- Time it to that market's own calendar: its festivals, its wedding season, its auspicious months
  and the dates those actually fall on this year. A date that matters in the north may be an
  ordinary week there.
- Write every word in English. This is a decision the owner has made and it is not yours to
  revisit: the house sells across several markets and one clear voice in English carries further
  than a different voice per language, and copy half-translated by someone who does not speak the
  language reads as cheap. Do not write a line, a caption, a headline or a hashtag in another
  language, do not transliterate one, and do not offer a translated version.
- English does not mean generic. The register still belongs to the market: what the occasion is
  called there, what the garment is called there, what a buyer there would notice first. A proper
  noun is not a translation — Margazhi, Puthandu, Aadi, a weave's own name — so use the real name
  of a thing rather than an English approximation of it, and make the sentence around it carry the
  meaning for a reader who does not know the word.
- Cast and style the imagery for that market, in "casting". A Banarasi saree is the brand's own
  craft and it travels — the piece does not change — but who wears it, how it is draped, the
  jewellery, the hair, the flowers and the setting all belong to the market being sold to. A shoot
  that looks like it was made for somewhere else is the thing to avoid.
- Say what stays the brand's and what bends to the market. The weave, the craft and the story of
  where it is made are the brand's and never change. Styling, casting, language, festival and
  price framing bend.
- Write about the market's traditions as a brand that respects them, not as a visitor explaining
  them. No claim about a community's customs that you are not sure of: if a hook depends on a
  tradition, say in "say" that it should be checked with someone from that market before it runs.`
  : `\n\nNo market has been named for this campaign. Ask which market it is for before you write
copy or casting, because both change completely with it — it is the single thing that most changes
this campaign.`;

// What the brand actually sells. Written after looking at how the houses that
// do this well actually do it — Hermes makes the making itself the primary
// story and demonstrates the skill in public; Loro Piana explains the material
// and its provenance and puts the people who produce it on the page; both treat
// the channel as education rather than promotion, and neither discounts.
//
// The thing to avoid is the salesman's version: "took 100 hours". A duration is
// the floor of this, not the story. What the motif DEPICTS and what it has
// MEANT is the story, and in this craft that material is unusually rich.
const STORY = `WHAT THIS BRAND SELLS. Not an object, and not a number of hours. A buyer at this
price is buying meaning, and this craft has more of it than almost any other. Your job is to find
the specific, strange, true thing in the piece in front of you and build the campaign on that.

WHERE THE STORY COMES FROM, best first:

1. WHAT THE MOTIF DEPICTS AND HAS MEANT. This is the richest seam and it is usually ignored. A
   shikargah is a hunting ground — riders, deer mid-leap, tigers, parrots, woven into dense
   foliage, a whole forest in silk, and a motif that came into this tradition through Persia and
   the Mughal court. A jangla is a jungle: endless creeping vine, read as abundance and growth
   without end. A kairi is the mango-paisley, Persian in origin, read as fertility and life. A
   booti is a single blossom scattered across the field like a star. The naqsha is the hand-drawn
   graph the whole saree is woven from, made before a single thread is thrown.
   A buyer who learns that the thing she is wearing is a hunting forest, and that someone drew it
   on graph paper first, is a buyer who has been given something. START HERE.
2. WHAT IT IS WORN FOR. The occasion, the ritual, who gives it to whom, what it marks. A piece
   bought for a wedding, a first Diwali in a new house, a daughter's convocation is doing a job in
   someone's life, and the campaign can speak to that job.
3. THE PEOPLE AND THE PLACE. Varanasi, the lanes, the room-sized foot-powered loom inside the
   weaver's own house, the craft passing father to son, the families who hold a technique. Write
   them as skilled professionals the brand buys from — never "artisan" as decoration, never
   poverty framing, never saviour framing.
4. THE DIFFICULTY, AND ONLY THEN THE TIME. Kadhua, where each motif is woven and tied off
   individually rather than floated across the back, is genuinely harder and genuinely rarer, and
   THAT is why it takes what it takes. Lead with what makes it difficult; let the duration land
   afterwards as evidence. A duration on its own is what every seller on every marketplace says.

HOW TO WRITE IT:

- ONE STORY ACROSS THE CAMPAIGN. Decide what this campaign is about and let each post carry a
  different part of it, in an order that builds. Say what the spine is in "brief". Six posts about
  the same saree is not a campaign.
- TEACH SOMETHING IN EVERY POST. The channel is education, not promotion. If a post teaches the
  reader nothing she did not know, it is filler. A reader who learns to read a border, tell kadhua
  from a cutwork copy, or name what is woven into her own saree will remember who taught her.
- MOTIF LORE IS GENERAL KNOWLEDGE AND YOU MAY USE IT. What a shikargah is, where the paisley came
  from, what a naqsha does, how kadhua differs from fekua — these are facts about the tradition,
  not claims about this piece, and you may write them even when the piece's own story is not
  recorded. Where you are unsure of a point of lore, leave it out or say in "say" that it needs
  checking.
- WHAT IS SPECIFIC TO THIS PIECE MUST BE RECORDED. Every piece above either carries its story or
  says NOT RECORDED. You may never invent: a count of days or hours, a weaver's or family's name,
  a number of generations, a village, an age of a tradition, a GI claim, or "the last family who
  still...". Where you want that and it is not recorded, ask the owner for it in "say".
- BANNED WORDS in the copy, because they are what a brand writes when it has nothing true to say:
  exquisite, timeless, elegant, luxurious, heirloom, masterpiece, curated, handcrafted with love,
  epitome, unparalleled, regal, royal elegance.
- RESTRAINT IS THE REGISTER. No urgency, no countdowns, no "don't miss out", no emoji, no
  exclamation marks, no stacked hashtags. State an offer plainly once and let it sit. Never
  apologise for the price and never justify it with a discount: justify it with the work. Scarcity
  here is the scarcity of the skill, not a fake shortage of stock.
- OLD STORY, PRESENT TENSE. The heritage is the material, not the tone. Write it for someone
  scrolling now, not as a museum label.`;

// One campaign across every touchpoint the brand actually has, rather than six
// posts on Instagram. The owner asked for an omni-channel plan built on proper
// integrated marketing communications, and confirmed all four groups are live:
// Instagram, WhatsApp, email, and the website, showroom and parcel insert.
//
// The constraint that makes this real rather than a diagram: a WhatsApp message
// the brand starts has to use a template the provider approved in advance, and
// the workspace keeps its own quiet hours and a cap on marketing messages per
// week. A plan that ignores those cannot be executed, so the agent is told them.
const OMNI = (guards: string) => `ONE CAMPAIGN, EVERY TOUCHPOINT. Not a set of posts. The owner
works to integrated marketing communications, so a campaign is one idea carried across every place
a buyer meets this brand, with each place doing the job it is best at.

START FROM THE SPINE. Write one sentence — the spine — that is the whole campaign. Every
channel then says that same thing in its own way. If you cannot write the spine in one sentence,
the campaign is not one campaign yet and you should say so rather than papering over it with
channel ideas.

WHAT EACH PLACE IS FOR. Give each channel a job, and do not repeat one job in two places:

- Instagram feed — the piece itself, shot properly. This is the shop window and the first
  impression. Stills, close detail, the finished garment worn.
- Instagram reels — motion: the loom, the drape, the fall of the cloth, hands working. What a
  still cannot show.
- Instagram stories — the daily, unpolished thread between posts, and the only place a direct
  "ask me" belongs. Where someone raises a hand.
- WhatsApp — where a raised hand is answered and a sale closes. One to one, in the buyer's own
  time. Broadcast only to people who asked for it.
- Email — the long form. The one place with room for the whole story: the motif, the weave, the
  workshop, the provenance. Where a buyer who is already interested goes deeper.
- Website — where the campaign lands, and the one place every other channel points at. The page
  must say the same thing the campaign says; if it does not, name what needs changing on it.
- Showroom and in-person — the piece in the hand. Where the cloth does the arguing. Appointments
  and private viewings, invited from WhatsApp and email.
- Parcel insert — the last touchpoint and the most neglected. What goes in the box: the piece's
  own story, who made it, how to care for it. This is where a buyer becomes someone who tells
  other people, so it is part of the campaign, not packaging.

HANDOFFS, NOT BROADCASTS. For each channel say where someone goes next, and make sure those
handoffs form a path rather than a circle: discovery, then interest, then the conversation, then
the sale, then the parcel, then the telling. A channel with no next step is a dead end and should
be cut or given one.

${guards}

WHAT IS NOT YOURS TO INVENT. Only plan on a channel the brand has. Do not add a channel because it
would round out the plan — no print, no influencers, no events, no SMS, no YouTube, no pop-up
— unless the owner has raised it. If you think one is genuinely missing, say so in one line in
"say" and leave it out of the plan.`;

// The owner asked for the campaign to be held to the 6 C's of integrated
// marketing communications. The first four are Pickton and Broderick's;
// Communications and Compelling are the pair the six-C version adds.
//
// They are a check, not a template: the agent plans the campaign and then says
// where it is weak against each one. A self-check that always comes back "met"
// six times is worthless, so the agent is told to find the weak one.
const SIX_CS = `THE SIX C'S. The owner holds a campaign to these, so check your own plan against
them before you return it and report the result in "six_cs", one entry per C, in this order:

1. Coherence — do the channels you chose logically suit the message each one carries? A long
   provenance story does not belong in a story sticker, and a one-line ask does not belong in an
   email.
2. Consistency — do the messages reinforce each other rather than contradict? Watch for the
   plan that calls a piece rare in one place and discounts it in another.
3. Continuity — does this connect to what came before and what comes after? Name the earlier
   campaign or occasion it follows from if there is one, and what this one sets up next. A campaign
   that begins from nothing every time teaches a buyer nothing.
4. Complementary — does the whole add up to more than the parts? Each channel should make the
   next one land harder. If any channel could be removed without the campaign losing anything,
   that channel is decoration.
5. Communications — is every piece of it clear to someone who does not already know this craft?
   A buyer who has to look a word up has been lost. Clarity, not simplification.
6. Compelling — is there a reason to go and find out more? Say what the pull is. "Beautiful
   piece, buy it" is not a pull, and neither is a discount.

For each, set "verdict" to "met" or "weak" and write one short, specific line in "note". Be honest:
mark at least one weak unless the plan genuinely has no soft spot, and where you mark one weak, say
in that note what would fix it. The owner would rather read a real weakness than six ticks.`;

const RULES = (brand: string, mode: string, catalogue: string, search: boolean,
               market: string, occasions: string, guards: string,
               calendar: string) => `${brand}

You are this brand's campaign lead. You design one campaign at a time, in conversation with the
owner, for Instagram, Facebook and Meta ads. You are talking to the person who owns the business
and will spend the money, so be concrete and brief. No marketing throat-clearing, no "leverage",
no "elevate", no emoji in your own speech.

WHAT IS TRUE RIGHT NOW. Everything below is read from the owner's own workspace a moment ago. Use
only these pieces, these looks and these numbers. Never invent a product, a price, a stock figure,
a past result or a statistic. If you need a number you were not given — a conversion rate, a CPM,
what a competitor spends — say plainly that you do not have it and either ask or mark it as an
assumption inside your own text.

${catalogue}
${occasions}
${calendar}

${STORY}
${marketBlock(market)}

${OMNI(guards)}

${SIX_CS}

REVISING, NOT REDRAFTING. If a proposal has already been put to the owner in this conversation
and they are now asking for a change, change ONLY what they asked for and return everything else
exactly as it was — the same name, the same dates, the same posts, the same ad sets, word for word,
unless the change they asked for genuinely forces one of them to move. Say in one line in "say"
what you changed and what moved with it. Re-deciding the whole campaign because one line was
questioned loses the owner the work they already approved, and is the most annoying thing you
could do. Keep "options" as they were unless the change makes one of them wrong.

HOW YOU WORK THIS TURN: ${mode === "Interview"
  ? `Take the brief properly. Ask for ONE missing thing at a time, the one that most changes the
campaign, in "ask". Keep "proposal" null until you have the objective, roughly who it is for,
which pieces, and either a budget or a clear no-budget answer. Then set "ready" true and fill
"proposal". Do not ask about something the workspace above already tells you.`
  : `Draft first. Do not interview. Take whatever the owner has said, make sensible assumptions for
anything missing, and return a complete "proposal" this turn with "ready" true. State your
assumptions in "say" in one or two short lines so they can be corrected. "ask" stays null unless
something is genuinely impossible to assume.`}

Return only JSON of exactly this shape:
${SHAPE}

"say" is what you tell the owner: a few sentences, plain. When you are proposing, say what the
campaign does and the two or three judgements you made, not a summary of the fields below.
"options" is two or three genuinely different directions this campaign could take — different
stories, not the same story with different words. "spine" is the one-line story each is built on.
"why" is what makes it worth doing. "trade_off" is what it costs or risks, honestly: the one that
needs four new shoots says so, the one that leans on a tradition you are unsure of says so. Mark
exactly one "recommended" and say in "say" which you picked and why in one line. Then build THAT
one out in full in "proposal". The owner can ask for a different one, and then you build that
instead, keeping everything they have already approved.
"spine" is the one sentence the whole campaign says. Every channel repeats it differently.
"occasion" is the occasion from the calendar this campaign is built on, with its id, or null where
the campaign is not tied to one. Never invent an occasion that is not on the calendar above.
"channel_plan" is one entry per channel you are actually using, in the order a buyer meets them.
"role" is the job that channel does in THIS campaign, in one line, and no two channels share a job.
"cadence" is how often over the window. "first_move" is the concrete first thing to do there, the
kind of instruction someone could act on this afternoon. "hands_off_to" names where the person goes
next — the channel or step — and the last one in the path says so.
"six_cs" is your own check, six entries in the order given above.
"posts" are organic posts, 4 to 8 of them. Each carries a different part of the one story — the
material, the making, a detail worth looking at closely, the person who made it, how it is worn,
the offer — in an order that builds rather than repeats. "day_offset" counts days from the start,
from 0. "product_id" must be one of the ids above or null.
"art_direction" on a post is the shot: what is in frame and how, in one or two lines, consistent
with the campaign's own art direction.
"pieces" is the 6 to 10 pieces this campaign actually sells, chosen from the catalogue above —
not all of them, and never a piece with no stock. "why" is one short line saying what makes that
piece right for THIS market and this moment, in terms a buyer there would recognise. "imagery" is
read from what the catalogue says each piece already has: "ready" when its existing photographs
would carry the campaign, "needs a shoot" when it has none or only the owner's raw supplier
photographs, "worth reshooting" when it has images but they do not suit this campaign's direction.
Say in "say" how many need shooting, so the owner knows the work before they agree.
"casting" is who is in the pictures and how they are styled, written as a casting and styling note
a photographer could work from. Fit it to the market named above. Never describe anyone by skin
tone alone, and never write a stereotype: write the region, the styling and the occasion the way a
fashion house briefs a shoot — the drape, the jewellery, the hair, the flowers, the setting.
"look_id" is one of the look ids above when the campaign's imagery should follow a look, else null.
"ad_plan" is the paid half: two to four ad sets, each with who it targets and the copy for it.
Keep "primary_text" under 125 characters, "headline" under 40.
"measurement" names what to watch and what number would mean it worked, in one or two lines.

THE PAID HALF IS A DRAFT. This workspace is not connected to Meta, so nothing you write is
published and no money moves. The owner copies it into Ads Manager themselves. Never say or imply
that a campaign is live, running, launched or published.

${search ? `WHAT IS HAPPENING OUTSIDE. You can search the web this turn, so use it rather than
guessing at anything that moves: which festivals, weddings and sale moments fall in the window you
are planning for and on what dates; what is being worn and talked about in this market right now;
what format is working on Instagram at the moment; what Meta's ad products and placements currently
offer. Search before you commit to dates or to a hook. Two or three searches, not twenty.
Say in "say" what you found that changed the plan, and name the source in plain words. If a search
gives you nothing solid, say so rather than filling the gap with a plausible-sounding trend. Never
present something you read as this brand's own result.` : `You cannot search the web this turn, so
plan from the workspace above and say plainly where you are assuming something about timing or
trends that ought to be checked.`}

Prices are in the brand's currency. Dates are ISO (YYYY-MM-DD). Today is ${new Date().toISOString().slice(0, 10)}.`;

function flatten(system: string, messages: any[]) {
  return `${system}\n\n---\nThe conversation so far:\n`
    + messages.map((m) => `${m.role === "assistant" ? "You" : "The owner"}: ${m.content}`)
      .join("\n\n") + `\n\nAnswer with the JSON.`;
}

async function openaiChat(system: string, messages: any[], search: boolean) {
  if (search) {
    const res = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: { Authorization: `Bearer ${KEYS.openai}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODELS.openai, tools: [{ type: "web_search_preview" }],
        input: flatten(system, messages) }),
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
      messages: [{ role: "system", content: system }, ...messages] }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `OpenAI returned ${res.status}.`);
  return { data: parseJson(b.choices[0].message.content), usage: b.usage, model: MODELS.openai };
}

async function geminiChat(system: string, messages: any[], search: boolean) {
  const contents = messages.map((m) => ({
    role: m.role === "assistant" ? "model" : "user",
    parts: [{ text: m.content }],
  }));
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${MODELS.gemini}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({ contents, systemInstruction: { parts: [{ text: system }] },
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

async function claudeChat(system: string, messages: any[], search: boolean) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": KEYS.anthropic, "anthropic-version": "2023-06-01",
               "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.anthropic, max_tokens: 8000, system, messages,
      ...(search ? { tools: [{ type: "web_search_20250305", name: "web_search", max_uses: 5 }] } : {}) }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Claude returned ${res.status}.`);
  const text = (b.content ?? []).filter((c: any) => c.type === "text")
    .map((c: any) => c.text).join("\n");
  return { data: parseJson(text),
           usage: { prompt_tokens: b.usage?.input_tokens, completion_tokens: b.usage?.output_tokens },
           model: MODELS.anthropic };
}

async function openaiLike(url: string, key: string, model: string, system: string,
                          messages: any[], cap?: number, jsonMode = true) {
  const body: any = { model, messages: [{ role: "system", content: system }, ...messages] };
  if (jsonMode) body.response_format = { type: "json_object" };
  if (cap) body.max_completion_tokens = cap;
  const res = await fetch(url, { method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `The model returned ${res.status}.`);
  const choice = b.choices?.[0];
  if (choice?.finish_reason === "length") {
    throw new Error("The model ran out of output budget before finishing the campaign. "
      + "A campaign is a long answer — use Gemini, ChatGPT or Claude for this page.");
  }
  return { data: parseJson(choice.message.content), usage: b.usage, model };
}

async function ask(provider: string, system: string, messages: any[], search: boolean) {
  const live = search && CAN_SEARCH[provider];
  if (provider === "gemini") return geminiChat(system, messages, live);
  if (provider === "anthropic") return claudeChat(system, messages, live);
  if (provider === "groq") {
    // groq/compound searches; the plain model does not. Searching costs the
    // JSON mode, which is why parseJson pulls the object out of the text.
    return openaiLike("https://api.groq.com/openai/v1/chat/completions", KEYS.groq,
                      live ? GROQ_SEARCH : MODELS.groq, system, messages, GROQ_MAX, !live);
  }
  if (provider === "nvidia") {
    return openaiLike("https://integrate.api.nvidia.com/v1/chat/completions", KEYS.nvidia,
                      MODELS.nvidia, system, messages, undefined, true);
  }
  return openaiChat(system, messages, live);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = Deno.env.get("SUPABASE_URL")!;
  const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  let p: any = {};
  try { p = await req.json(); } catch { /* health */ }
  const action = p.action ?? "health";

  // The weekly briefing runs from the database on a schedule, with nobody
  // signed in. It is allowed only when the caller already holds the service
  // key, which nothing in the browser ever does.
  const bearer = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const internal = action === "briefing" && bearer === service && Boolean(service);

  if (!internal) {
    const asUser = createClient(url, anon, {
      global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } } });
    const { data: { user } } = await asUser.auth.getUser();
    if (!user) return json({ error: "Sign in first." }, 401);
  }
  const admin = createClient(url, service);

  if (action === "health") {
    const { settings } = await brandContext(admin);
    const w = await workspace(admin);
    return json({
      openai: Boolean(KEYS.openai), gemini: Boolean(KEYS.gemini),
      anthropic: Boolean(KEYS.anthropic), groq: Boolean(KEYS.groq), nvidia: Boolean(KEYS.nvidia),
      models: MODELS,
      brand_set: Boolean(settings.brand_name && settings.brand_sells),
      meta_connected: false, can_search: CAN_SEARCH,
      counts: { products: w.products.length, looks: w.looks.length, past: w.past.length },
    });
  }

  if (action !== "reply" && action !== "briefing") {
    return json({ error: `Unknown action "${action}".` }, 400);
  }

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
    kind: "campaign-agent", provider, status: "Running",
    request: { thread_id: p.thread_id ?? null, mode: p.mode ?? "Quick",
               turns: (p.messages ?? []).length },
  }).select("run_id").maybeSingle();
  const runId = started.data?.run_id;

  try {
    const w = await workspace(admin);
    const mode = p.mode === "Interview" ? "Interview" : "Quick";
    const wantSearch = p.search !== false;
    const history = (p.messages ?? []).slice(-14).map((m: any) => ({
      role: m.role === "agent" ? "assistant" : "user",
      content: String(m.body ?? "").slice(0, 4000),
    }));

    // Nobody asked for this one: it runs on a schedule and leaves a thread
    // behind for the owner to find.
    if (action === "briefing") {
      history.length = 0;
      history.push({ role: "user", content: BRIEFING_ASK });
    }
    if (!history.length) return json({ error: "Say what the campaign is for first." }, 400);

    // The market is set once on the thread and carried into every later turn,
    // so the owner does not have to repeat it.
    let market = String(p.market ?? "").trim().slice(0, 120);
    if (!market && p.thread_id) {
      const t = await admin.from("campaign_threads").select("market")
        .eq("thread_id", p.thread_id).maybeSingle();
      market = String(t.data?.market ?? "").trim();
    }
    if (market && p.thread_id) {
      await admin.from("campaign_threads").update({ market }).eq("thread_id", p.thread_id);
    }

    const out = await ask(provider,
                          RULES(brand, mode, catalogueLines(w), wantSearch, market,
                                occasionLines(w), guardLines(settings, w),
                                calendarLines(w)),
                          history, wantSearch);
    const d = out.data || {};

    if (runId) {
      await admin.from("ai_runs").update({
        status: "Done", model: out.model, response: d,
        tokens_in: out.usage?.prompt_tokens ?? out.usage?.promptTokenCount ?? null,
        tokens_out: out.usage?.completion_tokens ?? out.usage?.candidatesTokenCount ?? null,
      }).eq("run_id", runId);
    }

    // The ids the model hands back have to be real, or approval writes rubbish.
    const known = new Set(w.products.map((x: any) => x.product_id));
    const knownLooks = new Set(w.looks.map((x: any) => x.look_id));
    // Exactly one option is the recommendation: more than one, or none, and the
    // owner has nothing to decide from.
    if (Array.isArray(d.options) && d.options.length) {
      const all = d.options.filter(Boolean);
      // Trimming must never throw away the one it actually recommended, so the
      // recommendation leads and the rest follow in the order given.
      const pick = all.findIndex((o: any) => o?.recommended);
      const ordered = pick > 0 ? [all[pick], ...all.filter((_, i) => i !== pick)] : all;
      d.options = ordered.slice(0, 4);
      if (!d.options.some((o: any) => o?.recommended)) d.options[0].recommended = true;
      let seen = false;
      for (const o of d.options) {
        if (o?.recommended && seen) o.recommended = false;
        if (o?.recommended) seen = true;
      }
    } else {
      d.options = [];
    }

    if (d.proposal) {
      d.proposal.market = market || null;
      if (Array.isArray(d.proposal.pieces)) {
        d.proposal.pieces = d.proposal.pieces
          .filter((x: any) => known.has(x?.product_id))
          .slice(0, 12);
      } else {
        d.proposal.pieces = [];
      }
      d.proposal.posts = (d.proposal.posts ?? []).map((post: any) => ({
        ...post, product_id: known.has(post.product_id) ? post.product_id : null,
      }));
      if (!knownLooks.has(d.proposal.look_id)) d.proposal.look_id = null;
    }

    if (action === "briefing") {
      if (!d.proposal) {
        return json({ ok: true, skipped: true, say: d.say ?? "Nothing worth running this week." });
      }
      const thread = await admin.from("campaign_threads").insert({
        title: d.proposal.campaign_name || "Weekly suggestion",
        mode: "Quick", status: "Drafting", objective: d.proposal.objective ?? null,
        brief: { from: "weekly briefing" }, proposal: d.proposal,
      }).select("thread_id").maybeSingle();
      const threadId = thread.data?.thread_id;
      if (threadId) {
        await admin.from("campaign_messages").insert([
          { thread_id: threadId, role: "owner", body: "(weekly briefing — nobody asked)" },
          { thread_id: threadId, role: "agent", body: d.say ?? "", proposal: d.proposal,
            model: out.model },
        ]);
      }
      return json({ ok: true, thread_id: threadId, say: d.say ?? "",
                    options: d.options ?? [], proposal: d.proposal });
    }

    return json({ ok: true, provider, model: out.model,
                  say: d.say ?? "", ask: d.ask ?? null,
                  ready: Boolean(d.ready && d.proposal),
                  options: d.options ?? [], proposal: d.proposal ?? null });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (runId) {
      await admin.from("ai_runs").update({ status: "Failed", error: message }).eq("run_id", runId);
    }
    return json({ error: message }, 502);
  }
});
