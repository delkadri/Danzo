export function Input({ className = "", ...props }) {
  return (
    <input
      className={`w-full px-4 py-2 rounded-xl bg-zinc-950 border border-zinc-800 outline-none focus:border-indigo-500 ${className}`}
      {...props}
    />
  );
}
