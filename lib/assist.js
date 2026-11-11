'use client';
import { sb } from './db';

const ENDPOINT = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/launch-assist`;

// Providers report billing problems in their own words, which read like faults in
// this app. Say what actually has to be done, and keep the original underneath.
function humanise(raw) {
  const m = String(raw || '');
  if (/prepayment credits are depleted/i.test(m)) {
    return 'Google says this API key has no credit left. Top up or attach a payment method on the '
      + 'Google Cloud project that issued the key, then try again — nothing here needs changing. '
      + `(Google's words: ${m.trim()})`;
  }
  if (/limit:\s*0/i.test(m) && /free_tier/i.test(m)) {
    return 'Google allows this model no free-tier quota at all, so the project behind the API key '
      + 'needs billing enabled. Nothing here needs changing. '
      + `(Google's words: ${m.trim().slice(0, 300)})`;
  }
  if (/RESOURCE_EXHAUSTED|rate limit|429/i.test(m)) {
    return `The model provider is rate-limiting this key, so wait and try again. (${m.trim().slice(0, 300)})`;
  }
  if (/\b546\b/.test(m)) {
    return 'That took too long for the server to finish. If the photos were uploaded before tonight '
      + 'they are full-size: remove and re-add them, since photos are shrunk on upload now.';
  }
  return m;
}

export async function assist(body) {
  const { data: { session } } = await sb().auth.getSession();
  if (!session) throw new Error('Sign in again, your session expired.');
  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const out = await res.json().catch(() => ({ error: `The assistant returned ${res.status}.` }));
  if (!res.ok) throw new Error(humanise(out.error) || `The assistant returned ${res.status}.`);
  return out;
}

export const checkKeys = () => assist({ action: 'health' });

// The models the CRM can use. Add a key below and the option stops saying
// "no key yet". Keys live only as Edge Function secrets, never in the browser.
export const PROVIDERS = [
  ['openai', 'ChatGPT', 'OpenAI',
    'Reliable at copy. Reads photos. Searches the web for prices.'],
  ['gemini', 'Gemini', 'Google',
    'Reads photos closely and grounds price research in Google Search.'],
  ['anthropic', 'Claude', 'Anthropic',
    'Strongest at long writing and at following a brief exactly.'],
];
export const NO_KEYS = { openai: false, gemini: false, anthropic: false };
export const SECRET_NAME = {
  openai: 'OPENAI_API_KEY', gemini: 'GEMINI_API_KEY', anthropic: 'ANTHROPIC_API_KEY',
};
const row = (k) => PROVIDERS.find((p) => p[0] === k);
export const providerLabel = (k) => row(k)?.[1] ?? k;
export const providerOption = (k, keys) =>
  `${row(k)?.[1] ?? k} (${row(k)?.[2] ?? ''})${keys && !keys[k] ? ' \u2014 no key yet' : ''}`;
export const providerHint = (k) => row(k)?.[3] ?? '';
export const hasKey = (keys, k) => Boolean(keys && keys[k]);
export const anyKey = (keys) => PROVIDERS.some(([k]) => keys && keys[k]);
// Default to a model the workspace can actually call. Defaulting to one with no
// key makes every run fail, or worse, quietly decline to start.
export const firstWithKey = (keys, fallback = 'openai') =>
  PROVIDERS.map(([k]) => k).find((k) => keys && keys[k]) || fallback;

const AGENT_ENDPOINT = `${process.env.NEXT_PUBLIC_SUPABASE_URL}/functions/v1/department-agent`;

export async function runAgent(body) {
  const { data: { session } } = await sb().auth.getSession();
  if (!session) throw new Error('Sign in again, your session expired.');
  const res = await fetch(AGENT_ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      apikey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const out = await res.json().catch(() => ({ error: `The agent returned ${res.status}.` }));
  if (!res.ok) throw new Error(humanise(out.error) || `The agent returned ${res.status}.`);
  return out;
}
