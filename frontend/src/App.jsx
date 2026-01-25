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

  const leaveRoom = () => {
    if (roomId) socket.emit("leave_room", { room_id: roomId });
    setRoomId(null);
    setRoom(null);
    setView("home");
  };

  useEffect(() => {
    const onConnected = (payload) => setMyId(payload?.id || null);

    const onRoomJoined = (payload) => {
      const rid = payload?.room_id;
      if (!rid) return;
      setRoomId(rid);
      setView("lobby");
      setRoom((prev) => prev || { room_id: rid });
    };

    const onRoomState = (payload) => {
      const newRoom = payload?.room;
      if (!newRoom) return;

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

    socket.on("connected", onConnected);
    socket.on("room_joined", onRoomJoined);
    socket.on("room_state", onRoomState);
    socket.on("game_started", onGameStarted);
    socket.on("game_end", onGameEnd);
    socket.on("error", onError);

    return () => {
      socket.off("connected", onConnected);
      socket.off("room_joined", onRoomJoined);
      socket.off("room_state", onRoomState);
      socket.off("game_started", onGameStarted);
      socket.off("game_end", onGameEnd);
      socket.off("error", onError);
    };
  }, []);

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
            <div className="text-2xl font-black">Ziago</div>
            <div className="text-sm text-zinc-400">
            {roomId ? `Room: ${roomId}` : ""}
            </div>
        </div>
        </div>


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
