export function Input({ className = "", ...props }) {
  return (
    <input
      className={`min-h-12 w-full rounded-xl border border-zinc-300 bg-white px-4 py-2.5 text-base text-zinc-950 outline-none placeholder:text-zinc-400 focus:border-indigo-500 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-600 ${className}`}
      {...props}
    />
  );
}
