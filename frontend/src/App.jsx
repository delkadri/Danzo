import { useEffect, useRef, useState } from "react";
import { socket } from "./lib/socket";

import Home from "./pages/Home";
import Lobby from "./pages/Lobby";
import Game from "./pages/Game";

import { Card } from "./components/Card";
import { Button } from "./components/Button";
import { ThemeToggle } from "./components/ThemeToggle";

function getInitialTheme() {
  const savedTheme = localStorage.getItem("danzo_theme");
  if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function viewForRoom(room) {
  const phase = room?.phase || "lobby";
  return phase === "playing" || phase === "ranking" || phase === "results"
    ? "game"
    : "lobby";
}

export default function App() {
  const [theme, setTheme] = useState(getInitialTheme);
  const [myId, setMyId] = useState(null);
  const [roomId, setRoomId] = useState(null);
  const [room, setRoom] = useState(null);
  const [view, setView] = useState("home"); // home | lobby | game
  const [sessionVersion, setSessionVersion] = useState(0);
  const myIdRef = useRef(null);

  // ✅ small modern banner message (ex: kicked)
  const [systemMsg, setSystemMsg] = useState("");

  useEffect(() => {
    if (!systemMsg) return undefined;
    const timeoutId = window.setTimeout(() => setSystemMsg(""), 5000);
    return () => window.clearTimeout(timeoutId);
  }, [systemMsg]);

  useEffect(() => {
    const isDark = theme === "dark";
    document.documentElement.classList.toggle("dark", isDark);
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content",
      isDark ? "#09090b" : "#f8fafc"
    );
    localStorage.setItem("danzo_theme", theme);
  }, [theme]);

  const clearSessionStorage = () => {
    localStorage.removeItem("danzo_room_id");
    localStorage.removeItem("danzo_player_id");
    localStorage.removeItem("danzo_name");
  };

  const clearRoomStorage = () => {
    localStorage.removeItem("danzo_room_id");
  };

  const resetToHome = (msg = "") => {
    if (msg) setSystemMsg(msg);
    myIdRef.current = null;
    setMyId(null);
    setRoomId(null);
    setRoom(null);
    setView("home");
    clearSessionStorage();
  };

  const leaveRoom = () => {
    const rid = roomId;
    // on clear d’abord, comme ça si refresh => pas de rejoin auto
    clearRoomStorage();

    if (rid) {
      socket.emit("leave_room", { room_id: rid });
    }

    myIdRef.current = null;
    setMyId(null);
    setRoomId(null);
    setRoom(null);
    setView("home");
  };

  useEffect(() => {
    const onConnected = () => {
      // ✅ auto-reconnect on refresh (si session présente)
      const rid = localStorage.getItem("danzo_room_id");
      const pid = localStorage.getItem("danzo_player_id");
      const name = localStorage.getItem("danzo_name");

      if (rid && pid && name) {
        socket.emit("join_room", { room_id: rid, name, player_id: pid });
      }
    };

    const onRoomJoined = (payload) => {
      const rid = payload?.room_id;
      const pid = payload?.player_id;
      if (!rid || !pid) return;

      const joinedRoom = payload?.room || null;
      myIdRef.current = pid;
      setRoomId(rid);
      setMyId(pid);
      setRoom(joinedRoom);
      setView(joinedRoom ? viewForRoom(joinedRoom) : "loading");
      setSessionVersion((current) => current + 1);
      setSystemMsg("");

      // persist for refresh-reconnect
      localStorage.setItem("danzo_room_id", rid);
      localStorage.setItem("danzo_player_id", pid);
      // le nom est normalement déjà stocké par Home
    };

    const onRoomState = (payload) => {
      const newRoom = payload?.room;
      if (!newRoom) return;

      // ✅ Si on a un player_id et qu'il n'est plus dans la room => on sort
      // (utile si "kicked" n'arrive pas pour une raison quelconque)
      const activePlayerId = myIdRef.current;
      if (activePlayerId) {
        const ids = Array.isArray(newRoom.players)
          ? newRoom.players.map((p) => p?.id).filter(Boolean)
          : [];
        if (ids.length > 0 && !ids.includes(activePlayerId)) {
          resetToHome("You were removed from the room.");
          return;
        }
      }

      setRoom(newRoom);

      setView(viewForRoom(newRoom));
    };

    const onGameStarted = (payload) => {
      setView("game");
      if (payload?.room) setRoom(payload.room);
    };

    const onGameEnd = (payload) => {
      if (payload?.room) setRoom(payload.room);
      setView("game");
    };

    const onError = (payload) => {
      alert(payload?.message || "Unknown error");
    };

    // ✅ when admin kicks you
    const onKicked = (payload) => {
      // IMPORTANT: clear storage to prevent auto-rejoin on refresh
      resetToHome(payload?.message || "An admin removed you from the room.");
    };

    socket.on("connect", onConnected);
    socket.on("room_joined", onRoomJoined);
    socket.on("room_state", onRoomState);
    socket.on("game_started", onGameStarted);
    socket.on("game_end", onGameEnd);
    socket.on("error", onError);
    socket.on("kicked", onKicked);

    // The socket can finish connecting before this React effect is mounted.
    // In that case, restore the stored session immediately.
    if (socket.connected) onConnected();

    return () => {
      socket.off("connect", onConnected);
      socket.off("room_joined", onRoomJoined);
      socket.off("room_state", onRoomState);
      socket.off("game_started", onGameStarted);
      socket.off("game_end", onGameEnd);
      socket.off("error", onError);
      socket.off("kicked", onKicked);
    };
  }, []);

  // loading safe
  if (view !== "home" && (!roomId || !room)) {
    return (
      <div className="safe-top safe-bottom flex min-h-[100dvh] items-center justify-center p-4">
        <Card className="w-full max-w-md p-5 sm:p-6">
          <div className="text-xl font-bold">Loading room…</div>
          <div className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
            Waiting for server state…
          </div>
          <div className="mt-4">
            <Button variant="danger" onClick={leaveRoom} className="w-full">
              Back to Home
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="safe-top safe-bottom mx-auto min-h-[100dvh] w-full max-w-5xl px-3 pb-6 sm:px-6 sm:pb-8">
      {/* HEADER */}
      <header className="mb-4 flex min-h-14 items-center justify-between gap-3 sm:mb-5">
        <div className="min-w-0">
          <div className="truncate text-xl font-black tracking-tight sm:text-2xl">Play Danzo</div>
        </div>
        <ThemeToggle
          theme={theme}
          onToggle={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
        />
      </header>

      {/* ✅ System banner (kicked, etc.) */}
      {systemMsg && (
        <div
          className="mb-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-zinc-800 dark:text-zinc-200"
          role="status"
        >
          <div className="min-w-0">
            <div className="font-bold">Removed from the room</div>
            <div className="text-zinc-600 dark:text-zinc-300">{systemMsg}</div>
          </div>
        </div>
      )}

      {view === "home" && <Home />}

      {view === "lobby" && (
        <Lobby
          key={`${roomId}:${sessionVersion}`}
          myId={myId}
          room={room}
          roomId={roomId}
          onLeave={leaveRoom}
        />
      )}

      {view === "game" && (
        <Game
          key={`${roomId}:${sessionVersion}`}
          myId={myId}
          room={room}
          roomId={roomId}
          onLeave={leaveRoom}
        />
      )}
    </div>
  );
}
