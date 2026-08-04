import { useEffect } from "react";

export function Toast({ message, onClose }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => onClose?.(), 2500);
    return () => clearTimeout(t);
  }, [message, onClose]);

  if (!message) return null;

  return (
    <div className="safe-bottom fixed bottom-3 left-3 right-3 z-50 mx-auto max-w-md rounded-xl border border-zinc-200 bg-white px-4 py-3 text-center text-sm shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
      {message}
    </div>
  );
}
