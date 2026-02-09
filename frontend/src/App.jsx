import { useEffect, useState } from "react";
import { socket } from "./lib/socket";

import Home from "./pages/Home";
import Lobby from "./pages/Lobby";
import Game from "./pages/Game";

import { Card } from "./components/Card";
import { Button } from "./components/Button";

export default function App() {
  const [myId, setMyId] = useState(null);
  const [roomId, setRoomId] = useState(null);
  const [room, setRoom] = useState(null);
  const [view, setView] = useState("home"); // home | lobby | game

  // ✅ small modern banner message (ex: kicked)
  const [systemMsg, setSystemMsg] = useState("");

  const clearSessionStorage = () => {
    localStorage.removeItem("danzo_room_id");
    localStorage.removeItem("danzo_player_id");
    localStorage.removeItem("danzo_name");
  };

  const resetToHome = (msg = "") => {
    if (msg) setSystemMsg(msg);
    setMyId(null);
    setRoomId(null);
    setRoom(null);
    setView("home");
    clearSessionStorage();
  };

  const leaveRoom = () => {
    const rid = roomId;
    // on clear d’abord, comme ça si refresh => pas de rejoin auto
    clearSessionStorage();

    if (rid) {
      socket.emit("leave_room", { room_id: rid });
    }

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

      // si déjà dans une room côté state, ne rien faire
      if (roomId || myId) return;

      if (rid && pid && name) {
        socket.emit("join_room", { room_id: rid, name, player_id: pid });
      }
    };

    const onRoomJoined = (payload) => {
      const rid = payload?.room_id;
      const pid = payload?.player_id;
      if (!rid || !pid) return;

      setRoomId(rid);
      setMyId(pid);
      setView("lobby");
      setRoom((prev) => prev || { room_id: rid });
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
      if (myId) {
        const ids = Array.isArray(newRoom.players)
          ? newRoom.players.map((p) => p?.id).filter(Boolean)
          : [];
        if (ids.length > 0 && !ids.includes(myId)) {
          resetToHome("You were removed from the room.");
          return;
        }
      }

      setRoom(newRoom);

      const phase = newRoom.phase || "lobby";
      if (phase === "playing" || phase === "ranking" || phase === "results") {
        setView("game");
      } else {
        setView("lobby");
      }
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

    socket.on("connected", onConnected);
    socket.on("room_joined", onRoomJoined);
    socket.on("room_state", onRoomState);
    socket.on("game_started", onGameStarted);
    socket.on("game_end", onGameEnd);
    socket.on("error", onError);
    socket.on("kicked", onKicked);

    return () => {
      socket.off("connected", onConnected);
      socket.off("room_joined", onRoomJoined);
      socket.off("room_state", onRoomState);
      socket.off("game_started", onGameStarted);
      socket.off("game_end", onGameEnd);
      socket.off("error", onError);
      socket.off("kicked", onKicked);
    };
  }, [roomId, myId]); // ✅ important: needed for onConnected + onRoomState checks

  // loading safe
  if (view !== "home" && (!roomId || !room)) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <Card className="p-6 max-w-md w-full">
          <div className="text-xl font-bold">Loading room…</div>
          <div className="text-sm text-zinc-400 mt-2">
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
    <div className="min-h-screen p-4 sm:p-6 max-w-6xl mx-auto">
      {/* HEADER */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <div className="text-2xl font-black">Play Danzo</div>
          <div className="text-sm text-zinc-400">
            {roomId ? `Room: ${roomId}` : ""}
          </div>
        </div>
      </div>

      {/* ✅ System banner (kicked, etc.) */}
      {systemMsg && (
        <div className="mb-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-zinc-200 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-bold">Removed from the room</div>
            <div className="text-zinc-300">{systemMsg}</div>
          </div>
          <button
            onClick={() => setSystemMsg("")}
            className="shrink-0 rounded-xl border border-zinc-800 bg-zinc-950 px-3 py-1 text-xs text-zinc-200 hover:border-zinc-700"
          >
            OK
          </button>
        </div>
      )}

      {view === "home" && <Home />}

      {view === "lobby" && (
        <Lobby myId={myId} room={room} roomId={roomId} onLeave={leaveRoom} />
      )}

      {view === "game" && (
        <Game myId={myId} room={room} roomId={roomId} onLeave={leaveRoom} />
      )}
    </div>
  );
}
