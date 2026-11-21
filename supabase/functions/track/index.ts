import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (b: unknown, status = 200) =>
  new Response(JSON.stringify(b), { status, headers: { ...CORS, "Content-Type": "application/json" } });

// What a customer may see about their own order. Everything else the row holds
// — cost price, which vendor supplied what, margins, internal notes, the
// courier label, anyone else's order — never leaves this function. The token is
// the only key; it is random per order, so the order number cannot be walked.
const SHOWN = {
  // Shiprocket's words are not a customer's words.
  status: (s: string) => {
    const t = (s || "").toLowerCase();
    if (/delivered/.test(t)) return "Delivered";
    if (/out for delivery/.test(t)) return "Out for delivery";
    if (/rto|return/.test(t)) return "Coming back to us";
    if (/transit|shipped|dispatch/.test(t)) return "On its way";
    if (/picked/.test(t)) return "Picked up";
    if (/pickup scheduled/.test(t)) return "Waiting for the courier";
    if (/booked|created/.test(t)) return "Packed, courier booked";
    return "Being prepared";
  },
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const admin = createClient(
    Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

  let p: any = {};
  try { p = await req.json(); } catch { /* fall through to the bad-token reply */ }
  const token = String(p.token ?? "").trim();

  // A short or malformed token is refused without touching the database, and
  // every failure says the same thing, so nothing here can be used to tell a
  // real order from a wrong guess.
  const no = () => json({ error: "That tracking link is not valid." }, 404);
  if (!/^[0-9a-f]{32}$/.test(token)) return no();

  try {
    const { data: order } = await admin.from("orders")
      .select("order_id,order_number,order_status,ordered_at,ship_name,ship_city,ship_state")
      .eq("track_token", token).maybeSingle();
    if (!order) return no();

    const [{ data: items }, { data: shipments }, { data: brand }] = await Promise.all([
      admin.from("order_items")
        .select("order_item_id,quantity,name,products(public_product_name,brand_id)")
        .eq("order_id", order.order_id),
      admin.from("shipments")
        .select("shipment_id,brand_id,awb,courier,status,tracking_url,shipped_at,delivered_at,"
          + "checkpoints,last_sync_at")
        .eq("order_id", order.order_id),
      admin.from("settings").select("setting_value").eq("setting_key", "brand_name").maybeSingle(),
    ]);

    // Pieces are grouped the way they actually travel: by the vendor they ship
    // from. The customer is told there are two parcels and which pieces are in
    // each, rather than wondering why half an order arrived.
    const byBrand = new Map<string, any>();
    for (const i of items ?? []) {
      const b = (i as any).products?.brand_id ?? "none";
      const g = byBrand.get(b) ?? { brand_id: b, pieces: [] as any[] };
      g.pieces.push({
        name: (i as any).name || (i as any).products?.public_product_name || "Piece",
        quantity: (i as any).quantity ?? 1,
      });
      byBrand.set(b, g);
    }

    const parcels = [...byBrand.values()].map((g, n) => {
      const s = (shipments ?? []).find((x: any) => (x.brand_id ?? "none") === g.brand_id);
      const steps = Array.isArray(s?.checkpoints) ? s!.checkpoints as any[] : [];
      return {
        parcel: n + 1,
        pieces: g.pieces,
        // The vendor's name is ours to know, not the customer's.
        status: s ? SHOWN.status(s.status) : "Being prepared",
        courier: s?.courier ?? null,
        awb: s?.awb ?? null,
        tracking_url: s?.tracking_url ?? null,
        shipped_at: s?.shipped_at ?? null,
        delivered_at: s?.delivered_at ?? null,
        updated_at: s?.last_sync_at ?? null,
        steps: steps.slice(0, 8).map((c: any) => ({
          at: c.date ?? c.updated_at ?? null,
          what: c.activity ?? c["sr-status-label"] ?? c.status ?? "",
          where: c.location ?? "",
        })).filter((c: any) => c.what),
      };
    });

    return json({
      ok: true,
      brand: brand?.setting_value ?? "Zarivia",
      order_number: order.order_number,
      ordered_at: order.ordered_at,
      // A first name only: the full name and the street address are not echoed
      // back to whoever holds the link.
      name: String(order.ship_name ?? "").trim().split(/\s+/)[0] || null,
      to: [order.ship_city, order.ship_state].filter(Boolean).join(", ") || null,
      parcels,
      split: parcels.length > 1,
    });
  } catch {
    return json({ error: "Could not read that order just now. Try again shortly." }, 502);
  }
});
