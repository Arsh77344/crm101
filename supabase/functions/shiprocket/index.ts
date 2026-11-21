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
// A fallback for stock the brand of which is unknown. Every vendor has their
// own pickup point; this is only for pieces with no brand against them.
const FALLBACK_PICKUP = Deno.env.get("SHIPROCKET_PICKUP_LOCATION") ?? "Primary";
const FALLBACK_PINCODE = Deno.env.get("SHIPROCKET_PICKUP_PINCODE") ?? "";

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
    admin.from("order_items")
      .select("*,products(product_id,brand_id,public_product_name,internal_sku,"
        + "brands(brand_id,name,pickup_nickname,pickup_pincode,pickup_registered_at))")
      .eq("order_id", orderId),
  ]);
  if (!order) throw new Error("That order no longer exists.");
  return { order, items: items ?? [] };
}

// One parcel per vendor. An order holding two vendors' pieces is two parcels
// from two addresses, and pretending otherwise means a courier turns up at the
// wrong door.
function byVendor(items: any[]) {
  const groups = new Map<string, any>();
  for (const i of items) {
    const brand = i.products?.brands ?? null;
    const id = brand?.brand_id ?? "none";
    const g = groups.get(id) ?? {
      brand_id: brand?.brand_id ?? null,
      brand_name: brand?.name ?? "No vendor on these pieces",
      pickup: brand?.pickup_nickname ?? null,
      pickup_pincode: brand?.pickup_pincode ?? null,
      registered: Boolean(brand?.pickup_registered_at),
      items: [] as any[],
    };
    g.items.push(i);
    groups.set(id, g);
  }
  return [...groups.values()];
}

function vendorGaps(g: any) {
  const gaps: string[] = [];
  if (!g.brand_id) {
    gaps.push("these pieces have no vendor against them, so there is no pickup address");
    return gaps;
  }
  if (!g.pickup) gaps.push(`${g.brand_name} has no Shiprocket pickup name`);
  else if (!g.registered) gaps.push(`${g.brand_name}'s pickup address is not registered with Shiprocket yet`);
  if (!/^\d{6}$/.test(String(g.pickup_pincode ?? ""))) {
    gaps.push(`${g.brand_name} has no six-digit pickup pincode`);
  }
  return gaps;
}

function orderPayload(order: any, items: any[], pickup: string, suffix: string) {
  return {
    // Shiprocket keys on this, so two parcels from one order need two ids.
    order_id: `${order.order_number || order.order_id}${suffix}`,
    order_date: (order.ordered_at ?? new Date().toISOString()).slice(0, 16).replace("T", " "),
    pickup_location: pickup,
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
      name: i.name || i.products?.public_product_name || "Piece",
      sku: i.sku || i.products?.internal_sku || String(i.product_id ?? "item").slice(0, 12),
      units: i.quantity, selling_price: Number(i.unit_price) || 0,
      discount: Number(i.discount) || 0, hsn: i.hsn ?? "",
    })),
    payment_method: order.payment_method === "COD" ? "COD" : "Prepaid",
    // What is in this parcel, not what the whole order came to.
    sub_total: items.reduce((n: number, i: any) =>
      n + (Number(i.unit_price) || 0) * (Number(i.quantity) || 0) - (Number(i.discount) || 0), 0),
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
      // Pickup readiness is now per vendor, so health counts how many vendors
      // have an address Shiprocket knows about rather than naming one point.
      const { data: brands } = await admin.from("brands")
        .select("brand_id,name,pickup_nickname,pickup_registered_at");
      const all = brands ?? [];
      const ready = all.filter((b: any) => b.pickup_nickname && b.pickup_registered_at);
      const pickups = {
        vendors: all.length, registered: ready.length,
        waiting: all.filter((b: any) => !b.pickup_nickname || !b.pickup_registered_at)
                    .map((b: any) => b.name),
        fallback: FALLBACK_PICKUP,
      };
      const configured = Boolean(EMAIL && PASSWORD);
      if (!configured) {
        return json({ configured: false, connected: false, pickups,
          note: "Add SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD to Edge Function secrets." });
      }
      try {
        const { cached } = await tokenFor(admin);
        return json({ configured: true, connected: true, pickups, token_cached: cached });
      } catch (e) {
        return json({ configured: true, connected: false, pickups,
                      error: e instanceof Error ? e.message : String(e) });
      }
    }

    // Which vendors an order spans, and whether each can actually be shipped.
    if (action === "vendors") {
      const { order, items } = await orderWith(admin, p.order_id);
      const groups = byVendor(items).map((g) => ({
        brand_id: g.brand_id, brand_name: g.brand_name, pickup: g.pickup,
        pickup_pincode: g.pickup_pincode, registered: g.registered,
        lines: g.items.length,
        units: g.items.reduce((n: number, i: any) => n + (Number(i.quantity) || 0), 0),
        value: g.items.reduce((n: number, i: any) =>
          n + (Number(i.unit_price) || 0) * (Number(i.quantity) || 0), 0),
        gaps: vendorGaps(g),
      }));
      return json({ ok: true, order_gaps: missing(order, items), vendors: groups });
    }

    // The pickup points this Shiprocket account already knows about.
    if (action === "pickups") {
      const out = await call(admin, "GET", "/settings/company/pickup");
      const list = (out?.data?.shipping_address ?? out?.data ?? []).map?.((a: any) => ({
        id: a.id, nickname: a.pickup_location, city: a.city, state: a.state,
        pincode: a.pin_code, address: a.address, phone: a.phone,
      })) ?? [];
      return json({ ok: true, pickups: list });
    }

    // Register a vendor's address with Shiprocket, so their nickname exists to
    // be passed on an order. Done once per vendor, from their own fields here.
    if (action === "add_pickup") {
      const { data: brand } = await admin.from("brands").select("*")
        .eq("brand_id", p.brand_id).maybeSingle();
      if (!brand) return json({ error: "That vendor no longer exists." }, 400);
      const gaps: string[] = [];
      if (!brand.pickup_line1) gaps.push("a street address");
      if (!brand.pickup_city) gaps.push("a city");
      if (!brand.pickup_state) gaps.push("a state");
      if (!/^\d{6}$/.test(String(brand.pickup_pincode ?? ""))) gaps.push("a six-digit pincode");
      if (!brand.pickup_phone) gaps.push("a phone number");
      if (gaps.length) {
        return json({ error: `${brand.name} still needs ${gaps.join(", ")} before the address `
          + `can be registered.` }, 400);
      }
      const nickname = (brand.pickup_nickname
        || brand.name.replace(/[^A-Za-z0-9 ]/g, "").slice(0, 32).trim()) || `Vendor ${brand.brand_id.slice(0, 6)}`;
      const out = await call(admin, "POST", "/settings/company/addpickup", {
        pickup_location: nickname,
        name: brand.pickup_contact || brand.contact_person || brand.name,
        email: brand.email || "",
        phone: String(brand.pickup_phone).replace(/\D/g, "").slice(-10),
        address: brand.pickup_line1,
        address_2: brand.pickup_line2 ?? "",
        city: brand.pickup_city, state: brand.pickup_state,
        country: brand.pickup_country || "India", pin_code: brand.pickup_pincode,
      });
      await admin.from("brands").update({
        pickup_nickname: nickname, pickup_registered_at: new Date().toISOString(),
      }).eq("brand_id", p.brand_id);
      return json({ ok: true, nickname, response: out?.success ?? out });
    }

    // What it would cost and who can carry it, per vendor, before anything is
    // booked. Each vendor's quote leaves from their own pincode.
    if (action === "rates") {
      const { order, items } = await orderWith(admin, p.order_id);
      const gaps = missing(order, items);
      if (gaps.length) return json({ error: `This order still needs ${gaps.join(", ")}.` }, 400);

      const groups = byVendor(items);
      const wanted = p.brand_id
        ? groups.filter((g) => g.brand_id === p.brand_id)
        : groups;
      const cod = order.payment_method === "COD" ? 1 : 0;

      const out = [];
      for (const g of wanted) {
        const from = g.pickup_pincode || FALLBACK_PINCODE;
        if (!/^\d{6}$/.test(String(from))) {
          out.push({ brand_id: g.brand_id, brand_name: g.brand_name,
            error: `No pickup pincode for ${g.brand_name}.`, couriers: [] });
          continue;
        }
        // The parcel's weight is its share of the order's, by line count, when
        // nothing finer is recorded.
        const share = items.length ? g.items.length / items.length : 1;
        const weight = Math.max(0.3, (Number(order.weight_kg) || 0.6) * share);
        const q = `?pickup_postcode=${from}&delivery_postcode=${order.ship_pincode}`
          + `&weight=${weight.toFixed(2)}&cod=${cod}`;
        try {
          const got = await call(admin, "GET", `/courier/serviceability/${q}`);
          const couriers = (got?.data?.available_courier_companies ?? []).map((c: any) => ({
            courier_id: c.courier_company_id, name: c.courier_name,
            rate: c.rate, etd: c.etd, days: c.estimated_delivery_days,
            rating: c.rating, cod: c.cod,
          })).sort((a: any, b: any) => Number(a.rate) - Number(b.rate));
          out.push({ brand_id: g.brand_id, brand_name: g.brand_name, from, weight, couriers });
        } catch (e) {
          out.push({ brand_id: g.brand_id, brand_name: g.brand_name, couriers: [],
            error: e instanceof Error ? e.message : String(e) });
        }
      }
      return json({ ok: true, vendors: out,
                    couriers: out[0]?.couriers ?? [] });
    }

    // One booking per vendor in the order. Each is its own Shiprocket order,
    // its own AWB and its own parcel, because each leaves from a different
    // door. A vendor that cannot be booked does not stop the others, and each
    // step records what it got, so a failure half way leaves the shipment row
    // telling the truth about how far it reached.
    if (action === "book") {
      const { order, items } = await orderWith(admin, p.order_id);
      const gaps = missing(order, items);
      if (gaps.length) return json({ error: `This order still needs ${gaps.join(", ")}.` }, 400);

      const groups = byVendor(items).filter((g) =>
        !p.brand_id || g.brand_id === p.brand_id);
      if (!groups.length) return json({ error: "Nothing in this order to book." }, 400);

      const chosen: Record<string, number> = p.couriers ?? {};
      const done: any[] = [];

      for (const g of groups) {
        const label = g.brand_name;
        const vgaps = vendorGaps(g);
        if (vgaps.length) { done.push({ brand_name: label, error: vgaps.join("; ") }); continue; }

        const already = await admin.from("shipments").select("*")
          .eq("order_id", p.order_id).eq("brand_id", g.brand_id).maybeSingle();
        if (already.data?.awb) {
          done.push({ brand_name: label, awb: already.data.awb,
                      error: `Already booked as ${already.data.awb}.` });
          continue;
        }

        const share = items.length ? g.items.length / items.length : 1;
        const weight = Math.max(0.3, (Number(order.weight_kg) || 0.6) * share);
        // Shiprocket rejects a repeated order id, so each parcel carries the
        // vendor's name for a human plus four characters of their id, which two
        // vendors cannot share even when their names start the same.
        const suffix = groups.length > 1
          ? `-${(g.brand_name || "V").replace(/[^A-Za-z0-9]/g, "").slice(0, 6)}`
            + `${String(g.brand_id ?? "none").slice(0, 4)}`
          : "";

        let srOrder = "", srShipment = "";
        try {
          const created = await call(admin, "POST", "/orders/create/adhoc", {
            ...orderPayload(order, g.items, g.pickup!, suffix), weight,
          });
          srOrder = String(created.order_id ?? "");
          srShipment = String(created.shipment_id ?? "");
          if (!srShipment) throw new Error("Shiprocket created no shipment.");
        } catch (e) {
          done.push({ brand_name: label,
                      error: `Could not create the order: ${e instanceof Error ? e.message : e}` });
          continue;
        }

        const row: Record<string, unknown> = {
          order_id: p.order_id, brand_id: g.brand_id, provider: "Shiprocket",
          sr_order_id: srOrder, sr_shipment_id: srShipment,
          status: "Created", booked_at: new Date().toISOString(),
          address_city: order.ship_city, address_country: order.ship_country || "India",
          weight_kg: weight, pickup_address: g.pickup, last_error: null,
        };
        const saved = already.data
          ? await admin.from("shipments").update(row)
              .eq("shipment_id", already.data.shipment_id).select().maybeSingle()
          : await admin.from("shipments").insert(row).select().maybeSingle();
        const shipmentId = saved.data?.shipment_id;

        const note = async (message: string) => {
          if (shipmentId) {
            await admin.from("shipments").update({ last_error: message })
              .eq("shipment_id", shipmentId);
          }
        };

        let awb = "", courier = "";
        try {
          const courierId = chosen[g.brand_id ?? "none"] ?? p.courier_id;
          const got = await call(admin, "POST", "/courier/assign/awb", {
            shipment_id: Number(srShipment),
            ...(courierId ? { courier_id: Number(courierId) } : {}),
          });
          const d = got?.response?.data ?? {};
          awb = String(d.awb_code ?? "");
          courier = String(d.courier_name ?? "");
          if (!awb) throw new Error(got?.message || "No AWB came back.");
        } catch (e) {
          const message = `No courier would take it: ${e instanceof Error ? e.message : e}`;
          await note(message);
          done.push({ brand_name: label, shipment_id: shipmentId, error: message });
          continue;
        }

        await admin.from("shipments").update({
          awb, courier, status: "Booked",
          tracking_url: `https://shiprocket.co/tracking/${awb}`,
        }).eq("shipment_id", shipmentId);

        let pickedUp = false, labelUrl = null;
        try {
          await call(admin, "POST", "/courier/generate/pickup",
                     { shipment_id: [Number(srShipment)] });
          pickedUp = true;
          await admin.from("shipments").update({
            pickup_scheduled_at: new Date().toISOString(), status: "Pickup scheduled",
          }).eq("shipment_id", shipmentId);
        } catch (e) {
          await note(`Booked, but the pickup was not scheduled: ${e instanceof Error ? e.message : e}`);
        }
        try {
          const got = await call(admin, "POST", "/courier/generate/label",
                                 { shipment_id: [Number(srShipment)] });
          labelUrl = got?.label_url ?? null;
          if (labelUrl) {
            await admin.from("shipments").update({ label_url: labelUrl })
              .eq("shipment_id", shipmentId);
          }
        } catch (e) {
          await note(`Booked, but the label was not generated: ${e instanceof Error ? e.message : e}`);
        }

        done.push({ brand_name: label, shipment_id: shipmentId, awb, courier,
                    pickup: pickedUp, label_url: labelUrl, from: g.pickup });
      }

      if (done.some((d) => d.awb)) {
        await admin.from("orders").update({ order_status: "Processing" })
          .eq("order_id", p.order_id);
      }
      return json({ ok: true, parcels: done,
                    booked: done.filter((d) => d.awb).length,
                    failed: done.filter((d) => !d.awb).length });
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
