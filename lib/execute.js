'use client';
import { sb, insertRow } from './db';
import { slug } from './upload';

// Approving a campaign is the moment it stops being words. Each step below does
// one real thing and reports it, so a failure halfway leaves a clear record of
// what happened rather than a half-built campaign nobody can account for.
const CODE = () => Math.random().toString(36).slice(2, 8);

async function assist(body) {
  const { data: { session } } = await sb().auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/launch-assist`,
    { method: 'POST',
      headers: { Authorization: `Bearer ${session?.access_token}`,
                 'Content-Type': 'application/json' },
      body: JSON.stringify(body) });
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || `The image step returned ${res.status}.`);
  return out;
}

// Creatives are made from the piece's own photographs, so a campaign image is
// still the garment the customer receives.
async function photosFor(productId) {
  const { data } = await sb().from('product_images')
    .select('public_url,part,generated')
    .eq('product_id', productId).eq('generated', false)
    .order('is_primary', { ascending: false }).limit(4);
  return (data || []);
}

export async function executeCampaign({ proposal, campaign, thread, perPost = 2, onStep }) {
  const done = [];
  const trouble = [];
  const say = (text) => { if (onStep) onStep(text); };

  // 1. A collection, so the campaign's pieces hang together in the catalogue.
  const ids = [...new Set((proposal.posts || []).map((p) => p.product_id).filter(Boolean))];
  let collection = null;
  if (ids.length) {
    try {
      say('Grouping the pieces into a collection…');
      collection = await insertRow('collections', {
        name: proposal.campaign_name, slug: slug(proposal.campaign_name, 'campaign'),
        kind: 'Campaign', description: proposal.brief || null,
        story: proposal.art_direction || null, status: 'Active',
      });
      const rows = ids.map((pid) => ({ collection_id: collection.collection_id, product_id: pid }));
      const { error } = await sb().from('product_collections').insert(rows);
      if (error) throw error;
      done.push(`Collection "${proposal.campaign_name}" with ${ids.length} piece${ids.length === 1 ? '' : 's'}`);
    } catch (e) { trouble.push(`Collection: ${e.message || e}`); }
  }

  // 2. One tracked link per ad set, plus one for the collection, so what sells
  //    can be told apart from what merely ran.
  try {
    say('Making the tracked links…');
    const links = [];
    if (collection) {
      links.push({ code: CODE(), label: `${proposal.campaign_name} — organic`,
        kind: 'Collection', target: `/collections/${collection.slug}`,
        collection_id: collection.collection_id, campaign_id: campaign.campaign_id });
    }
    (proposal.ad_plan?.ad_sets || []).forEach((a) => {
      links.push({ code: CODE(), label: `${proposal.campaign_name} — ${a.name}`,
        kind: collection ? 'Collection' : 'Campaign',
        target: collection ? `/collections/${collection.slug}` : '/',
        collection_id: collection?.collection_id ?? null, campaign_id: campaign.campaign_id });
    });
    if (links.length) {
      const { error } = await sb().from('links').insert(links);
      if (error) throw error;
      done.push(`${links.length} tracked link${links.length === 1 ? '' : 's'}`);
    }
  } catch (e) { trouble.push(`Tracked links: ${e.message || e}`); }

  // 3. The work someone actually has to do, dated.
  try {
    say('Raising the tasks…');
    const start = proposal.start_date || new Date().toISOString().slice(0, 10);
    const before = (days) => {
      const d = new Date(start); d.setDate(d.getDate() - days);
      return d.toISOString().slice(0, 10);
    };
    const tasks = [
      { title: `Approve the creatives for ${proposal.campaign_name}`,
        detail: 'Check every generated image against the real piece before anything goes out.',
        due_on: before(2), status: 'To do', priority: 'High',
        campaign_id: campaign.campaign_id },
      { title: `Set up the Meta ads for ${proposal.campaign_name}`,
        detail: (proposal.ad_plan?.ad_sets || []).map((a) =>
          `${a.name}: ${a.audience}, ${a.geography}, ${a.budget_share}`).join('\n')
          || 'No ad plan drafted.',
        due_on: before(1), status: 'To do', priority: 'High',
        campaign_id: campaign.campaign_id },
      { title: `Schedule the posts for ${proposal.campaign_name}`,
        detail: `${(proposal.posts || []).length} posts, starting ${start}.`,
        due_on: before(1), status: 'To do', priority: 'Normal',
        campaign_id: campaign.campaign_id },
    ];
    const { error } = await sb().from('tasks').insert(tasks);
    if (error) throw error;
    done.push(`${tasks.length} tasks`);
  } catch (e) { trouble.push(`Tasks: ${e.message || e}`); }

  // 4. The creatives. Slowest and the only part that costs money, so it runs
  //    last: everything above survives even if the images fail.
  const posts = (proposal.posts || []).filter((p) => p.product_id);
  if (!posts.length) {
    trouble.push('No post named a piece from the catalogue, so no creatives were generated.');
  }
  let made = 0;
  for (let i = 0; i < posts.length; i++) {
    const post = posts[i];
    say(`Generating creatives — post ${i + 1} of ${posts.length}…`);
    try {
      const photos = await photosFor(post.product_id);
      if (!photos.length) {
        trouble.push(`"${post.title}": that piece has no photographs to work from.`);
        continue;
      }
      const out = await assist({
        action: 'images', provider: 'gemini',
        mode: proposal.look_id ? 'Editorial' : 'Model',
        count: perPost, look_id: proposal.look_id || null,
        set_id: null, cutout_on_white: false, check: true,
        tweak: [proposal.art_direction, post.art_direction].filter(Boolean).join(' '),
        piece: { public_product_name: post.title },
        images: photos.map((x) => x.public_url),
        parts: photos.map((x) => x.part || 'Unlabelled'),
      });
      const rows = (out.images || []).map((im) => ({
        post_id: post.post_id || null, thread_id: thread?.thread_id || null,
        product_id: post.product_id, look_id: proposal.look_id || null,
        storage_path: im.path, public_url: im.url,
        alt_text: `${proposal.campaign_name} — ${post.title}`,
        shot_angle: im.shot_angle || null, check_result: im.check || null,
      }));
      if (rows.length) {
        const { error } = await sb().from('campaign_assets').insert(rows);
        if (error) throw error;
        made += rows.length;
      }
      (out.failed || []).forEach((f) => trouble.push(`"${post.title}": ${f}`));
    } catch (e) { trouble.push(`"${post.title}": ${e.message || e}`); }
  }
  if (made) done.push(`${made} creative${made === 1 ? '' : 's'}`);

  return { done, trouble, collection };
}
