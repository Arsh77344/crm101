import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { ...CORS, "Content-Type": "application/json" } });

const BASE = "https://apiv2.shiprocket.in/v1/external";
const EMAIL = Deno.env.get("SHIPROCKET_EMAIL") ?? "";
const PASSWORD = Deno.env.get("SHIPROCKET_PASSWORD") ?? "";
const PICKUP = Deno.env.get("SHIPROCKET_PICKUP_LOCATION") ?? "Primary";

// Shiprocket's token lifetime is documented inconsistently — 24 hours in one
// place, ten days in another — so it is cached with a conservative expiry and
// re-fetched the moment a call comes back unauthorised.
const TOKEN_HOURS = 20;

async function login() {
  if (!EMAIL || !PASSWORD) {
    throw new Error("No Shiprocket credentials. Add SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD to "
      + "this project's Edge Function secrets. They come from an API user in Shiprocket under "
      + "Settings > API > Configure, not from your own login.");
  }
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  const b = await res.json().catch(() => ({}));
  if (!res.ok || !b.token) {
    throw new Error(b?.message
      ? `Shiprocket would not sign in: ${b.message}`
      : `Shiprocket would not sign in (${res.status}). Check the API user's email and password.`);
  }
  return b.token as string;
}

async function tokenFor(admin: any) {
  const { data } = await admin.from("integrations").select("integration_id,config")
    .eq("provider", "Shiprocket").maybeSingle();
  const cfg = data?.config ?? {};
  const fresh = cfg.token && cfg.token_expires_at
    && new Date(cfg.token_expires_at).getTime() > Date.now();
  if (fresh) return { token: cfg.token as string, id: data.integration_id, cached: true };

  const token = await login();
  const expires = new Date(Date.now() + TOKEN_HOURS * 3600 * 1000).toISOString();
  await admin.from("integrations").update({
    status: "Connected", last_checked_at: new Date().toISOString(),
    config: { ...cfg, token, token_expires_at: expires },
  }).eq("provider", "Shiprocket");
  return { token, id: data?.integration_id, cached: false };
}

// Every call goes through here so a stale token is retried once, silently,
// instead of surfacing as a mysterious failure to the owner.
async function call(admin: any, method: string, path: string, body?: unknown, retry = true) {
  const { token } = await tokenFor(admin);
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (res.status === 401 && retry) {
    await admin.from("integrations")
      .update({ config: { token: null, token_expires_at: null } })
      .eq("provider", "Shiprocket");
    return call(admin, method, path, body, false);
  }
  const text = await res.text();
  let out: any = {};
  try { out = text ? JSON.parse(text) : {}; } catch { out = { raw: text }; }
  if (!res.ok) {
    const why = out?.message || out?.errors
      ? `${out.message ?? ""} ${JSON.stringify(out.errors ?? "")}`.trim()
      : `Shiprocket returned ${res.status}.`;
    throw new Error(why);
  }
  return out;
}

function missing(order: any, items: any[]) {
  const gaps: string[] = [];
  if (!order.ship_name) gaps.push("the name the parcel goes to");
  if (!order.ship_phone) gaps.push("a phone number");
  if (!order.ship_line1) gaps.push("a street address");
  if (!order.ship_city) gaps.push("a city");
  if (!order.ship_state) gaps.push("a state");
  if (!/^\d{6}$/.test(String(order.ship_pincode ?? ""))) gaps.push("a six-digit pincode");
  if (!items.length) gaps.push("at least one line item");
  if (!order.weight_kg) gaps.push("a parcel weight");
  return gaps;
}

async function orderWith(admin: any, orderId: string) {
  const [{ data: order }, { data: items }] = await Promise.all([
    admin.from("orders").select("*").eq("order_id", orderId).maybeSingle(),
    admin.from("order_items").select("*").eq("order_id", orderId),
  ]);
  if (!order) throw new Error("That order no longer exists.");
  return { order, items: items ?? [] };
}

function orderPayload(order: any, items: any[]) {
  return {
    order_id: order.order_number || order.order_id,
    order_date: (order.ordered_at ?? new Date().toISOString()).slice(0, 16).replace("T", " "),
    pickup_location: PICKUP,
    billing_customer_name: order.ship_name,
    billing_last_name: "",
    billing_address: order.ship_line1,
    billing_address_2: order.ship_line2 ?? "",
    billing_city: order.ship_city,
    billing_pincode: order.ship_pincode,
    billing_state: order.ship_state,
    billing_country: order.ship_country || "India",
    billing_email: order.ship_email ?? "",
    billing_phone: String(order.ship_phone ?? "").replace(/\D/g, "").slice(-10),
    shipping_is_billing: true,
    order_items: items.map((i: any) => ({
      name: i.name, sku: i.sku || String(i.product_id ?? "item").slice(0, 12),
      units: i.units, selling_price: Number(i.unit_price) || 0,
      discount: Number(i.discount) || 0, hsn: i.hsn ?? "",
    })),
    payment_method: order.payment_method === "COD" ? "COD" : "Prepaid",
    sub_total: Number(order.subtotal ?? order.total ?? 0),
    // Shiprocket wants centimetres and kilogrammes. A folded saree in a poly
    // bag is roughly this; the owner overrides the weight per order.
    length: 30, breadth: 24, height: 8,
    weight: Number(order.weight_kg) || 0.6,
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const url = Deno.env.get("SUPABASE_URL")!;
  const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  let p: any = {};
  try { p = await req.json(); } catch { /* health */ }
  const action = p.action ?? "health";

  const bearer = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const internal = action === "sync" && bearer === service && Boolean(service);
  if (!internal) {
    const asUser = createClient(url, anon, {
      global: { headers: { Authorization: req.headers.get("Authorization") ?? "" } } });
    const { data: { user } } = await asUser.auth.getUser();
    if (!user) return json({ error: "Sign in first." }, 401);
  }
  const admin = createClient(url, service);

  try {
    if (action === "health") {
      const configured = Boolean(EMAIL && PASSWORD);
      if (!configured) {
        return json({ configured: false, connected: false, pickup: PICKUP,
          note: "Add SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD to Edge Function secrets." });
      }
      try {
        const { cached } = await tokenFor(admin);
        return json({ configured: true, connected: true, pickup: PICKUP, token_cached: cached });
      } catch (e) {
        return json({ configured: true, connected: false, pickup: PICKUP,
                      error: e instanceof Error ? e.message : String(e) });
      }
    }

    // What it would cost and who can carry it, before anything is booked.
    if (action === "rates") {
      const { order, items } = await orderWith(admin, p.order_id);
      const gaps = missing(order, items);
      if (gaps.length) return json({ error: `This order still needs ${gaps.join(", ")}.` }, 400);
      const from = p.pickup_pincode ?? Deno.env.get("SHIPROCKET_PICKUP_PINCODE") ?? "";
      if (!/^\d{6}$/.test(from)) {
        return json({ error: "No pickup pincode. Set SHIPROCKET_PICKUP_PINCODE in Edge Function "
          + "secrets, or pass one." }, 400);
      }
      const cod = order.payment_method === "COD" ? 1 : 0;
      const q = `?pickup_postcode=${from}&delivery_postcode=${order.ship_pincode}`
        + `&weight=${Number(order.weight_kg) || 0.6}&cod=${cod}`;
      const out = await call(admin, "GET", `/courier/serviceability/${q}`);
      const couriers = (out?.data?.available_courier_companies ?? []).map((c: any) => ({
        courier_id: c.courier_company_id, name: c.courier_name,
        rate: c.rate, etd: c.etd, days: c.estimated_delivery_days,
        rating: c.rating, cod: c.cod,
      })).sort((a: any, b: any) => Number(a.rate) - Number(b.rate));
      return json({ ok: true, couriers });
    }

    // The whole booking, in the order Shiprocket wants it: order, AWB, pickup,
    // label. Each step records what it got, so a failure half way leaves the
    // shipment row telling the truth about how far it reached.
    if (action === "book") {
      const { order, items } = await orderWith(admin, p.order_id);
      const gaps = missing(order, items);
      if (gaps.length) return json({ error: `This order still needs ${gaps.join(", ")}.` }, 400);

      const existing = await admin.from("shipments").select("*")
        .eq("order_id", p.order_id).maybeSingle();
      if (existing.data?.awb) {
        return json({ error: `This order already has AWB ${existing.data.awb}.` }, 400);
      }

      const created = await call(admin, "POST", "/orders/create/adhoc",
                                 orderPayload(order, items));
      const srOrder = String(created.order_id ?? "");
      const srShipment = String(created.shipment_id ?? "");
      if (!srShipment) throw new Error("Shiprocket created no shipment for that order.");

      const row: Record<string, unknown> = {
        order_id: p.order_id, provider: "Shiprocket",
        sr_order_id: srOrder, sr_shipment_id: srShipment,
        status: "Created", booked_at: new Date().toISOString(),
        address_city: order.ship_city, address_country: order.ship_country || "India",
        weight_kg: Number(order.weight_kg) || 0.6, last_error: null,
      };
      const saved = existing.data
        ? await admin.from("shipments").update(row).eq("shipment_id", existing.data.shipment_id)
            .select().maybeSingle()
        : await admin.from("shipments").insert(row).select().maybeSingle();
      const shipmentId = saved.data?.shipment_id;

      const fail = async (stage: string, e: unknown) => {
        const message = `${stage}: ${e instanceof Error ? e.message : String(e)}`;
        if (shipmentId) {
          await admin.from("shipments").update({ last_error: message }).eq("shipment_id", shipmentId);
        }
        return json({ ok: true, partial: true, shipment_id: shipmentId,
                      sr_order_id: srOrder, sr_shipment_id: srShipment, error: message });
      };

      let awb = "", courier = "";
      try {
        const got = await call(admin, "POST", "/courier/assign/awb", {
          shipment_id: Number(srShipment),
          ...(p.courier_id ? { courier_id: Number(p.courier_id) } : {}),
        });
        const d = got?.response?.data ?? {};
        awb = String(d.awb_code ?? "");
        courier = String(d.courier_name ?? "");
        if (!awb) throw new Error(got?.message || "No AWB came back.");
      } catch (e) { return fail("The order was created but no courier would take it", e); }

      await admin.from("shipments").update({
        awb, courier, courier_id: p.courier_id ? String(p.courier_id) : null,
        status: "Booked", tracking_url: `https://shiprocket.co/tracking/${awb}`,
      }).eq("shipment_id", shipmentId);

      let pickup = null;
      try {
        pickup = await call(admin, "POST", "/courier/generate/pickup",
                            { shipment_id: [Number(srShipment)] });
        await admin.from("shipments").update({
          pickup_scheduled_at: new Date().toISOString(), status: "Pickup scheduled",
        }).eq("shipment_id", shipmentId);
      } catch (e) { await fail("Booked, but the pickup was not scheduled", e); }

      let label = null;
      try {
        const got = await call(admin, "POST", "/courier/generate/label",
                               { shipment_id: [Number(srShipment)] });
        label = got?.label_url ?? null;
        if (label) await admin.from("shipments").update({ label_url: label })
          .eq("shipment_id", shipmentId);
      } catch (e) { await fail("Booked, but the label was not generated", e); }

      await admin.from("orders").update({ order_status: "Processing" }).eq("order_id", p.order_id);

      return json({ ok: true, shipment_id: shipmentId, awb, courier,
                    label_url: label, pickup: Boolean(pickup) });
    }

    // Reads the courier's scans back in. Runs on demand and on a schedule.
    if (action === "track" || action === "sync") {
      const q = admin.from("shipments")
        .select("shipment_id,awb,status,order_id")
        .not("awb", "is", null);
      const { data } = action === "track"
        ? await q.eq("shipment_id", p.shipment_id)
        : await q.not("status", "in", '("Delivered","Cancelled","RTO")').limit(40);

      const seen: any[] = [];
      for (const s of data ?? []) {
        try {
          const out = await call(admin, "GET", `/courier/track/awb/${s.awb}`);
          const t = out?.tracking_data ?? out?.[s.awb!]?.tracking_data ?? {};
          const activities = t?.shipment_track_activities ?? [];
          const head = (t?.shipment_track ?? [])[0] ?? {};
          const status = String(head.current_status ?? t?.shipment_status ?? s.status ?? "Booked");
          const patch: Record<string, unknown> = {
            status, last_sync_at: new Date().toISOString(), last_error: null,
            checkpoints: activities.slice(0, 25),
          };
          if (/delivered/i.test(status)) patch.delivered_at = head.delivered_date ?? new Date().toISOString();
          if (/picked|transit|dispatch/i.test(status) ) patch.shipped_at = head.pickup_date ?? null;
          await admin.from("shipments").update(patch).eq("shipment_id", s.shipment_id);
          if (/delivered/i.test(status)) {
            await admin.from("orders").update({ order_status: "Fulfilled" }).eq("order_id", s.order_id);
          }
          seen.push({ shipment_id: s.shipment_id, awb: s.awb, status });
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          await admin.from("shipments").update({ last_error: message, last_sync_at: new Date().toISOString() })
            .eq("shipment_id", s.shipment_id);
          seen.push({ shipment_id: s.shipment_id, awb: s.awb, error: message });
        }
      }
      return json({ ok: true, checked: seen.length, shipments: seen });
    }

    if (action === "cancel") {
      const { data: s } = await admin.from("shipments").select("awb,sr_order_id,shipment_id")
        .eq("shipment_id", p.shipment_id).maybeSingle();
      if (!s?.awb) return json({ error: "That shipment has no AWB to cancel." }, 400);
      await call(admin, "POST", "/orders/cancel/shipment/awbs", { awbs: [s.awb] });
      await admin.from("shipments").update({ status: "Cancelled" }).eq("shipment_id", p.shipment_id);
      return json({ ok: true });
    }

    return json({ error: `Unknown action "${action}".` }, 400);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    return json({ error: message }, 502);
  }
});
