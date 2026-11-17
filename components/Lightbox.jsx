'use client';
import { createContext, useContext, useEffect, useState, useCallback } from 'react';

const Ctx = createContext(() => {});
export const useLightbox = () => useContext(Ctx);

// One viewer for the whole app: anything that renders a picture can hand it a list
// and an index, so a thumbnail in a table and a thumbnail in a gallery behave alike.
export function LightboxProvider({ children }) {
  const [state, setState] = useState(null);

  const open = useCallback((images, index = 0) => {
    const list = (images || []).filter((i) => i && i.public_url);
    if (list.length) setState({ list, i: Math.max(0, Math.min(index, list.length - 1)) });
  }, []);

  const close = useCallback(() => setState(null), []);
  const step = useCallback((d) => setState((s) =>
    s ? { ...s, i: (s.i + d + s.list.length) % s.list.length } : s), []);

  useEffect(() => {
    if (!state) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowRight') step(1);
      if (e.key === 'ArrowLeft') step(-1);
    };
    window.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev; };
  }, [state, close, step]);

  const cur = state ? state.list[state.i] : null;
  const many = state && state.list.length > 1;

  return (
    <Ctx.Provider value={open}>
      {children}
      {cur && (
        <div className="lb" onClick={close} role="dialog" aria-modal="true"
          aria-label="Product image viewer">
          <button className="lb-x" onClick={close} aria-label="Close">×</button>
          {many && (
            <button className="lb-nav lb-prev" aria-label="Previous image"
              onClick={(e) => { e.stopPropagation(); step(-1); }}>‹</button>)}
          <figure className="lb-fig" onClick={(e) => e.stopPropagation()}>
            <img src={cur.public_url} alt={cur.image_role || ''} />
            <figcaption>
              <span>{cur.image_role || 'Photo'}{cur.shot_angle ? ` · ${cur.shot_angle}` : ''}</span>
              {cur.generated && <span className="lb-tag">AI generated</span>}
              {many && <span className="lb-count">{state.i + 1} of {state.list.length}</span>}
            </figcaption>
          </figure>
          {many && (
            <button className="lb-nav lb-next" aria-label="Next image"
              onClick={(e) => { e.stopPropagation(); step(1); }}>›</button>)}
        </div>)}
    </Ctx.Provider>
  );
}
