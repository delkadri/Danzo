import { useEffect, useMemo, useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";

export default function Lobby({ myId, room, roomId, onLeave }) {
  const isHost = room?.host_id === myId;
  const players = room?.players || [];

  const teamSlots = Math.ceil(players.length / 2);

  const [draftTeams, setDraftTeams] = useState(
    Array.from({ length: teamSlots }, () => [])
  );

  // ✅ mobile selection state
  const [selectedPlayerId, setSelectedPlayerId] = useState(null);

  // non-host: follow backend draft teams live
  useEffect(() => {
    const incoming = room?.draft_teams;

    if (Array.isArray(incoming)) {
      const next = Array.from({ length: teamSlots }, (_, i) => incoming[i] || []);
      setDraftTeams(next);
    } else {
      setDraftTeams(Array.from({ length: teamSlots }, () => []));
    }
  }, [room?.draft_teams, teamSlots]);

  // host: ensure slots count + broadcast (also dedupe/clean)
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

  // map id -> player
  const playerById = useMemo(() => {
    const m = new Map();
    players.forEach((p) => m.set(p.id, p));
    return m;
  }, [players]);

  const selectedPlayer = selectedPlayerId ? playerById.get(selectedPlayerId) : null;

  const findPlayerTeamIndex = (pid) => {
    for (let i = 0; i < draftTeams.length; i++) {
      if (draftTeams[i]?.includes(pid)) return i;
    }
    return null;
  };

  const broadcastIfHost = (next) => {
    if (isHost) {
      socket.emit("host_update_draft_teams", { room_id: roomId, draft_teams: next });
    }
  };

  // tap player (toggle selection)
  const selectPlayer = (pid) => {
    if (!isHost) return;
    setSelectedPlayerId((prev) => (prev === pid ? null : pid));
  };

  // move selected player to a team
  const moveSelectedToTeam = (teamIndex) => {
    if (!isHost) return;
    if (!selectedPlayerId) return;

    setDraftTeams((prev) => {
      const next = prev.map((t) => (Array.isArray(t) ? [...t] : []));
      // remove from anywhere
      for (let i = 0; i < next.length; i++) {
        next[i] = next[i].filter((id) => id !== selectedPlayerId);
      }
      // add if room
      if ((next[teamIndex] || []).length >= 2) return prev;
      next[teamIndex].push(selectedPlayerId);

      broadcastIfHost(next);
      return next;
    });

    setSelectedPlayerId(null);
  };

  // move selected player to unassigned
  const moveSelectedToUnassigned = () => {
    if (!isHost) return;
    if (!selectedPlayerId) return;

    setDraftTeams((prev) => {
      const next = prev.map((t) => (Array.isArray(t) ? [...t] : []));
      for (let i = 0; i < next.length; i++) {
        next[i] = next[i].filter((id) => id !== selectedPlayerId);
      }
      broadcastIfHost(next);
      return next;
    });

    setSelectedPlayerId(null);
  };

  // ✅ kick player (admin)
  const kickPlayer = (playerId) => {
    if (!isHost) return;
    if (!playerId) return;

    // if you kick someone selected, clear selection
    setSelectedPlayerId((prev) => (prev === playerId ? null : prev));

    socket.emit("host_kick_player", {
      room_id: roomId,
      player_id: playerId,
    });
  };

  // start conditions
  const allTeamsComplete = draftTeams.every((t) => (t || []).length === 2);
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

  const rulesText = "40s per turn • First team to reach 50+ wins.";

  // styles helpers
  const dropBase = "rounded-2xl border bg-zinc-50 transition dark:bg-zinc-950";
  const dropNormal = "border-zinc-200 dark:border-zinc-800";
  const dropActive = "border-indigo-600/70 ring-2 ring-indigo-600/25";

  const chipWrap = "relative mr-1 mt-1 min-w-0";
  const chipBase =
    "min-h-12 max-w-full px-4 py-3 rounded-2xl border cursor-pointer active:scale-[0.98] transition select-none text-left";
  const chipNormal = "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/40";
  const chipAdmin = "border-indigo-700/50 bg-indigo-700/10";
  const chipSelected =
    "border-indigo-500/60 bg-indigo-500/10 ring-2 ring-indigo-500/20";

  const kickBtn =
    "absolute -right-3 -top-3 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-zinc-300 bg-white text-base leading-none text-zinc-600 shadow-sm hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:text-rose-300";

  const selectedHint = isHost
    ? selectedPlayer
      ? `Selected: ${selectedPlayer.name} — tap a Team or Unassigned`
      : "Tap a player, then tap a Team (or Unassigned)"
    : "Waiting for admin to create teams and start…";

  return (
    <div className="pb-28 sm:pb-0">
      <Card className="p-4 sm:p-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xl font-black sm:text-2xl">Lobby</div>

            {/* Room code hero (no COPY button now) */}
            <div className="mt-3 flex items-center gap-3">
              <div className="min-w-0">
                <div className="text-xs font-bold tracking-wider text-zinc-500">ROOM CODE</div>
                <div className="max-w-full font-mono text-3xl font-black tracking-[0.22em] text-zinc-950 dark:text-zinc-100 sm:text-4xl sm:tracking-[0.35em]">
                  {roomId}
                </div>
              </div>
            </div>

            <div className="mt-2 text-xs text-zinc-500">{rulesText}</div>

            <div className={`mt-3 text-sm leading-5 ${isHost ? "text-zinc-700 dark:text-zinc-300" : "text-zinc-600 dark:text-zinc-400"}`}>
              <b>{selectedHint}</b>
            </div>
          </div>

          {/* Leave inside card */}
          <Button variant="danger" onClick={onLeave}>
            Leave
          </Button>
        </div>

        {/* Unassigned */}
        <div className="mt-6">
          <div className="mb-2 text-sm font-medium text-zinc-600 dark:text-zinc-400">Unassigned players</div>

          <div
            className={`${dropBase} p-4 min-h-[88px] ${
              isHost && selectedPlayerId ? dropActive : dropNormal
            }`}
            onClick={() => {
              if (!isHost) return;
              if (!selectedPlayerId) return;
              moveSelectedToUnassigned();
            }}
          >
            <div className="flex flex-wrap gap-2">
              {unassignedPlayers.length === 0 ? (
                <Badge className="text-zinc-600 dark:text-zinc-400">All assigned ✅</Badge>
              ) : (
                unassignedPlayers.map((p) => {
                  const isSelected = selectedPlayerId === p.id;
                  const isAdmin = p.id === room?.host_id;

                  return (
                    <div key={p.id} className={chipWrap}>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          selectPlayer(p.id);
                        }}
                        className={[
                          chipBase,
                          isSelected ? chipSelected : isAdmin ? chipAdmin : chipNormal,
                        ].join(" ")}
                      >
                        <div className="flex items-center gap-2">
                          <span className="min-w-0 truncate text-base font-semibold">{p.name}</span>
                          {isAdmin && <Badge>ADMIN</Badge>}
                          {p.id === myId && (
                            <Badge className="bg-indigo-700/40 border-indigo-700">
                              YOU
                            </Badge>
                          )}
                        </div>
                      </button>

                      {/* ✅ Kick button (admin only, cannot kick self) */}
                      {isHost && p.id !== myId && (
                        <button
                          className={kickBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            kickPlayer(p.id);
                          }}
                          aria-label={`Kick ${p.name}`}
                          title={`Kick ${p.name}`}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {isHost && selectedPlayerId && (
              <div className="mt-3 text-xs text-zinc-500">
                Tap here to move selected player back to <b>Unassigned</b>.
              </div>
            )}
          </div>
        </div>

        {/* Teams */}
        <div className="mt-6">
          <div className="mb-2 text-sm font-medium text-zinc-600 dark:text-zinc-400">Teams</div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {draftTeams.map((t, idx) => {
              const team = Array.isArray(t) ? t : [];
              const canDropHere =
                isHost &&
                !!selectedPlayerId &&
                team.length < 2 &&
                findPlayerTeamIndex(selectedPlayerId) !== idx;

              return (
                <div
                  key={idx}
                  className={`p-4 min-h-[130px] ${dropBase} ${
                    canDropHere ? dropActive : dropNormal
                  }`}
                  onClick={() => {
                    if (!isHost) return;
                    if (!selectedPlayerId) return;
                    moveSelectedToTeam(idx);
                  }}
                >
                  <div className="flex items-center justify-between">
                    <div className="font-bold text-base">Team {idx + 1}</div>
                    <Badge>{team.length}/2</Badge>
                  </div>

                  <div className="mt-3 flex flex-wrap gap-2">
                    {team.length === 0 ? (
                      <div className="text-sm text-zinc-500">
                        {isHost
                          ? selectedPlayerId
                            ? "Tap to place selected player"
                            : "Tap a player above, then tap this team"
                          : "Waiting…"}
                      </div>
                    ) : (
                      team.map((pid) => {
                        const p = playerById.get(pid);
                        const isSelected = selectedPlayerId === pid;

                        return (
                          <div key={pid} className={chipWrap}>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                selectPlayer(pid);
                              }}
                              className={[
                                chipBase,
                                isSelected ? chipSelected : chipNormal,
                              ].join(" ")}
                            >
                              <span className="font-semibold text-base">
                                {p?.name || pid.slice(0, 6)}
                              </span>
                            </button>

                            {/* ✅ Kick button (admin only, cannot kick self) */}
                            {isHost && pid !== myId && (
                              <button
                                className={kickBtn}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  kickPlayer(pid);
                                }}
                                aria-label={`Kick ${p?.name || "player"}`}
                                title={`Kick ${p?.name || "player"}`}
                              >
                                ✕
                              </button>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>

                  {isHost && selectedPlayerId && (
                    <div className="mt-3 text-xs text-zinc-500">
                      Tap team card to move selected player here.
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Host validation message */}
        {isHost && !canStart && (
          <div className="mt-4 text-xs text-zinc-500">
            {players.length % 2 !== 0
              ? "⚠️ Players count must be even to create teams of 2."
              : "Assign all players into complete teams (2/2) to start."}
          </div>
        )}
      </Card>

      {/* Sticky bottom bar (mobile) */}
      {isHost && (
        <div className="safe-bottom fixed bottom-0 left-0 right-0 z-40 px-3 pt-3 sm:hidden">
          <div className="mx-auto max-w-xl rounded-2xl border border-zinc-200 bg-white/90 px-3 py-3 shadow-xl backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90">
            <Button className="w-full" onClick={startGame} disabled={!canStart}>
              Start game
            </Button>
          </div>
        </div>
      )}

      {/* Desktop host start button */}
      {isHost && (
        <div className="hidden sm:block mt-4">
          <Button className="w-full" onClick={startGame} disabled={!canStart}>
            Start game
          </Button>
        </div>
      )}
    </div>
  );
}
