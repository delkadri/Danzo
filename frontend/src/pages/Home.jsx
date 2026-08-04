import { useEffect, useMemo, useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input } from "../components/Input";

function getOrCreatePlayerId() {
  const existing = localStorage.getItem("danzo_player_id");
  if (existing) return existing;

  // Prefer crypto.randomUUID if available
  let pid = "";
  if (typeof crypto !== "undefined" && crypto?.randomUUID) {
    pid = crypto.randomUUID().replaceAll("-", "");
  } else {
    pid = `${Date.now()}${Math.random().toString(16).slice(2)}`;
  }

  localStorage.setItem("danzo_player_id", pid);
  return pid;
}

export default function Home() {
  const [joinName, setJoinName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [createName, setCreateName] = useState("");

  const playerId = useMemo(() => getOrCreatePlayerId(), []);

  // ✅ Prefill nickname from storage
  useEffect(() => {
    const saved = localStorage.getItem("danzo_name");
    if (saved && !joinName && !createName) {
      setJoinName(saved);
      setCreateName(saved);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persistName = (name) => {
    const n = (name || "").trim();
    if (n) localStorage.setItem("danzo_name", n);
  };

  const joinRoom = () => {
    const name = joinName.trim();
    const code = joinCode.trim();

    if (!name) return alert("Nickname is required.");
    if (!code) return alert("Room code is required.");

    persistName(name);
    localStorage.setItem("danzo_room_id", code);

    socket.emit("join_room", {
      room_id: code,
      name,
      player_id: playerId,
    });
  };

  const createRoom = () => {
    const name = createName.trim();
    if (!name) return alert("Nickname is required.");

    persistName(name);

    socket.emit("create_room", {
      name,
      player_id: playerId,
    });
  };

  return (
    <Card className="mx-auto max-w-lg p-4 sm:p-6">
      <div className="rounded-2xl bg-indigo-50 px-4 py-4 dark:bg-indigo-500/10">
        <div className="text-xs font-black uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">
          Team word game
        </div>
        <div className="mt-1 text-2xl font-black tracking-tight">Ready to play?</div>
        <div className="mt-1 text-sm leading-6 text-zinc-600 dark:text-zinc-400">
          Guess words with a teammate and race to the top of the ranking.
        </div>
      </div>

      {/* JOIN FIRST */}
      <form
        className="mt-6"
        onSubmit={(event) => {
          event.preventDefault();
          joinRoom();
        }}
      >
        <div className="text-lg font-bold">Join a room</div>
        <div className="mt-3 space-y-3">
          <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Nickname
          <Input
            className="mt-2"
            placeholder="Your nickname"
            value={joinName}
            onChange={(e) => setJoinName(e.target.value)}
            autoComplete="nickname"
            enterKeyHint="next"
          />
          </label>
          <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Room code
          <Input
            placeholder="Room code (4 digits)"
            value={joinCode}
            onChange={(e) =>
              setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 4))
            }
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={4}
            autoComplete="one-time-code"
            enterKeyHint="go"
            className="mt-2 font-mono text-lg tracking-[0.2em]"
          />
          </label>
          <Button type="submit" className="w-full">
            Join
          </Button>
        </div>
      </form>

      {/* CREATE SECOND */}
      <form
        className="mt-7 border-t border-zinc-200 pt-6 dark:border-zinc-800"
        onSubmit={(event) => {
          event.preventDefault();
          createRoom();
        }}
      >
        <div className="text-lg font-bold">Create a game</div>
        <div className="mt-3 space-y-3">
          <label className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Nickname
          <Input
            className="mt-2"
            placeholder="Your nickname"
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            autoComplete="nickname"
            enterKeyHint="go"
          />
          </label>
          <Button type="submit" variant="ghost" className="w-full">
            Create
          </Button>
        </div>
      </form>
    </Card>
  );
}
