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
    <Card className="p-6">
      <div className="text-sm text-zinc-400 mt-1">Guess words in teams of 2.</div>

      {/* JOIN FIRST */}
      <div className="mt-6">
        <div className="text-lg font-bold">Join a room</div>
        <div className="mt-3 space-y-3">
          <Input
            placeholder="Your nickname"
            value={joinName}
            onChange={(e) => setJoinName(e.target.value)}
          />
          <Input
            placeholder="Room code (4 digits)"
            value={joinCode}
            onChange={(e) =>
              setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 4))
            }
          />
          <Button onClick={joinRoom} className="w-full">
            Join
          </Button>
        </div>
      </div>

      {/* CREATE SECOND */}
      <div className="mt-8 border-t border-zinc-800 pt-6">
        <div className="text-lg font-bold">Create a game</div>
        <div className="mt-3 space-y-3">
          <Input
            placeholder="Your nickname"
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
          />
          <Button onClick={createRoom} variant="ghost" className="w-full">
            Create
          </Button>
        </div>
      </div>

      {/* tiny debug helper (optional, harmless) */}
      <div className="mt-6 text-xs text-zinc-600">
        Your player id: <span className="font-mono">{playerId.slice(0, 10)}…</span>
      </div>
    </Card>
  );
}
