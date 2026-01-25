export function Badge({ children, className = "" }) {
  return (
    <span className={`px-2 py-1 rounded-lg text-xs bg-zinc-800 border border-zinc-700 ${className}`}>
      {children}
    </span>
  );
}
