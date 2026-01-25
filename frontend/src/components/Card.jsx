export function Card({ children, className = "" }) {
  return (
    <div className={`rounded-2xl bg-zinc-900/60 border border-zinc-800 shadow-lg ${className}`}>
      {children}
    </div>
  );
}
