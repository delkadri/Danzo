export function Badge({ children, className = "" }) {
  return (
    <span className={`inline-flex items-center rounded-lg border border-zinc-300 bg-zinc-100 px-2 py-1 text-xs text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 ${className}`}>
      {children}
    </span>
  );
}
