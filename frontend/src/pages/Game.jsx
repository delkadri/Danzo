import { useEffect, useMemo, useRef, useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { categoryLabel } from "../lib/utils";

function makeEmptyBoxes() {
  return Array.from({ length: 5 }, () => ({
    text: "",
    status: "empty", // empty | exact | close | wrong
    locked: false,   // lock only exact
  }));
}

function boxClass(box, isGuesser) {
  if (box.status === "exact")
    return "border-emerald-500/50 bg-emerald-500/10 ring-2 ring-emerald-500/15";
  if (box.status === "close")
    return "border-yellow-500/50 bg-yellow-500/10 ring-2 ring-yellow-500/15";
  if (box.status === "wrong")
    return "border-rose-500/30 bg-rose-500/5";

  return isGuesser
    ? "border-zinc-800 bg-zinc-950 focus-within:border-indigo-500/50 focus-within:ring-2 focus-within:ring-indigo-500/15"
    : "border-zinc-800 bg-zinc-950";
}
function formatPts(n) {
  // show 0.5 cleanly, no trailing .0
  return Number.isInteger(n) ? String(n) : String(n);
}

function displayedPoints(status, difficulty) {
  const d = (difficulty || "medium").toLowerCase();
  const mult = d === "easy" ? 0.5 : d === "hard" ? 2 : 1;

  const base = status === "exact" ? 2 : status === "close" ? 1 : 0;
  return base * mult;
}


const DIFFS = [
  { key: "easy", label: "Easy", hint: "Points / 2", mult: 0.5 },
  { key: "medium", label: "Medium", hint: "Normal", mult: 1 },
  { key: "hard", label: "Hard", hint: "Points x 2", mult: 2 },
];

function diffLabel(d) {
  if (d === "easy") return "Easy";
  if (d === "hard") return "Hard";
  return "Medium";
}

function diffMult(d) {
  if (d === "easy") return 0.5;
  if (d === "hard") return 2;
  return 1;
}

export default function Game({ myId, room, roomId, onLeave }) {
  const [remaining, setRemaining] = useState(null);
  const [boxes, setBoxes] = useState(makeEmptyBoxes);
  const [localTurnStarted, setLocalTurnStarted] = useState(false);

  // countdown
  const [countdown, setCountdown] = useState(null);
  const [countdownCat, setCountdownCat] = useState(null);
  const [countdownDiff, setCountdownDiff] = useState(null);

  const submitTimersRef = useRef({});
  const inputRefs = useRef(Array.from({ length: 5 }, () => null));
  const countdownIntervalRef = useRef(null);

  const ct = room?.current_turn || {};
  const phase = room?.phase || "playing";
  const players = room?.players || [];

  const describerId = ct.describer_id;
  const guesserId = ct.guesser_id;

  const isDescriber = myId === describerId;
  const isGuesser = myId === guesserId;
  const isHost = room?.host_id === myId;

  const categoryOptions = ct.category_options || [];
  const chosenCategory = ct.chosen_category;
  const difficulty = ct.difficulty; // ✅ NEW
  const words = ct.words || [];

  const lastTurnSummary = room?.last_turn_summary || room?.last_turn || null;
  const lastTurnWords = Array.isArray(lastTurnSummary?.words) ? lastTurnSummary.words : [];
  const lastTurnPoints =
    typeof lastTurnSummary?.points === "number" ? lastTurnSummary.points : null;

  useEffect(() => {
    setLocalTurnStarted(!!ct.turn_started);
  }, [ct.turn_started]);

  const describerName = useMemo(() => {
    return players.find((p) => p.id === describerId)?.name || "Describer";
  }, [players, describerId]);

  const guesserName = useMemo(() => {
    return players.find((p) => p.id === guesserId)?.name || "Guesser";
  }, [players, guesserId]);

  const playerNameById = useMemo(() => {
    const m = new Map();
    for (const p of players) m.set(p.id, p.name);
    return (id) => m.get(id) || (typeof id === "string" ? id.slice(0, 6) : "—");
  }, [players]);

  useEffect(() => {
    setRemaining(null);
    setLocalTurnStarted(!!ct.turn_started);
    setBoxes(makeEmptyBoxes());
    setCountdown(null);
    setCountdownCat(null);
    setCountdownDiff(null);

    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ct.team_id, ct.turn_number]);

  useEffect(() => {
    return () => {
      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    function onTimerUpdate(payload) {
      const r = payload?.remaining;
      setRemaining(typeof r === "number" ? r : null);
    }

    function onTurnStarted() {
      setLocalTurnStarted(true);
    }

    function onTurnEnded() {
      setLocalTurnStarted(false);
      setCountdown(null);
      setCountdownCat(null);
      setCountdownDiff(null);

      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
      }
    }

    function onGuessBoxesUpdate(payload) {
      const incoming = payload?.boxes;
      if (!Array.isArray(incoming)) return;

      setBoxes((prev) =>
        prev.map((b, i) => ({
          ...b,
          text: typeof incoming[i] === "string" ? incoming[i] : (b.text || ""),
        }))
      );
    }

    function onGuessBoxResult(payload) {
      const idx = payload?.index;
      const status = payload?.status;

      if (typeof idx !== "number" || idx < 0 || idx > 4) return;

      setBoxes((prev) => {
        const next = [...prev];
        const cur = next[idx] || { text: "", status: "empty", locked: false };

        const shouldLock = status === "exact";
        const nextStatus =
          status === "exact" || status === "close" || status === "wrong"
            ? status
            : (cur.text ? cur.status : "empty");

        next[idx] = { ...cur, status: nextStatus, locked: shouldLock ? true : false };
        return next;
      });
    }

    // ✅ after category chosen: reset UI + WAIT FOR difficulty selection
    function onCategoryChosen(payload) {
      const cat = payload?.category || chosenCategory;
      setCountdownCat(cat || null);

      setBoxes(makeEmptyBoxes());
      setRemaining(null);
      setCountdown(null);
      setCountdownDiff(null);

      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
      }
    }

    // ✅ after difficulty chosen: start 3..2..1 for everyone
    function onDifficultyChosen(payload) {
      const diff = payload?.difficulty || difficulty || "medium";
      setCountdownDiff(diff);

      setBoxes(makeEmptyBoxes());
      setRemaining(null);

      if (countdownIntervalRef.current) {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
      }

      setCountdown(3);
      let c = 3;

      countdownIntervalRef.current = setInterval(() => {
        c -= 1;
        if (c <= 0) {
          clearInterval(countdownIntervalRef.current);
          countdownIntervalRef.current = null;
          setCountdown(null);
          return;
        }
        setCountdown(c);
      }, 1000);
    }

    socket.on("timer_update", onTimerUpdate);
    socket.on("turn_started", onTurnStarted);
    socket.on("turn_ended", onTurnEnded);

    socket.on("guess_boxes_update", onGuessBoxesUpdate);
    socket.on("guess_box_result", onGuessBoxResult);

    socket.on("category_chosen", onCategoryChosen);
    socket.on("difficulty_chosen", onDifficultyChosen);

    return () => {
      socket.off("timer_update", onTimerUpdate);
      socket.off("turn_started", onTurnStarted);
      socket.off("turn_ended", onTurnEnded);

      socket.off("guess_boxes_update", onGuessBoxesUpdate);
      socket.off("guess_box_result", onGuessBoxResult);

      socket.off("category_chosen", onCategoryChosen);
      socket.off("difficulty_chosen", onDifficultyChosen);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const turnStarted = !!ct.turn_started || localTurnStarted;

  const startTurn = () => socket.emit("describer_start_turn", { room_id: roomId });
  const chooseCategory = (cat) => socket.emit("choose_category", { room_id: roomId, category: cat });

  const chooseDifficulty = (diff) => {
    socket.emit("choose_difficulty", { room_id: roomId, difficulty: diff });
  };

  const updateBoxText = (index, val) => {
    setBoxes((prev) => {
      const next = [...prev];
      if (!next[index] || next[index].locked) return prev;
      next[index] = { ...next[index], text: val };
      return next;
    });

    if (!isGuesser) return;

    socket.emit("guess_boxes_typing", { room_id: roomId, index, text: val });

    const timers = submitTimersRef.current;
    if (timers[index]) clearTimeout(timers[index]);

    timers[index] = setTimeout(() => {
      socket.emit("submit_guess_box", { room_id: roomId, index, guess: val });
    }, 220);
  };

  const ranking = room?.ranking || [];

  const inCountdown = typeof countdown === "number";
  const roundActive = !!chosenCategory && !!difficulty && !inCountdown;
  const showTurnControl = phase === "playing" && !roundActive && !inCountdown;

  const onPlayAgain = () => {
    socket.emit("host_play_again", { room_id: roomId });
    socket.emit("play_again", { room_id: roomId });
  };

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
            {isDescriber && <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>}

            <Badge>Guesser</Badge>
            <span className="font-semibold">{guesserName}</span>
            {isGuesser && <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>}

            {chosenCategory && (
              <Badge className="border-zinc-700 bg-zinc-900/40">
                {categoryLabel(chosenCategory)}
              </Badge>
            )}

            {difficulty && (
              <Badge className="border-indigo-700/50 bg-indigo-700/10">
                {diffLabel(difficulty)} ×{diffMult(difficulty)}
              </Badge>
            )}
          </div>

          {roundActive && typeof remaining === "number" && (
            <div className="text-lg font-black">⏱ {remaining}s</div>
          )}
        </div>

        {(phase === "ranking" || phase === "results") && (
          <>
            <Card className="p-5 mt-5">
              <div className="text-xl font-black mb-2">
                {phase === "results" ? "Final Ranking" : "Ranking"}
              </div>

              <div className="space-y-2">
                {ranking.length === 0 ? (
                  <div className="text-sm text-zinc-400">Waiting for teams…</div>
                ) : (
                  ranking.map((r, idx) => {
                    const p1 = r?.players?.[0];
                    const p2 = r?.players?.[1];
                    const names =
                      p1 && p2 ? `${playerNameById(p1)} & ${playerNameById(p2)}` : "—";

                    return (
                      <div
                        key={r.team_id}
                        className="p-3 rounded-xl bg-zinc-950 border border-zinc-800 flex justify-between"
                      >
                        <div className="flex gap-2 items-center">
                          <Badge>#{idx + 1}</Badge>
                          <div className="flex flex-col">
                            <span className="text-sm text-zinc-300 font-semibold">
                              Team {r.team_id + 1}: {names}
                            </span>
                            <span className="text-xs text-zinc-500">Score</span>
                          </div>
                        </div>
                        <span className="font-black">{r.score}</span>
                      </div>
                    );
                  })
                )}
              </div>

              {phase !== "results" && isDescriber && (
                <div className="mt-4">
                  <Button className="w-full" onClick={startTurn}>
                    Start Turn
                  </Button>
                </div>
              )}

              {phase !== "results" && !isDescriber && (
                <div className="mt-4 text-sm text-zinc-400">
                  Waiting for <b>{describerName}</b> to press <b>Start Turn</b>…
                </div>
              )}

              {phase === "results" && isHost && (
                <div className="mt-4">
                  <Button className="w-full" onClick={onPlayAgain}>
                    Play again
                  </Button>
                </div>
              )}
            </Card>

            {phase === "ranking" && lastTurnWords.length > 0 && (
              <Card className="p-5 mt-4">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-black">Words</div>
                  {typeof lastTurnPoints === "number" && (
                    <div className="text-sm text-zinc-300">
                      Points: <b className="text-zinc-100">{lastTurnPoints}</b>
                    </div>
                  )}
                </div>

                <div className="mt-3 grid md:grid-cols-2 gap-2">
                  {lastTurnWords.map((w) => (
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
          </>
        )}

        {phase === "playing" && (
          <div className="mt-5 grid gap-4">
            {showTurnControl && (
              <Card className="p-5">
                <div className="font-bold mb-2">Turn Control</div>

                {!turnStarted && isDescriber && <Button onClick={startTurn}>Start Turn</Button>}

                {!turnStarted && !isDescriber && (
                  <div className="text-sm text-zinc-400">
                    Waiting for <b>{describerName}</b> to press <b>Start Turn</b>…
                  </div>
                )}

                {turnStarted && !chosenCategory && isDescriber && (
                  <div className="mt-4">
                    <div className="text-sm text-zinc-400 mb-2">Pick a category (1 out of 2)</div>
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
                    Waiting for <b>{describerName}</b> to choose category…
                  </div>
                )}

                {/* ✅ NEW: choose difficulty after category */}
                {turnStarted && chosenCategory && !difficulty && isDescriber && (
                  <div className="mt-5">
                    <div className="text-sm text-zinc-400 mb-2">
                      Choose difficulty
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      {DIFFS.map((d) => (
                        <Button key={d.key} onClick={() => chooseDifficulty(d.key)}>
                          <span className="font-bold">{d.label}</span>
                          <span className="ml-2 text-xs text-zinc-300">({d.hint})</span>
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {turnStarted && chosenCategory && !difficulty && !isDescriber && (
                  <div className="mt-4 text-sm text-zinc-400">
                    Waiting for <b>{describerName}</b> to choose difficulty…
                  </div>
                )}
              </Card>
            )}

            {inCountdown && (
              <Card className="p-6 text-center">
                <div className="text-sm text-zinc-400">Starting</div>
                <div className="text-2xl font-black mt-1">
                  {countdownCat ? categoryLabel(countdownCat) : "—"}
                </div>
                <div className="mt-2">
                  <Badge className="border-indigo-700/50 bg-indigo-700/10">
                    {diffLabel(countdownDiff || difficulty || "medium")} ×{diffMult(countdownDiff || difficulty || "medium")}
                  </Badge>
                </div>
                <div className="text-5xl font-black mt-4">{countdown}</div>
              </Card>
            )}

            {roundActive && !isGuesser && words && words.length > 0 && (
              <Card className="p-5">
                <div className="font-bold mb-3">Words (visible to spectators + describer)</div>

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

            {roundActive && (
              <Card className="p-5">
                <div className="flex items-center justify-between">
                  <div className="font-bold">Guesser</div>
                  <div className="text-xs text-zinc-500">
                    {isGuesser ? "Type directly in the boxes" : "Live guesses"}
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {boxes.map((b, idx) => (
                    <div
                      key={idx}
                      className={`p-4 rounded-2xl border transition ${boxClass(b, isGuesser)}`}
                      onClick={() => {
                        if (!isGuesser) return;
                        inputRefs.current[idx]?.focus?.();
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-xs text-zinc-500">Word #{idx + 1}</div>

                        {(b.status === "exact" || b.status === "close") && (
                        <Badge
                          className={
                            b.status === "exact"
                              ? "border-emerald-600/50 bg-emerald-600/10"
                              : "border-yellow-600/50 bg-yellow-600/10"
                          }
                        >
                          +{formatPts(displayedPoints(b.status, ct?.difficulty))}
                        </Badge>
                      )}
                      </div>

                      {isGuesser ? (
                        <input
                          ref={(el) => (inputRefs.current[idx] = el)}
                          className="mt-2 w-full bg-transparent outline-none text-base sm:text-lg font-semibold placeholder:text-zinc-700"
                          placeholder="Type here…"
                          value={b.text}
                          onChange={(e) => updateBoxText(idx, e.target.value)}
                          disabled={b.locked}
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={false}
                          inputMode="text"
                        />
                      ) : (
                        <div className="mt-2 text-base sm:text-lg font-semibold text-zinc-200 min-h-[28px]">
                          {b.text ? b.text : <span className="text-zinc-700">…</span>}
                        </div>
                      )}

                      <div className="mt-2 text-[11px] text-zinc-500">
                        {b.status === "exact"
                          ? "Exact"
                          : b.status === "close"
                          ? "1–2 typos (editable)"
                          : ""}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-3 text-xs text-zinc-500">
                  ✅ Exact = green (+2) • 1–2 typos = yellow (+1) — Difficulty multiplier applies
                </div>
              </Card>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
