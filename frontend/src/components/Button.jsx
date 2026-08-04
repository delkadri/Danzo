export function Button({ children, className = "", variant = "primary", ...props }) {
  const base =
    "inline-flex min-h-12 items-center justify-center px-4 py-2.5 rounded-xl font-semibold transition active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100";
  const styles =
    variant === "ghost"
      ? "bg-white border border-zinc-300 text-zinc-800 hover:bg-zinc-50 dark:bg-transparent dark:border-zinc-700 dark:text-zinc-100 dark:hover:bg-zinc-800"
      : variant === "danger"
      ? "bg-red-600 text-white hover:bg-red-500 shadow-sm"
      : "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm shadow-indigo-950/10";

  return (
    <button className={`${base} ${styles} ${className}`} {...props}>
      {children}
    </button>
  );
}
