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
  const [products, collections, looks, past, orders] = await Promise.all([
    admin.from("products")
      .select("product_id,public_product_name,category,fabric,colour,weave_or_motif,retail_price,stock_qty,status")
      .eq("status", "Published").order("created_at", { ascending: false }).limit(40),
    admin.from("collections").select("collection_id,name,kind,description,status").limit(20),
    admin.from("looks").select("look_id,look_no,name,summary,source,use_for,status")
      .eq("status", "Ready").order("look_no").limit(30),
    admin.from("campaigns")
      .select("campaign_name,objective,channel,audience_type,budget,spend,start_date,end_date,offer")
      .order("created_at", { ascending: false }).limit(8),
    admin.from("orders").select("total,ordered_at,first_touch_campaign")
      .order("ordered_at", { ascending: false }).limit(60),
  ]);
  const p = products.data ?? [];
  const sold = (orders.data ?? []);
  const revenue = sold.reduce((n: number, o: any) => n + Number(o.total || 0), 0);
  return {
    products: p, collections: collections.data ?? [], looks: looks.data ?? [],
    past: past.data ?? [],
    trade: { orders: sold.length, revenue,
             average: sold.length ? Math.round(revenue / sold.length) : null },
  };
}

function catalogueLines(w: any) {
  const pieces = w.products.slice(0, 25).map((x: any) =>
    `- ${x.public_product_name} · ${[x.colour, x.fabric, x.weave_or_motif].filter(Boolean).join(", ")}`
    + ` · ${x.retail_price ?? "unpriced"} · ${x.stock_qty ?? 0} in stock [id ${x.product_id}]`).join("\n");
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
    "art_direction": string,
    "look_id": string | null,
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

const RULES = (brand: string, mode: string, catalogue: string, search: boolean) => `${brand}

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
"posts" are organic posts, 4 to 8 of them, each a different idea — detail, making, styling, the
offer, a customer-facing question. "day_offset" counts days from the start, from 0. "product_id"
must be one of the ids above or null.
"art_direction" on a post is the shot: what is in frame and how, in one or two lines, consistent
with the campaign's own art direction.
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

    const out = await ask(provider, RULES(brand, mode, catalogueLines(w), wantSearch), history,
                          wantSearch);
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
    if (d.proposal) {
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
      return json({ ok: true, thread_id: threadId, say: d.say ?? "", proposal: d.proposal });
    }

    return json({ ok: true, provider, model: out.model,
                  say: d.say ?? "", ask: d.ask ?? null,
                  ready: Boolean(d.ready && d.proposal), proposal: d.proposal ?? null });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (runId) {
      await admin.from("ai_runs").update({ status: "Failed", error: message }).eq("run_id", runId);
    }
    return json({ error: message }, 502);
  }
});
