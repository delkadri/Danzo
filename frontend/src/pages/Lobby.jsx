import { useEffect, useMemo, useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";

export default function Lobby({ myId, room, roomId, onLeave }) {
  const isHost = room?.host_id === myId;
  const players = room?.players || [];
  const settings = room?.settings || { time_limit: 60, rounds: 5 };

  const teamSlots = Math.ceil(players.length / 2);

  const [draftTeams, setDraftTeams] = useState(
    Array.from({ length: teamSlots }, () => [])
  );

  // non-host: follow backend draft teams
    useEffect(() => {
    const incoming = room?.draft_teams;

    if (Array.isArray(incoming)) {
        // Ajuste le nombre de teams à l'écran
        const next = Array.from({ length: teamSlots }, (_, i) => incoming[i] || []);
        setDraftTeams(next);
    } else {
        setDraftTeams(Array.from({ length: teamSlots }, () => []));
    }
    }, [room?.draft_teams, teamSlots]);


  // host: ensure slots count + broadcast
  useEffect(() => {
    if (!isHost) return;

    setDraftTeams((prev) => {
      const next = Array.from({ length: teamSlots }, (_, i) => prev[i] || []);
      socket.emit("host_update_draft_teams", { room_id: roomId, draft_teams: next });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamSlots]);

  const assigned = useMemo(() => new Set(draftTeams.flat()), [draftTeams]);

  const unassignedPlayers = useMemo(() => {
    return players.filter((p) => !assigned.has(p.id));
  }, [players, assigned]);

  const onDragStart = (e, playerId) => {
    e.dataTransfer.setData("playerId", playerId);
  };

  const allowDrop = (e) => e.preventDefault();

  const dropToTeam = (e, teamIndex) => {
    const playerId = e.dataTransfer.getData("playerId");
    if (!playerId) return;

    setDraftTeams((prev) => {
      const next = prev.map((t) => t.filter((id) => id !== playerId));
      if (next[teamIndex].length >= 2) return prev;
      next[teamIndex].push(playerId);

      if (isHost) {
        socket.emit("host_update_draft_teams", { room_id: roomId, draft_teams: next });
      }
      return next;
    });
  };

  const dropToUnassigned = (e) => {
    const playerId = e.dataTransfer.getData("playerId");
    if (!playerId) return;

    setDraftTeams((prev) => {
      const next = prev.map((t) => t.filter((id) => id !== playerId));
      if (isHost) {
        socket.emit("host_update_draft_teams", { room_id: roomId, draft_teams: next });
      }
      return next;
    });
  };

  const allTeamsComplete = draftTeams.every((t) => t.length === 2);
  const allPlayersAssigned = assigned.size === players.length;
  const canStart =
    isHost &&
    players.length >= 2 &&
    players.length % 2 === 0 &&
    allTeamsComplete &&
    allPlayersAssigned;

  const startGame = () => {
    if (!canStart) return;

    socket.emit("host_set_teams", {
      room_id: roomId,
      teams: draftTeams.map((t) => ({ players: t })),
    });
  };

  useEffect(() => {
    const onTeamsSaved = () => {
      if (!isHost) return;
      socket.emit("host_start_game", { room_id: roomId });
    };

    socket.on("teams_saved", onTeamsSaved);
    return () => socket.off("teams_saved", onTeamsSaved);
  }, [isHost, roomId]);

  // settings (host only)
  const updateTime = (val) => {
    const n = Number(val);
    if (!Number.isFinite(n)) return;
    socket.emit("host_update_settings", {
      room_id: roomId,
      time_limit: n,
      rounds: settings.rounds,
    });
  };

  const updateRounds = (val) => {
    const n = Number(val);
    if (!Number.isFinite(n)) return;
    socket.emit("host_update_settings", {
      room_id: roomId,
      time_limit: settings.time_limit,
      rounds: n,
    });
  };

  const copyCode = async () => {
    await navigator.clipboard.writeText(roomId);
  };

  return (
    <Card className="p-5 sm:p-6">
      {/* Header inside card */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-2xl font-black">Lobby</div>

          <div className="mt-2 flex items-center gap-2">
            <div className="text-sm text-zinc-400">Room code:</div>
            <div className="font-mono text-lg font-black tracking-widest text-zinc-200">
              {roomId}
            </div>
            <Button variant="ghost" onClick={copyCode}>
              Copy
            </Button>
          </div>

          {isHost ? (
            <div className="text-sm text-zinc-400 mt-2">
              <b>Drag players into teams of 2, then start the game.</b>
            </div>
          ) : (
            <div className="text-sm text-zinc-400 mt-2">
              Waiting for admin to create teams and start…
            </div>
          )}
        </div>

        {/* ✅ Leave inside card (top-right) */}
        <Button variant="danger" onClick={onLeave}>
          Leave
        </Button>
      </div>

      {/* Unassigned */}
      <div className="mt-6">
        <div className="text-sm text-zinc-400 mb-2">Unassigned players</div>

        <div
          className="p-3 rounded-2xl bg-zinc-950 border border-zinc-800"
          onDrop={dropToUnassigned}
          onDragOver={allowDrop}
        >
          <div className="flex flex-wrap gap-2">
            {unassignedPlayers.length === 0 ? (
              <Badge className="text-zinc-400">All assigned ✅</Badge>
            ) : (
              unassignedPlayers.map((p) => (
                <div
                  key={p.id}
                  draggable={isHost}
                  onDragStart={(e) => onDragStart(e, p.id)}
                  className={`px-3 py-2 rounded-xl border ${
                    p.id === room?.host_id
                      ? "border-indigo-700/50 bg-indigo-700/10"
                      : "border-zinc-800 bg-zinc-900/40"
                  } cursor-move`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{p.name}</span>
                    {p.id === room?.host_id && <Badge>ADMIN</Badge>}
                    {p.id === myId && (
                      <Badge className="bg-indigo-700/40 border-indigo-700">
                        YOU
                      </Badge>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Teams */}
      <div className="mt-6">
        <div className="text-sm text-zinc-400 mb-2">Teams</div>

        <div className="grid sm:grid-cols-2 gap-3">
          {draftTeams.map((t, idx) => (
            <div
              key={idx}
              className="p-4 rounded-2xl bg-zinc-950 border border-zinc-800"
              onDrop={(e) => dropToTeam(e, idx)}
              onDragOver={allowDrop}
            >
              <div className="flex items-center justify-between">
                <div className="font-bold">Team {idx + 1}</div>
                <Badge>{t.length}/2</Badge>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {t.length === 0 ? (
                  <Badge className="text-zinc-400">Drop here</Badge>
                ) : (
                  t.map((pid) => {
                    const p = players.find((x) => x.id === pid);
                    return (
                      <div
                        key={pid}
                        draggable={isHost}
                        onDragStart={(e) => onDragStart(e, pid)}
                        className="px-3 py-2 rounded-xl border border-zinc-800 bg-zinc-900/40 cursor-move"
                      >
                        <span className="font-semibold">
                          {p?.name || pid.slice(0, 6)}
                        </span>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ✅ Admin bottom controls */}
      {isHost && (
        <div className="mt-7">
          {/* ✅ settings ABOVE Start */}
          <div className="grid grid-cols-2 gap-3">
            <div className="p-4 rounded-2xl bg-zinc-950 border border-zinc-800">
              <div className="text-xs text-zinc-500">Time (seconds)</div>
              <input
                className="mt-2 w-full bg-transparent border border-zinc-800 rounded-xl px-3 py-2"
                type="number"
                min={20}
                max={180}
                value={settings.time_limit}
                onChange={(e) => updateTime(e.target.value)}
              />
            </div>

            <div className="p-4 rounded-2xl bg-zinc-950 border border-zinc-800">
              <div className="text-xs text-zinc-500">Rounds</div>
              <input
                className="mt-2 w-full bg-transparent border border-zinc-800 rounded-xl px-3 py-2"
                type="number"
                min={1}
                max={20}
                value={settings.rounds}
                onChange={(e) => updateRounds(e.target.value)}
              />
            </div>
          </div>

          {/* ✅ start button under settings */}
          <div className="mt-4">
            <Button className="w-full" onClick={startGame} disabled={!canStart}>
              Start game
            </Button>

            {!canStart && (
              <div className="text-xs text-zinc-500 mt-2">
                {players.length % 2 !== 0
                  ? "⚠️ Players count must be even to create teams of 2."
                  : "Assign all players into complete teams (2/2) to start."}
              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
