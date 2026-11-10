export default function Flash({ params }) {
  const err = params?.error;
  const saved = params?.saved || params?.deleted;
  if (!err && !saved) return null;
  return err
    ? <div className="note warn" style={{ marginBottom: 14 }}>{err}</div>
    : <div className="ok" style={{ marginBottom: 14 }}>{params.deleted ? 'Deleted.' : 'Saved.'}</div>;
}
