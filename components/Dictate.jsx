'use client';
import { useEffect, useRef, useState } from 'react';

// Speech comes from the browser, not from an API: nothing is uploaded, nothing
// is billed, and it keeps working when a key runs out. Chrome and Edge have it;
// Firefox does not, and the button says so rather than failing silently.
function engine() {
  if (typeof window === 'undefined') return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

const LANGS = [
  ['en-IN', 'English (India)'],
  ['hi-IN', 'हिन्दी'],
  ['en-GB', 'English (UK)'],
  ['en-US', 'English (US)'],
];

// Appends to whatever is already typed rather than replacing it, so dictation
// and the keyboard can be mixed in one field.
function join(existing, said) {
  const a = String(existing || '');
  const b = String(said || '').trim();
  if (!b) return a;
  if (!a) return b[0].toUpperCase() + b.slice(1);
  return /\s$/.test(a) ? a + b : `${a} ${b}`;
}

export default function Dictate({ onText, label = 'Dictate', compact = false }) {
  const Engine = engine();
  const [on, setOn] = useState(false);
  const [heard, setHeard] = useState('');
  const [note, setNote] = useState('');
  const [lang, setLang] = useState('en-IN');
  const rec = useRef(null);
  const live = useRef(false);

  useEffect(() => {
    try {
      const kept = localStorage.getItem('cos-dictate-lang');
      if (kept && LANGS.some(([k]) => k === kept)) setLang(kept);
    } catch { /* ignore */ }
    return () => { try { rec.current?.stop(); } catch { /* ignore */ } };
  }, []);

  function start() {
    if (!Engine) {
      setNote('This browser cannot listen. Chrome, Edge and Safari can; Firefox cannot.');
      return;
    }
    setNote('');
    const r = new Engine();
    r.lang = lang;
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const said = e.results[i][0].transcript;
        if (e.results[i].isFinal) onText((cur) => join(cur, said));
        else interim += said;
      }
      setHeard(interim);
    };
    r.onerror = (e) => {
      const why = {
        'not-allowed': 'The microphone is blocked. Allow it for this site in the address bar.',
        'service-not-allowed': 'The microphone is blocked for this site.',
        'no-speech': 'Nothing was heard. Try again, closer to the microphone.',
        'audio-capture': 'No microphone was found.',
      }[e.error] || `The browser stopped listening (${e.error}).`;
      setNote(why);
      live.current = false; setOn(false); setHeard('');
    };
    r.onend = () => {
      // Chrome stops on its own after a pause; keep going until it is told not to.
      if (live.current) { try { r.start(); } catch { live.current = false; setOn(false); } }
      else { setOn(false); setHeard(''); }
    };
    rec.current = r;
    live.current = true;
    try { r.start(); setOn(true); } catch { setNote('Could not start listening.'); }
  }

  function stop() {
    live.current = false;
    try { rec.current?.stop(); } catch { /* ignore */ }
    setOn(false); setHeard('');
  }

  return (
    <div className="dictate">
      <button type="button" className={`btn btn-sm ${on ? 'btn-danger' : ''}`}
        onClick={() => (on ? stop() : start())}
        title={Engine ? 'Speak instead of typing. It adds to what is already there.'
          : 'Chrome, Edge and Safari can listen. Firefox cannot.'}>
        <span className={`mic ${on ? 'live' : ''}`} aria-hidden="true" />
        {on ? 'Stop' : (compact ? '' : label)}
      </button>
      {on && (
        <select value={lang} className="dictate-lang" disabled
          title="Language is fixed while listening">
          {LANGS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
        </select>)}
      {!on && (
        <select value={lang} className="dictate-lang"
          onChange={(e) => {
            setLang(e.target.value);
            try { localStorage.setItem('cos-dictate-lang', e.target.value); } catch { /* ignore */ }
          }}>
          {LANGS.map(([k, n]) => <option key={k} value={k}>{n}</option>)}
        </select>)}
      {heard && <span className="small faint dictate-heard">{heard}</span>}
      {note && <span className="small dictate-note">{note}</span>}
    </div>
  );
}

// For forms that read their values off the DOM at submit time rather than
// holding them in state. Dictation writes into the node and fires the events a
// listener would expect, so an onBlur save still runs.
export function SpokenArea({ name, defaultValue, placeholder, style }) {
  const box = useRef(null);
  return (
    <>
      <textarea ref={box} name={name} defaultValue={defaultValue}
        placeholder={placeholder} style={style} />
      <Dictate compact onText={(f) => {
        const node = box.current;
        if (!node) return;
        node.value = f(node.value);
        node.dispatchEvent(new Event('input', { bubbles: true }));
      }} />
    </>
  );
}
