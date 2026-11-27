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
// A customer reply is a short answer and there are a lot of them, so the default
// is the cheaper tier rather than the model the campaign studio uses.
const MODELS: Record<string, string> = {
  openai: Deno.env.get("WHATSAPP_OPENAI_MODEL") || "gpt-4o-mini",
  gemini: Deno.env.get("WHATSAPP_GEMINI_MODEL") || "gemini-3.8-flash",
  anthropic: Deno.env.get("WHATSAPP_ANTHROPIC_MODEL") || "claude-haiku-5-5",
  groq: Deno.env.get("WHATSAPP_GROQ_MODEL") || "qwen/qwen3.8-27b",
};
const LABEL: Record<string, string> = {
  openai: "ChatGPT", gemini: "Gemini", anthropic: "Claude", groq: "Groq",
};
const SECRET: Record<string, string> = {
  openai: "OPENAI_API_KEY", gemini: "GEMINI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY", groq: "GROQ_API_KEY",
};
const PROVIDERS = ["openai", "gemini", "anthropic", "groq"];

// Whether a message can actually leave this workspace. Until a number is
// attached there is no transport, and every outbound message is written down as
// ready rather than sent. Nothing in here may ever claim otherwise.
const HAS_TRANSPORT = Boolean(Deno.env.get("WHATSAPP_PHONE_NUMBER_ID")
                           && Deno.env.get("WHATSAPP_ACCESS_TOKEN"));

// Meta's webhook arrives with no signed-in user and no service key -- it
// authenticates by signing the body with the app secret. Verifying that is what
// stops anyone who learns the URL from posting fake customer messages into the
// inbox, so the real transport cannot be wired up without it.
async function signatureOk(raw: string, header: string | null, secret: string) {
  if (!secret || !header) return false;
  const got = header.replace(/^sha256=/i, "").trim().toLowerCase();
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(raw));
  const want = Array.from(new Uint8Array(mac))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
  if (got.length !== want.length) return false;
  // Compared without an early return, so the comparison itself leaks nothing.
  let diff = 0;
  for (let i = 0; i < want.length; i++) diff |= got.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

function parseJson(text: string): any {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const raw = fenced ? fenced[1] : text;
  const a = raw.indexOf("{"), b = raw.lastIndexOf("}");
  if (a === -1 || b === -1) throw new Error("The model did not return JSON.");
  return JSON.parse(raw.slice(a, b + 1));
}

const digits = (s: unknown) => String(s ?? "").replace(/[^0-9]/g, "");

// ---------------------------------------------------------------------------
// What arrives
// ---------------------------------------------------------------------------

// Two shapes come in here. Meta's Cloud API posts a nested envelope, and the
// test action posts a flat object. Normalising both at the edge means the rest
// of the function has one shape to reason about, and it also means the real
// webhook can be pointed at this function later without touching anything below.
function incoming(p: any): { from: string; name: string; text: string; id: string } | null {
  const flat = p.message ?? p;
  if (flat && typeof flat.text === "string" && (flat.from || flat.phone)) {
    return {
      from: digits(flat.from ?? flat.phone),
      name: String(flat.name ?? "").slice(0, 120),
      text: String(flat.text).slice(0, 4000),
      id: String(flat.wa_message_id ?? flat.id ?? "").slice(0, 200),
    };
  }
  const v = p?.entry?.[0]?.changes?.[0]?.value;
  const m = v?.messages?.[0];
  if (!m) return null;
  // A customer can send a sticker, an image or a location. There is no text to
  // answer, so it is written down and handed over rather than guessed at.
  const text = m.text?.body ?? m.button?.text ?? m.interactive?.list_reply?.title
    ?? m.interactive?.button_reply?.title ?? "";
  return {
    from: digits(m.from),
    name: String(v?.contacts?.[0]?.profile?.name ?? "").slice(0, 120),
    text: String(text).slice(0, 4000),
    id: String(m.id ?? "").slice(0, 200),
  };
}

// ---------------------------------------------------------------------------
// Who answers: decided before the model is asked
// ---------------------------------------------------------------------------

// The escalation decision is made here, in code, against the owner's own list.
// It is deliberately not left to the model: a model asked whether it feels able
// to answer will say yes, and the conversations that need a person are exactly
// the ones it will be confident about.
//
// A pattern matches on word boundaries, never as a bare substring: "eta" as a
// substring fires on "metallic zari", and a rule that escalates every mention
// of metallic zari is a rule the owner will switch off, taking the real
// deliveries question with it. A trailing * means match the word's start only,
// so "collaborat*" covers collaborate and collaboration without "custom*"
// quietly swallowing "customer".
function ruleHit(text: string, rows: any[]): { label: string; pattern: string } | null {
  const hay = text.toLowerCase().replace(/\s+/g, " ");
  for (const r of rows) {
    for (const pat of (r.patterns ?? [])) {
      const raw = String(pat ?? "").toLowerCase().trim();
      if (!raw) continue;
      const prefix = raw.endsWith("*");
      const word = (prefix ? raw.slice(0, -1) : raw).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (!word) continue;
      const re = new RegExp(`\\b${word}${prefix ? "" : "\\b"}`, "i");
      if (re.test(hay)) return { label: r.label, pattern: raw };
    }
  }
  return null;
}

const ORDER_TALK = /\b(?:where is my order|order status|track|tracking|shipped|dispatch|dispatched|courier|awb|parcel|delivered)\b/i;

// ---------------------------------------------------------------------------
// What may be said: enforced on the draft, not trusted to the prompt
// ---------------------------------------------------------------------------

// A price only exists if it is recorded against a piece. Anything else the model
// writes with a rupee sign next to it is an invention, and an invented price is
// the one mistake a customer will hold the brand to.
const PRICE_BEFORE = /(?:₹|rs\.?|rupees|inr|price(?:d at)?|costs?)\s*([0-9][0-9,]{2,})/gi;
const PRICE_AFTER = /([0-9][0-9,]{3,})\s*(?:₹|rs\.?|rupees|inr)\b/gi;

// Timing. The agent can read a parcel's tracking and say where it is; it may
// never say when something will arrive, because the complaint that follows a
// missed date is worse than the delay.
const TIMING = new RegExp(
  "\\b(?:with)?in\\s+\\d+\\s*(?:-\\s*\\d+\\s*)?(?:day|days|week|weeks|hour|hours)\\b"
  + "|\\bby\\s+(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\\b"
  + "|\\b(?:tomorrow|same day|next day|overnight)\\b"
  + "|\\b\\d{1,2}\\s*(?:st|nd|rd|th)?\\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
  "i");

const PROMISE = /\b(?:guarantee|guaranteed|i promise|we promise|rest assured|i assure|definitely will|100% sure|no doubt)\b/i;

// Returns a reason to hold, or null when the draft is safe to send. `prices` is
// every price actually recorded against a piece the draft was grounded on.
function railBreak(draft: string, prices: Set<string>, shippingNote: string): string | null {
  const said = new Set<string>();
  for (const re of [PRICE_BEFORE, PRICE_AFTER]) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(draft))) said.add(m[1].replace(/,/g, ""));
  }
  for (const n of said) {
    if (!prices.has(n)) {
      return `It wrote a price (${n}) that is not recorded against any piece in the catalogue.`;
    }
  }
  const t = draft.match(TIMING);
  // The one timing a brand may state is the one it has written down for itself.
  if (t && !(shippingNote && shippingNote.toLowerCase().includes(t[0].toLowerCase()))) {
    return `It promised a time ("${t[0].trim()}"). Only you can commit to a date.`;
  }
  const pr = draft.match(PROMISE);
  if (pr) return `It made a promise ("${pr[0]}") the business has not authorised.`;
  return null;
}

// ---------------------------------------------------------------------------
// What it is allowed to know
// ---------------------------------------------------------------------------

async function brandContext(admin: any) {
  const { data } = await admin.from("settings").select("setting_key,setting_value");
  const s: Record<string, string> = {};
  (data ?? []).forEach((r: any) => { s[r.setting_key] = r.setting_value ?? ""; });
  return {
    text: [
      s.brand_name ? `The brand is ${s.brand_name}.` : "",
      s.brand_sells ? `It sells: ${s.brand_sells}` : "",
      s.brand_voice ? `How it writes: ${s.brand_voice}` : "",
      s.storefront_url ? `Its storefront: ${s.storefront_url}` : "",
      s.default_currency ? `It prices in ${s.default_currency}.` : "",
      s.shipping_note ? `Its own recorded shipping note: ${s.shipping_note}` : "",
    ].filter(Boolean).join("\n"),
    settings: s,
  };
}

async function catalogue(admin: any) {
  const { data } = await admin.from("products")
    .select("product_id,public_product_name,category,fabric,colour,weave_or_motif,"
      + "retail_price,stock_qty,story,brands(name,city)")
    .eq("status", "Published").order("created_at", { ascending: false }).limit(40);
  return data ?? [];
}

function catalogueLines(rows: any[]) {
  if (!rows.length) return "Nothing is published in the catalogue, so there is nothing to offer.";
  return rows.map((x: any) =>
    `- ${x.public_product_name} · ${[x.category, x.colour, x.fabric, x.weave_or_motif]
      .filter(Boolean).join(", ")}`
    + ` · price ${x.retail_price ?? "NOT RECORDED"}`
    + ` · ${Number(x.stock_qty ?? 0) > 0 ? `${x.stock_qty} available` : "OUT OF STOCK"}`
    + (x.brands?.name ? ` · made by ${x.brands.name}${x.brands.city ? `, ${x.brands.city}` : ""}` : "")
    + (x.story ? `\n    its story (recorded, true): ${x.story}` : `\n    its story: NOT RECORDED`))
    .join("\n");
}

// Where a parcel actually is, for a customer who asks. Read rather than guessed,
// and if there is nothing to read the conversation goes to the owner instead of
// the agent inventing reassurance.
async function orderLines(admin: any, contactId: string | null) {
  if (!contactId) return { text: "", found: false };
  const { data } = await admin.from("orders")
    .select("order_id,order_number,order_status,total,ordered_at,"
      + "shipments(courier,awb,status,tracking_url,shipped_at,delivered_at)")
    .eq("contact_id", contactId).order("ordered_at", { ascending: false }).limit(3);
  const rows = data ?? [];
  if (!rows.length) return { text: "", found: false };
  const text = rows.map((o: any) => {
    const s = (o.shipments ?? [])[0];
    return `- order ${o.order_number ?? o.order_id} · ${o.order_status} · ${o.total}`
      + ` · placed ${String(o.ordered_at ?? "").slice(0, 10)}`
      + (s ? `\n    parcel: ${s.courier ?? "courier not set"}`
             + `${s.awb ? `, tracking ${s.awb}` : ", no tracking number yet"}`
             + ` · ${s.status ?? "status not set"}`
             + (s.tracking_url ? `\n    they can follow it at ${s.tracking_url}` : "")
             + (s.delivered_at ? ` · delivered ${String(s.delivered_at).slice(0, 10)}` : "")
           : `\n    no parcel booked yet`);
  }).join("\n");
  return { text: `\nTHIS CUSTOMER'S OWN ORDERS, read from the workspace just now:\n${text}`,
           found: true };
}

async function historyLines(admin: any, conversationId: string) {
  const { data } = await admin.from("conversation_messages")
    .select("direction,body,created_at,status")
    .eq("conversation_id", conversationId).order("created_at").limit(20);
  const rows = (data ?? []).filter((m: any) => m.status !== "Held");
  if (!rows.length) return "This is their first message.";
  return rows.map((m: any) =>
    `${m.direction === "in" ? "Customer" : "You"}: ${m.body}`).join("\n");
}

// ---------------------------------------------------------------------------
// The brief
// ---------------------------------------------------------------------------

const VOICE = `HOW TO WRITE. You are answering on WhatsApp, as the brand, to one person.

- Short. Two or three sentences. This is a chat, not an email, and nobody reads a paragraph here.
- Warm and plain. No sales pressure, no urgency, no emoji, no exclamation marks, no "dear customer".
- English. The owner has decided this and it is not yours to revisit. If the customer wrote in
  another language or in a mix, still answer in plain English, simply enough to be easy to read.
- Answer the question that was asked. Do not add an offer, a second piece or a closing push.
- TEACH ONE SMALL THING when it fits naturally. What a motif depicts, how a weave differs, how to
  tell real zari. One line, not a lecture, and only where it answers what they asked.
- BANNED WORDS: exquisite, timeless, elegant, luxurious, heirloom, masterpiece, curated,
  handcrafted with love, regal.`;

const LIMITS = `WHAT YOU MAY NOT DO. These are checked after you answer, and a reply that breaks
one of them is stopped and handed to the owner, so breaking one simply wastes the customer's time:

- NEVER state a price that is not recorded above against that exact piece. If a piece shows price
  NOT RECORDED, say you will confirm the price and set "escalate" true.
- NEVER say when something will arrive, ship or be delivered. Not a date, not "in 3-4 days", not
  "by Friday", not "before the festival". You may say where a parcel is if it is read above, and
  you may say you will confirm the timing. Nothing more.
- NEVER promise, guarantee or assure anything.
- NEVER invent a piece, a fabric, a colour, a stock figure, a weaver, a village, a number of days
  on the loom or a GI claim. Everything specific must be above. Motif and weave lore in general is
  fine; a claim about THIS piece must be recorded.
- NEVER agree to a return, an exchange, a cancellation, a refund, a discount, a custom order or a
  collaboration, even in principle, even softly.
- NEVER say or imply that you are a person. If asked, say plainly that you help with quick
  questions and the owner will reply himself. Do not pretend, and do not apologise at length.

WHEN YOU CANNOT ANSWER WELL, SET "escalate" TRUE and write one line in "escalate_why". That is not
a failure: it is the point. The owner would much rather answer ten himself than have one customer
told something untrue. Set it whenever the honest answer needs a decision, a price you do not have,
a date, or anything above.`;

const SHAPE = `{
  "reply": string,
  "escalate": boolean,
  "escalate_why": string | null,
  "topic": string,
  "used_product_ids": [string]
}`;

const RULES = (brand: string, cat: string, orders: string, history: string,
               windowLeft: number) => `${brand}

You answer this brand's WhatsApp messages. You are talking to a customer, one to one, right now.

WHAT IS TRUE RIGHT NOW. Everything below was read from the owner's own workspace a moment ago. It
is the only thing you know. You cannot search the web, you cannot look anything up, and you cannot
check with anyone before you answer.

The catalogue, published and sellable:
${cat}
${orders}

The conversation so far:
${history}

${VOICE}

${LIMITS}

"topic" is what this conversation is about, three or four words, for the owner's list.
"used_product_ids" is every piece id you relied on, so a wrong answer can be traced to what you
were reading. Leave it empty if you relied on none.
${windowLeft > 0
  ? `You have ${windowLeft} minutes left in which a free reply is allowed, which is plenty.`
  : `The free-reply window has closed, so set "escalate" true whatever the question is.`}

Return only JSON of exactly this shape:
${SHAPE}`;

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

async function openaiCall(system: string, user: string) {
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

async function geminiCall(system: string, user: string) {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${MODELS.gemini}:generateContent`,
    { method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": KEYS.gemini },
      body: JSON.stringify({
        contents: [{ role: "user", parts: [{ text: `${system}\n\n---\nThe customer just said: ${user}\n\nAnswer with the JSON.` }] }] }) });
  const b = await res.json();
  if (!res.ok) {
    const m = b?.error?.message || `Gemini returned ${res.status}.`;
    throw new Error(res.status === 404
      ? `${m} The model name "${MODELS.gemini}" may have been retired — set WHATSAPP_GEMINI_MODEL.` : m);
  }
  const text = (b.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("\n");
  return { data: parseJson(text), usage: b.usageMetadata, model: MODELS.gemini };
}

async function claudeCall(system: string, user: string) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": KEYS.anthropic, "anthropic-version": "2023-06-01",
               "Content-Type": "application/json" },
    body: JSON.stringify({ model: MODELS.anthropic, max_tokens: 1200, system,
      messages: [{ role: "user", content: user }] }),
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
    body: JSON.stringify({ model: MODELS.groq, response_format: { type: "json_object" },
      messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
  });
  const b = await res.json();
  if (!res.ok) throw new Error(b?.error?.message || `Groq returned ${res.status}.`);
  return { data: parseJson(b.choices[0].message.content), usage: b.usage, model: MODELS.groq };
}

function ask(provider: string, system: string, user: string) {
  if (provider === "gemini") return geminiCall(system, user);
  if (provider === "anthropic") return claudeCall(system, user);
  if (provider === "groq") return groqCall(system, user);
  return openaiCall(system, user);
}

// ---------------------------------------------------------------------------

async function escalate(admin: any, id: string, rule: string, note: string) {
  await admin.from("conversations").update({
    escalated: true, status: "Needs you", escalation_rule: rule,
    escalation_note: note, escalated_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }).eq("conversation_id", id);
}

// Every outbound message goes through here, so there is exactly one place that
// decides what "sent" means. Until a number is attached nothing is sent, and
// nothing in this function is allowed to pretend otherwise.
async function putOut(admin: any, conversationId: string, body: string,
                      writtenBy: string, grounded: unknown, ruleHitLabel: string | null) {
  const status = HAS_TRANSPORT ? "Sent" : "Ready to send";
  const held = HAS_TRANSPORT ? null
    : "No WhatsApp number is connected yet, so this was written but not sent.";
  const { data } = await admin.from("conversation_messages").insert({
    conversation_id: conversationId, direction: "out", body, status,
    held_reason: held, written_by: writtenBy, grounded_on: grounded ?? {},
    rule_hit: ruleHitLabel, sent_at: HAS_TRANSPORT ? new Date().toISOString() : null,
  }).select("message_id").maybeSingle();
  await admin.from("conversations").update({
    last_out_at: new Date().toISOString(), unanswered: 0,
    updated_at: new Date().toISOString(),
  }).eq("conversation_id", conversationId);
  return { message_id: data?.message_id ?? null, status, held_reason: held };
}

async function hold(admin: any, conversationId: string, body: string,
                    reason: string, writtenBy: string) {
  await admin.from("conversation_messages").insert({
    conversation_id: conversationId, direction: "out", body,
    status: "Held", held_reason: reason, written_by: writtenBy,
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = Deno.env.get("SUPABASE_URL")!;
  const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  // Meta subscribes by asking for its own token back, once, over GET.
  if (req.method === "GET") {
    const q = new URL(req.url).searchParams;
    const token = Deno.env.get("WHATSAPP_VERIFY_TOKEN") ?? "";
    if (q.get("hub.mode") === "subscribe" && token && q.get("hub.verify_token") === token) {
      return new Response(q.get("hub.challenge") ?? "", { headers: { ...CORS } });
    }
    return json({ error: "Not subscribed." }, 403);
  }

  // Read once as text: the signature is over the exact bytes, so parsing first
  // and re-serialising would compute it over something else.
  const raw = await req.text();
  let p: any = {};
  try { p = JSON.parse(raw); } catch { /* health */ }
  const action = p.action ?? "health";
  const admin = createClient(url, service);

  // Three ways to be allowed in, in the order they are cheap to check: the
  // service key (the scheduler and anything server-side), Meta's own signature
  // (the live webhook), or a signed-in user (the browser).
  const bearer = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const hasService = bearer === service && Boolean(service);
  const signed = action === "receive" && await signatureOk(
    raw, req.headers.get("x-hub-signature-256"), Deno.env.get("WHATSAPP_APP_SECRET") ?? "");
  const internal = (action === "receive" && hasService) || signed;

  if (!internal) {
    const asUser = createClient(url, anon, {
      global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } } });
    const { data: { user } } = await asUser.auth.getUser();
    if (!user) return json({ error: "Sign in first." }, 401);
  }

  if (action === "health") {
    const { settings } = await brandContext(admin);
    const { count } = await admin.from("escalation_topics")
      .select("topic_id", { count: "exact", head: true }).eq("active", true);
    return json({
      openai: Boolean(KEYS.openai), gemini: Boolean(KEYS.gemini),
      anthropic: Boolean(KEYS.anthropic), groq: Boolean(KEYS.groq),
      models: MODELS,
      transport: HAS_TRANSPORT ? "connected" : "none",
      brand_set: Boolean(settings.brand_name && settings.brand_sells),
      active_rules: count ?? 0,
    });
  }

  // The owner answering an escalated conversation himself.
  if (action === "answer") {
    const body = String(p.body ?? "").trim().slice(0, 4000);
    if (!p.conversation_id || !body) {
      return json({ error: "Which conversation, and what do you want to say?" }, 400);
    }
    const out = await putOut(admin, p.conversation_id, body, "owner", {}, null);
    await admin.from("conversations").update({
      escalated: false, status: "Waiting on customer",
      escalation_rule: null, escalation_note: null,
      updated_at: new Date().toISOString(),
    }).eq("conversation_id", p.conversation_id);
    return json({ ok: true, ...out, transport: HAS_TRANSPORT ? "connected" : "none" });
  }

  if (action === "close") {
    if (!p.conversation_id) return json({ error: "Which conversation?" }, 400);
    await admin.from("conversations").update({
      status: "Closed", escalated: false, updated_at: new Date().toISOString(),
    }).eq("conversation_id", p.conversation_id);
    return json({ ok: true });
  }

  if (action !== "receive" && action !== "test") {
    return json({ error: `Unknown action "${action}".` }, 400);
  }

  const msg = incoming(p);
  if (!msg || !msg.from) {
    // A status callback, or a sticker with nothing to read. Acknowledged so the
    // provider stops retrying, and ignored.
    return json({ ok: true, ignored: "Nothing in that payload to answer." });
  }

  const isTest = action === "test";
  const now = new Date().toISOString();

  // One conversation per number. The unique index does the work, so two webhooks
  // arriving at once cannot create two threads for the same person.
  const found = await admin.from("conversations").select("*")
    .eq("wa_phone", msg.from).eq("channel", "WhatsApp").eq("is_test", isTest).maybeSingle();
  let convo = found.data;
  if (!convo) {
    const contact = await admin.from("contacts").select("contact_id")
      .ilike("phone_number", `%${msg.from.slice(-10)}`).limit(1).maybeSingle();
    const made = await admin.from("conversations").insert({
      wa_phone: msg.from, wa_name: msg.name || null, is_test: isTest,
      contact_id: contact.data?.contact_id ?? null, last_in_at: now,
    }).select("*").maybeSingle();
    convo = made.data;
    if (!convo) {
      const again = await admin.from("conversations").select("*")
        .eq("wa_phone", msg.from).eq("channel", "WhatsApp").eq("is_test", isTest).maybeSingle();
      convo = again.data;
    }
  }
  if (!convo) return json({ error: "Could not open a conversation for that number." }, 500);

  // Idempotency. A provider that does not get a fast 200 sends the same message
  // again, and the unique index on wa_message_id is what stops a second answer.
  if (msg.id) {
    const seen = await admin.from("conversation_messages").select("message_id")
      .eq("wa_message_id", msg.id).maybeSingle();
    if (seen.data) {
      return json({ ok: true, already_seen: true, conversation_id: convo.conversation_id });
    }
  }

  if (!msg.text.trim()) {
    await admin.from("conversation_messages").insert({
      conversation_id: convo.conversation_id, direction: "in",
      body: "(a message with nothing to read — a sticker, an image or a location)",
      wa_message_id: msg.id || null,
    });
    // A sticker still starts the 24-hour clock, so the owner's own reply later
    // is inside the window rather than wrongly needing a template.
    await admin.from("conversations").update({
      last_in_at: now, wa_name: msg.name || convo.wa_name,
      status: convo.status === "Closed" ? "Open" : convo.status, updated_at: now,
    }).eq("conversation_id", convo.conversation_id);
    await escalate(admin, convo.conversation_id, "Nothing to read",
      "They sent something that is not text, so it needs your eyes.");
    return json({ ok: true, conversation_id: convo.conversation_id, escalated: true,
                  rule: "Nothing to read" });
  }

  const unanswered = Number(convo.unanswered ?? 0) + 1;
  const landed = await admin.from("conversation_messages").insert({
    conversation_id: convo.conversation_id, direction: "in", body: msg.text,
    wa_message_id: msg.id || null,
  }).select("message_id").maybeSingle();
  const inboundId = landed.data?.message_id ?? null;
  await admin.from("conversations").update({
    last_in_at: now, unanswered, wa_name: msg.name || convo.wa_name,
    status: convo.status === "Closed" ? "Open" : convo.status,
    updated_at: now,
  }).eq("conversation_id", convo.conversation_id);

  const reply = (extra: Record<string, unknown>) =>
    json({ ok: true, conversation_id: convo.conversation_id, is_test: isTest,
           transport: HAS_TRANSPORT ? "connected" : "none", ...extra });

  // 1. The owner's own list, before any model is involved.
  const topics = await admin.from("escalation_topics")
    .select("label,patterns").eq("active", true).order("sort_order");
  const hit = ruleHit(msg.text, topics.data ?? []);
  if (hit) {
    // Stamped on the row by its own id. `update()` takes no order or limit, so
    // "the latest inbound message" is not a thing it can be asked for.
    if (inboundId) {
      await admin.from("conversation_messages")
        .update({ rule_hit: hit.label }).eq("message_id", inboundId);
    }
    await escalate(admin, convo.conversation_id, hit.label,
      `Matched "${hit.pattern}" in your ${hit.label} rule.`);
    return reply({ escalated: true, rule: hit.label, matched: hit.pattern, drafted: false });
  }

  // 2. The same question twice with no answer is its own reason.
  if (unanswered >= 3) {
    await escalate(admin, convo.conversation_id, "Asked more than once",
      `${unanswered} messages in with no answer out. Worth your eyes.`);
    return reply({ escalated: true, rule: "Asked more than once", drafted: false });
  }

  // 3. An order question with no order behind it.
  const orders = await orderLines(admin, convo.contact_id);
  if (ORDER_TALK.test(msg.text) && !orders.found) {
    await escalate(admin, convo.conversation_id, "Order I cannot find",
      "They are asking about an order, and this number is not on one in the workspace.");
    return reply({ escalated: true, rule: "Order I cannot find", drafted: false });
  }

  const provider = PROVIDERS.includes(p.provider) ? p.provider : "openai";
  if (!KEYS[provider]) {
    await escalate(admin, convo.conversation_id, "No model available",
      `No ${LABEL[provider]} key is set, so nothing could be drafted.`);
    return reply({ escalated: true, rule: "No model available",
                   error: `Add ${SECRET[provider]} to this project's Edge Function secrets.` });
  }

  const { text: brand, settings } = await brandContext(admin);
  if (!settings.brand_name || !settings.brand_sells) {
    await escalate(admin, convo.conversation_id, "Brand not set up",
      "The brand name and what it sells are empty on the Settings page, so nothing was drafted.");
    return reply({ escalated: true, rule: "Brand not set up" });
  }

  const started = await admin.from("ai_runs").insert({
    kind: "whatsapp-agent", provider, status: "Running",
    request: { conversation_id: convo.conversation_id, is_test: isTest },
  }).select("run_id").maybeSingle();
  const runId = started.data?.run_id;

  try {
    const pieces = await catalogue(admin);
    const history = await historyLines(admin, convo.conversation_id);
    // Read from the view so the page and this function cannot disagree about
    // whether a free reply is still allowed.
    const state = await admin.from("conversation_state")
      .select("window_open,window_minutes_left")
      .eq("conversation_id", convo.conversation_id).maybeSingle();
    const left = Number(state.data?.window_minutes_left ?? 0);

    // 4. Outside 24 hours a free-text reply is not permitted at all, whatever
    //    the question was. It takes an approved template, which is the owner's.
    if (!state.data?.window_open) {
      await escalate(admin, convo.conversation_id, "Window closed",
        "Their last message is more than 24 hours old, so a free reply is not allowed. "
        + "It needs an approved template.");
      if (runId) await admin.from("ai_runs").update({ status: "Done", response: { skipped: "window closed" } }).eq("run_id", runId);
      return reply({ escalated: true, rule: "Window closed", drafted: false });
    }

    const system = RULES(brand, catalogueLines(pieces), orders.text, history, left);
    const out = await ask(provider, system, msg.text);
    const d = out.data || {};
    const draft = String(d.reply ?? "").trim();

    if (runId) {
      await admin.from("ai_runs").update({
        status: "Done", model: out.model, response: d,
        tokens_in: out.usage?.prompt_tokens ?? out.usage?.promptTokenCount ?? null,
        tokens_out: out.usage?.completion_tokens ?? out.usage?.candidatesTokenCount ?? null,
      }).eq("run_id", runId);
    }

    const usedIds = (Array.isArray(d.used_product_ids) ? d.used_product_ids : [])
      .filter((id: any) => pieces.some((x: any) => x.product_id === id));
    if (d.topic) {
      await admin.from("conversations")
        .update({ topic: String(d.topic).slice(0, 120) })
        .eq("conversation_id", convo.conversation_id);
    }

    if (!draft) {
      await escalate(admin, convo.conversation_id, "Nothing drafted",
        "The model returned no reply.");
      return reply({ escalated: true, rule: "Nothing drafted" });
    }

    // 5. It said itself that it should not answer. Believe it when it says no;
    //    the rails below are for when it says yes.
    if (d.escalate) {
      await hold(admin, convo.conversation_id, draft,
        `It handed this over itself: ${d.escalate_why || "no reason given"}`, out.model);
      await escalate(admin, convo.conversation_id, "Handed over by the agent",
        String(d.escalate_why || "It did not think it should answer this one.").slice(0, 500));
      return reply({ escalated: true, rule: "Handed over by the agent",
                     why: d.escalate_why ?? null, draft, drafted: true, sent: false });
    }

    // 6. The rails. Checked on the finished draft, because a model that has been
    //    told not to invent a price will still occasionally invent one.
    const prices = new Set<string>();
    pieces.forEach((x: any) => {
      if (x.retail_price !== null && x.retail_price !== undefined) {
        prices.add(String(x.retail_price).replace(/,/g, "").replace(/\.00$/, ""));
      }
    });
    const broke = railBreak(draft, prices, settings.shipping_note ?? "");
    if (broke) {
      await hold(admin, convo.conversation_id, draft, broke, out.model);
      await escalate(admin, convo.conversation_id, "Stopped by a rail", broke);
      return reply({ escalated: true, rule: "Stopped by a rail", why: broke,
                     draft, drafted: true, sent: false });
    }

    const put = await putOut(admin, convo.conversation_id, draft, out.model,
                             { product_ids: usedIds }, null);
    await admin.from("conversations").update({
      status: "Waiting on customer", updated_at: new Date().toISOString(),
    }).eq("conversation_id", convo.conversation_id);
    return reply({ escalated: false, drafted: true, draft, ...put,
                   model: out.model, used_product_ids: usedIds });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (runId) {
      await admin.from("ai_runs").update({ status: "Failed", error: message }).eq("run_id", runId);
    }
    await escalate(admin, convo.conversation_id, "Something broke",
      `Nothing was sent: ${message}`);
    return reply({ escalated: true, rule: "Something broke", error: message });
  }
});
