export function Card({ children, className = "" }) {
  return (
    <div className={`rounded-2xl border border-zinc-200 bg-white/90 shadow-lg shadow-zinc-950/5 backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-900/60 dark:shadow-black/20 ${className}`}>
      {children}
    </div>
  );
}
