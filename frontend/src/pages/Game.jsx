import { useEffect, useMemo, useState, useRef } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Badge } from "../components/Badge";
import { categoryLabel } from "../lib/utils";

export default function Game({ myId, room, roomId, onLeave }) {
  const [remaining, setRemaining] = useState(null);

  // ✅ Guess boxes UI
  const [selectedBox, setSelectedBox] = useState(0);
  const [boxes, setBoxes] = useState(
    Array.from({ length: 5 }, () => ({ text: "", status: "empty", locked: false }))
  );

  const [liveTyping, setLiveTyping] = useState("");

  // ✅ local immediate response for start turn UI
  const [localTurnStarted, setLocalTurnStarted] = useState(false);

  const inputRef = useRef(null);
  
  const ct = room?.current_turn || {};
  const phase = room?.phase || "playing";
  const players = room?.players || [];

  const describerId = ct.describer_id;
  const guesserId = ct.guesser_id;

  const isDescriber = myId === describerId;
  const isGuesser = myId === guesserId;

  const categoryOptions = ct.category_options || [];
  const chosenCategory = ct.chosen_category;

  const words = ct.words || []; // visible to everyone except guesser UI

  // keep local state synced
  useEffect(() => {
    setLocalTurnStarted(!!ct.turn_started);
  }, [ct.turn_started]);

  const describerName = useMemo(() => {
    return players.find((p) => p.id === describerId)?.name || "Describer";
  }, [players, describerId]);

  const guesserName = useMemo(() => {
    return players.find((p) => p.id === guesserId)?.name || "Guesser";
  }, [players, guesserId]);

  // reset UI when new turn changes (team change)
  useEffect(() => {
    setRemaining(null);
    setLiveTyping("");
    setLocalTurnStarted(!!ct.turn_started);
    setSelectedBox(0);
    setBoxes(Array.from({ length: 5 }, () => ({ text: "", status: "empty", locked: false })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ct.team_id, ct.turn_number]);

  useEffect(() => {
    function onTimerUpdate(payload) {
      setRemaining(payload?.remaining ?? null);
    }

    function onTyping(payload) {
      setLiveTyping(payload?.text || "");
    }

    // ✅ FIX: server confirms turn started
    function onTurnStarted() {
      setLocalTurnStarted(true);
    }

    function onTurnEnded() {
      setLiveTyping("");
      setLocalTurnStarted(false);
      // keep boxes as-is
    }

    // ✅ Apply result directly to selected box (no feed)
    function onGuessResult(payload) {
      const result = payload?.result; // exact | close | wrong
      const points = payload?.points || 0;

      // If wrong or empty => do nothing (as requested)
      if (!(result === "exact" || result === "close") || points <= 0) return;

      setBoxes((prev) => {
        const next = [...prev];
        const idx = selectedBox;

        if (!next[idx] || next[idx].locked) return prev;

        next[idx] = {
          ...next[idx],
          status: result === "exact" ? "exact" : "close",
          locked: true,
        };

        return next;
      });

      // auto go to next empty unlocked box
      setSelectedBox((prevIdx) => {
        for (let i = 0; i < 5; i++) {
          if (!boxes[i]?.locked && boxes[i]?.status === "empty" && boxes[i]?.text === "") {
            return i;
          }
        }
        // fallback: first unlocked
        for (let i = 0; i < 5; i++) {
          if (!boxes[i]?.locked) return i;
        }
        return prevIdx;
      });
    }

    socket.on("timer_update", onTimerUpdate);
    socket.on("guess_typing_update", onTyping);
    socket.on("turn_started", onTurnStarted);
    socket.on("turn_ended", onTurnEnded);
    socket.on("guess_result", onGuessResult);

    return () => {
      socket.off("timer_update", onTimerUpdate);
      socket.off("guess_typing_update", onTyping);
      socket.off("turn_started", onTurnStarted);
      socket.off("turn_ended", onTurnEnded);
      socket.off("guess_result", onGuessResult);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBox]);

  const turnStarted = !!ct.turn_started || localTurnStarted;

  const startTurn = () => {
    socket.emit("describer_start_turn", { room_id: roomId });
  };

  const chooseCategory = (cat) => {
    socket.emit("choose_category", { room_id: roomId, category: cat });
  };

  // Guess input actions
  const updateSelectedText = (val) => {
    setBoxes((prev) => {
      const next = [...prev];
      if (!next[selectedBox] || next[selectedBox].locked) return prev;
      next[selectedBox] = { ...next[selectedBox], text: val };
      return next;
    });

    // broadcast typing to everyone (as required)
    socket.emit("guess_typing", { room_id: roomId, text: val });
  };

  const submitSelectedGuess = () => {
    const text = boxes[selectedBox]?.text?.trim() || "";
    if (!text) return;

    socket.emit("submit_guess", { room_id: roomId, guess: text });

    // do NOT clear immediately: if wrong, keep it visible (user friendly)
    // but stop live typing if user wants:
    socket.emit("guess_typing", { room_id: roomId, text: "" });
  };

  const ranking = room?.ranking || [];

  return (
    <div className="grid gap-4">
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xl font-bold">Game</div>
            <div className="text-sm text-zinc-400">
              Round {ct.round || 1} — Turn {ct.turn_number || 1}
            </div>
          </div>

          <Button variant="danger" onClick={onLeave}>
            Leave
          </Button>
        </div>

        <div className="mt-5 flex items-center justify-between">
          <div className="flex flex-wrap gap-2 items-center">
            <Badge>Describer</Badge>
            <span className="font-semibold">{describerName}</span>
            {isDescriber && (
              <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>
            )}

            <Badge>Guesser</Badge>
            <span className="font-semibold">{guesserName}</span>
            {isGuesser && (
              <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>
            )}
          </div>

            {remaining !== null && (
            <div className="text-lg font-black">⏱ {remaining}s</div>
            )}
        </div>

        {/* ✅ Ranking stays until next describer presses Start Turn */}
        {(phase === "ranking" || phase === "results") && (
          <Card className="p-5 mt-5">
            <div className="text-xl font-black mb-2">
              {phase === "results" ? "Final Ranking" : "Ranking"}
            </div>

            <div className="space-y-2">
              {ranking.map((r, idx) => (
                <div
                  key={r.team_id}
                  className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 flex justify-between"
                >
                  <div className="flex gap-2 items-center">
                    <Badge>#{idx + 1}</Badge>
                    <span className="text-sm text-zinc-400">
                      Team {r.team_id + 1}
                    </span>
                  </div>
                  <span className="font-black">{r.score}</span>
                </div>
              ))}
            </div>

            {phase !== "results" && isDescriber && (
              <div className="mt-4">
                <Button className="w-full" onClick={startTurn}>
                  Start Turn
                </Button>
                <div className="text-xs text-zinc-500 mt-2">
                  Ranking will stay until you start the next turn.
                </div>
              </div>
            )}

            {phase !== "results" && !isDescriber && (
              <div className="mt-4 text-sm text-zinc-400">
                Waiting for next describer to press <b>Start Turn</b>…
              </div>
            )}
          </Card>
        )}

        {/* PLAYING */}
        {phase === "playing" && (
          <div className="mt-5 grid gap-4">
            <Card className="p-5">
              <div className="font-bold mb-2">Turn Control</div>

              {!turnStarted && isDescriber && (
                <Button onClick={startTurn}>Start Turn</Button>
              )}

              {!turnStarted && !isDescriber && (
                <div className="text-sm text-zinc-400">
                  Waiting for describer to press <b>Start Turn</b>…
                </div>
              )}

              {turnStarted && !chosenCategory && isDescriber && (
                <div className="mt-4">
                  <div className="text-sm text-zinc-400 mb-2">
                    Pick a category (1 out of 2)
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {categoryOptions.map((cat) => (
                      <Button key={cat} onClick={() => chooseCategory(cat)}>
                        {categoryLabel(cat)}
                      </Button>
                    ))}
                  </div>
                </div>
              )}

              {turnStarted && !chosenCategory && !isDescriber && (
                <div className="mt-4 text-sm text-zinc-400">
                  Waiting for describer to choose category…
                </div>
              )}

              {chosenCategory && (
                <div className="mt-4">
                  <div className="text-sm text-zinc-400">Category</div>
                  <div className="text-xl font-black">
                    {categoryLabel(chosenCategory)}
                  </div>
                </div>
              )}
            </Card>

            {/* ✅ WORDS visible to everyone EXCEPT the current guesser */}
            {!isGuesser && words && words.length > 0 && (
              <Card className="p-5">
                <div className="font-bold mb-3">
                  Words (visible to spectators + describer)
                </div>

                <div className="grid md:grid-cols-2 gap-2">
                  {words.map((w) => (
                    <div
                      key={w}
                      className="p-3 rounded-xl border border-zinc-800 bg-zinc-950"
                    >
                      <div className="font-semibold">{w}</div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* ✅ GUESSER UI (5 boxes, no feed, no scoreboard) */}
            <Card className="p-5">
              <div className="font-bold mb-2">Guesser</div>

              {!isGuesser ? (
                <div className="text-sm text-zinc-400">
                  Live typing:{" "}
                  <span className="font-semibold text-zinc-200">
                    {liveTyping || "..."}
                  </span>
                </div>
              ) : (
                <>
                  <div className="text-sm text-zinc-400 mb-3">
                    Tap a box, type your guess, and send.
                  </div>

                  {/* boxes */}
                  <div className="grid grid-cols-5 gap-2">
                    {boxes.map((b, idx) => {
                      const isSelected = idx === selectedBox;

                      const statusClass =
                        b.status === "exact"
                          ? "border-green-500/40 bg-green-500/10"
                          : b.status === "close"
                          ? "border-yellow-500/40 bg-yellow-500/10"
                          : isSelected
                          ? "border-indigo-500/40 bg-indigo-500/10"
                          : "border-zinc-800 bg-zinc-950";

                      return (
                        <button
                          key={idx}
                          onClick={() => {
                            setSelectedBox(idx);
                            setTimeout(() => inputRef.current?.focus(), 0);
                            }}
                          className={`p-3 rounded-xl border text-left min-h-[56px] ${statusClass}`}
                        >
                          <div className="text-xs text-zinc-500">#{idx + 1}</div>
                          <div className="text-sm font-semibold truncate">
                            {b.text || "—"}
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  {/* input for selected box */}
                  <div className="mt-4 flex gap-2">
                    <input
                        ref={inputRef}
                        className="w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 outline-none"
                        placeholder={`Word #${selectedBox + 1}`}
                        value={boxes[selectedBox]?.text || ""}
                        onChange={(e) => updateSelectedText(e.target.value)}
                        onKeyDown={(e) => {
                        if (e.key === "Enter") submitSelectedGuess();
                        }}
                        disabled={boxes[selectedBox]?.locked}
                        autoComplete="off"
                        inputMode="text"
                    />

                    <Button onClick={submitSelectedGuess} disabled={boxes[selectedBox]?.locked}>
                        Send
                    </Button>
                    </div>

                  <div className="mt-2 text-xs text-zinc-500">
                    ✅ Exact match = green (+2) • 1-2 typos = yellow (+1)
                  </div>
                </>
              )}
            </Card>
          </div>
        )}
      </Card>
    </div>
  );
}
