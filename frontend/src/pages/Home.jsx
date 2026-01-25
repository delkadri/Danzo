import { useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input } from "../components/Input";

export default function Home() {
  const [joinName, setJoinName] = useState("");
  const [joinCode, setJoinCode] = useState("");

  const [createName, setCreateName] = useState("");

  const joinRoom = () => {
    if (!joinName.trim()) return alert("Nickname is required.");
    if (!joinCode.trim()) return alert("Room code is required.");
    socket.emit("join_room", { room_id: joinCode.trim(), name: joinName.trim() });
  };

  const createRoom = () => {
    if (!createName.trim()) return alert("Nickname is required.");
    socket.emit("create_room", { name: createName.trim() });
  };

  return (
    <Card className="p-6">
      <div className="text-2xl font-black">Play Ziago</div>
      <div className="text-sm text-zinc-400 mt-1">
        Guess words in teams of 2.
      </div>

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
            onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, "").slice(0, 4))}
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
    </Card>
  );
}
