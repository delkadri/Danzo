export function Button({ children, className = "", variant = "primary", ...props }) {
  const base =
    "px-4 py-2 rounded-xl font-semibold transition active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed";
  const styles =
    variant === "ghost"
      ? "bg-transparent border border-zinc-700 hover:bg-zinc-800"
      : variant === "danger"
      ? "bg-red-600 hover:bg-red-500"
      : "bg-indigo-600 hover:bg-indigo-500";

  return (
    <button className={`${base} ${styles} ${className}`} {...props}>
      {children}
    </button>
  );
}
