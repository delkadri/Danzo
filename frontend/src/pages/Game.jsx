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

function boxesFromTurn(turn) {
  const values = Array.isArray(turn?.guess_boxes) ? turn.guess_boxes : [];
  const statuses = turn?.word_status || {};
  const claims = turn?.word_claims || {};
  const statusByIndex = {};

  Object.entries(claims).forEach(([word, index]) => {
    if (Number.isInteger(index) && index >= 0 && index < 5) {
      statusByIndex[index] = statuses[word];
    }
  });

  return Array.from({ length: 5 }, (_, index) => {
    const text = typeof values[index] === "string" ? values[index] : "";
    const status = statusByIndex[index] || (text ? "wrong" : "empty");
    return {
      text,
      status,
      locked: status === "exact",
    };
  });
}

function boxClass(box, isGuesser) {
  if (box.status === "exact")
    return "border-emerald-500/50 bg-emerald-500/10 ring-2 ring-emerald-500/15";
  if (box.status === "close")
    return "border-yellow-500/50 bg-yellow-500/10 ring-2 ring-yellow-500/15";
  if (box.status === "wrong")
    return "border-rose-500/30 bg-rose-500/5";

  return isGuesser
    ? "border-zinc-200 bg-white focus-within:border-indigo-500/50 focus-within:ring-2 focus-within:ring-indigo-500/15 dark:border-zinc-800 dark:bg-zinc-950"
    : "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950";
}

function summaryWordClass(status) {
  if (status === "exact")
    return "border-emerald-500/50 bg-emerald-500/10 text-emerald-950 dark:text-emerald-100";
  if (status === "close")
    return "border-yellow-500/50 bg-yellow-500/10 text-yellow-950 dark:text-yellow-100";
  return "border-rose-500/40 bg-rose-500/10 text-rose-950 dark:text-rose-100";
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
  const latestRevisionRef = useRef(Array.from({ length: 5 }, () => 0));
  const composingRef = useRef(Array.from({ length: 5 }, () => false));
  const isGuesserRef = useRef(false);
  const countdownIntervalRef = useRef(null);

  const ct = room?.current_turn || {};
  const phase = room?.phase || "playing";
  const players = room?.players || [];

  const describerId = ct.describer_id;
  const guesserId = ct.guesser_id;

  const isDescriber = myId === describerId;
  const isGuesser = myId === guesserId;
  const isHost = room?.host_id === myId;

  useEffect(() => {
    isGuesserRef.current = isGuesser;
  }, [isGuesser]);

  const categoryOptions = ct.category_options || [];
  const chosenCategory = ct.chosen_category;
  const difficulty = ct.difficulty; // ✅ NEW
  const words = ct.words || [];

  const lastTurnSummary = room?.last_turn_summary || room?.last_turn || null;
  const lastTurnWords = Array.isArray(lastTurnSummary?.words) ? lastTurnSummary.words : [];
  const lastTurnWordStatus = lastTurnSummary?.word_status || {};
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
    setRemaining(
      typeof ct.remaining_time === "number" ? ct.remaining_time : null
    );
    setLocalTurnStarted(!!ct.turn_started);
    setBoxes(boxesFromTurn(ct));
    latestRevisionRef.current = Array.from({ length: 5 }, (_, index) => {
      const revision = ct.guess_box_revisions?.[index];
      return Number.isInteger(revision) ? revision : 0;
    });
    composingRef.current.fill(false);
    Object.values(submitTimersRef.current).forEach(clearTimeout);
    submitTimersRef.current = {};
    setCountdown(null);
    setCountdownCat(null);
    setCountdownDiff(null);

    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }

    const countdownDeadline = Number(ct.countdown_deadline_at || 0);
    if (countdownDeadline > Date.now() / 1000) {
      const updateCountdown = () => {
        const seconds = Math.max(
          0,
          Math.ceil(countdownDeadline - Date.now() / 1000)
        );
        if (seconds <= 0) {
          setCountdown(null);
          if (countdownIntervalRef.current) {
            clearInterval(countdownIntervalRef.current);
            countdownIntervalRef.current = null;
          }
          return;
        }
        setCountdown(seconds);
      };

      setCountdownCat(ct.chosen_category || null);
      setCountdownDiff(ct.difficulty || null);
      updateCountdown();
      countdownIntervalRef.current = setInterval(updateCountdown, 250);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ct.team_id, ct.turn_number]);

  useEffect(() => {
    return () => {
      Object.values(submitTimersRef.current).forEach(clearTimeout);
      submitTimersRef.current = {};

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
      const incomingRevisions = Array.isArray(payload?.revisions) ? payload.revisions : [];

      incomingRevisions.forEach((revision, index) => {
        if (Number.isInteger(revision)) {
          latestRevisionRef.current[index] = Math.max(
            latestRevisionRef.current[index] || 0,
            revision
          );
        }
      });

      // The guesser's local input is authoritative while typing. Applying the
      // server echo here can replace newer keystrokes with an older response.
      if (isGuesserRef.current) return;

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
      const revision = payload?.revision;

      if (typeof idx !== "number" || idx < 0 || idx > 4) return;
      if (Number.isInteger(revision) && revision < latestRevisionRef.current[idx]) {
        return;
      }
      const shouldLock = status === "exact";

      setBoxes((prev) => {
        const next = [...prev];
        const cur = next[idx] || { text: "", status: "empty", locked: false };

        const nextStatus =
          status === "exact" || status === "close" || status === "wrong"
            ? status
            : (cur.text ? cur.status : "empty");

        next[idx] = { ...cur, status: nextStatus, locked: shouldLock ? true : false };
        return next;
      });

      if (
        shouldLock &&
        isGuesserRef.current &&
        document.activeElement === inputRefs.current[idx]
      ) {
        window.requestAnimationFrame(() => {
          for (let nextIndex = idx + 1; nextIndex < inputRefs.current.length; nextIndex += 1) {
            const input = inputRefs.current[nextIndex];
            if (input && !input.disabled) {
              input.focus();
              return;
            }
          }
          inputRefs.current[idx]?.blur();
        });
      }
    }

    // ✅ after category chosen: reset UI + WAIT FOR difficulty selection
    function onCategoryChosen(payload) {
      const cat = payload?.category || chosenCategory;
      setCountdownCat(cat || null);

      setBoxes(makeEmptyBoxes());
      latestRevisionRef.current.fill(0);
      Object.values(submitTimersRef.current).forEach(clearTimeout);
      submitTimersRef.current = {};
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
      latestRevisionRef.current.fill(0);
      Object.values(submitTimersRef.current).forEach(clearTimeout);
      submitTimersRef.current = {};
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

  const submitBox = (index, val, revision) => {
    socket.emit("submit_guess_box", {
      room_id: roomId,
      index,
      guess: val,
      revision,
    });
  };

  const scheduleBoxSubmission = (index, val, revision) => {
    const timers = submitTimersRef.current;
    if (timers[index]) clearTimeout(timers[index]);

    timers[index] = setTimeout(() => {
      delete timers[index];
      submitBox(index, val, revision);
    }, 300);
  };

  const updateBoxText = (index, val) => {
    setBoxes((prev) => {
      const next = [...prev];
      if (!next[index] || next[index].locked) return prev;
      next[index] = {
        ...next[index],
        text: val,
        status: val ? "typing" : "empty",
      };
      return next;
    });

    if (!isGuesser) return;

    const revision = latestRevisionRef.current[index] + 1;
    latestRevisionRef.current[index] = revision;

    socket.emit("guess_boxes_typing", {
      room_id: roomId,
      index,
      text: val,
      revision,
    });

    if (!composingRef.current[index]) {
      scheduleBoxSubmission(index, val, revision);
    }
  };

  const flushBoxSubmission = (index, val) => {
    const timers = submitTimersRef.current;
    if (!timers[index]) return;

    clearTimeout(timers[index]);
    delete timers[index];
    submitBox(index, val, latestRevisionRef.current[index]);
  };

  const focusNextBox = (index) => {
    for (let nextIndex = index + 1; nextIndex < inputRefs.current.length; nextIndex += 1) {
      const input = inputRefs.current[nextIndex];
      if (input && !input.disabled) {
        input.focus();
        return;
      }
    }

    inputRefs.current[index]?.blur();
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
      <Card className="p-4 sm:p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xl font-bold">Game</div>
            <div className="text-sm text-zinc-600 dark:text-zinc-400">
              Round {ct.round || 1} — Turn {ct.turn_number || 1}
            </div>
          </div>

          <Button variant="danger" onClick={onLeave}>
            Leave
          </Button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <div className="min-w-0 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Describer</div>
            <div className="mt-1 flex min-w-0 items-center gap-2">
              <span className="min-w-0 truncate text-sm font-semibold sm:text-base">{describerName}</span>
              {isDescriber && <Badge className="shrink-0 border-indigo-700 bg-indigo-700/20">YOU</Badge>}
            </div>
          </div>
          <div className="min-w-0 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950">
            <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Guesser</div>
            <div className="mt-1 flex min-w-0 items-center gap-2">
              <span className="min-w-0 truncate text-sm font-semibold sm:text-base">{guesserName}</span>
              {isGuesser && <Badge className="shrink-0 border-indigo-700 bg-indigo-700/20">YOU</Badge>}
            </div>
          </div>

          {(chosenCategory || difficulty) && (
            <div className="col-span-2 flex flex-wrap gap-2 pt-1">
              {chosenCategory && <Badge>{categoryLabel(chosenCategory)}</Badge>}
              {difficulty && (
                <Badge className="border-indigo-600/40 bg-indigo-500/10 text-indigo-700 dark:text-indigo-200">
                  {diffLabel(difficulty)} ×{diffMult(difficulty)}
                </Badge>
              )}
            </div>
          )}
        </div>

        {roundActive && typeof remaining === "number" && (
          <div
            className="sticky top-2 z-30 mt-3 flex items-center justify-between rounded-2xl bg-indigo-600 px-4 py-3 text-white shadow-lg shadow-indigo-950/20 sm:static"
            aria-live="polite"
          >
            <span className="text-sm font-semibold">Time remaining</span>
            <span className="text-xl font-black tabular-nums">{remaining}s</span>
          </div>
        )}

        {(phase === "ranking" || phase === "results") && (
          <>
            <Card className="mt-5 p-4 sm:p-5">
              <div className="text-xl font-black mb-2">
                {phase === "results" ? "Final Ranking" : "Ranking"}
              </div>

              <div className="space-y-2">
                {ranking.length === 0 ? (
                  <div className="text-sm text-zinc-600 dark:text-zinc-400">Waiting for teams…</div>
                ) : (
                  ranking.map((r, idx) => {
                    const p1 = r?.players?.[0];
                    const p2 = r?.players?.[1];
                    const podium = ["🥇", "🥈", "🥉"][idx];
                    const names =
                      p1 && p2 ? `${playerNameById(p1)} & ${playerNameById(p2)}` : "—";

                    return (
                      <div
                        key={r.team_id}
                        className="flex min-w-0 justify-between gap-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950"
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <div
                            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-lg font-black shadow-sm ${
                              idx === 0
                                ? "border-amber-400/60 bg-amber-400/15"
                                : idx === 1
                                ? "border-slate-400/60 bg-slate-400/15"
                                : idx === 2
                                ? "border-orange-500/50 bg-orange-500/15"
                                : "border-indigo-500/40 bg-indigo-500/10 text-sm text-indigo-700 dark:text-indigo-200"
                            }`}
                            aria-label={`Rank ${idx + 1}`}
                            title={`Rank ${idx + 1}`}
                          >
                            {podium || idx + 1}
                          </div>
                          <div className="flex flex-col">
                            <span className="break-words text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                              Team {r.team_id + 1}: {names}
                            </span>
                            <span className="text-xs text-zinc-500">Score</span>
                          </div>
                        </div>
                        <span className="shrink-0 font-black tabular-nums">{r.score}</span>
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
                <div className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
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
              <Card className="mt-4 p-4 sm:p-5">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-black">Words</div>
                  {typeof lastTurnPoints === "number" && (
                    <div className="text-sm text-zinc-700 dark:text-zinc-300">
                      Points: <b className="text-zinc-950 dark:text-zinc-100">{lastTurnPoints}</b>
                    </div>
                  )}
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2">
                  {lastTurnWords.map((w) => {
                    const status = lastTurnWordStatus[w] || "unfound";
                    return (
                      <div
                        key={w}
                        className={`rounded-xl border p-3 ${summaryWordClass(status)}`}
                      >
                        <div className="font-semibold">{w}</div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            )}
          </>
        )}

        {phase === "playing" && (
          <div className="mt-5 grid gap-4">
            {showTurnControl && (
              <Card className="p-4 sm:p-5">
                {!turnStarted && isDescriber && <Button className="w-full" onClick={startTurn}>Start Turn</Button>}

                {!turnStarted && !isDescriber && (
                  <div className="text-sm text-zinc-600 dark:text-zinc-400">
                    Waiting for <b>{describerName}</b> to press <b>Start Turn</b>…
                  </div>
                )}

                {turnStarted && !chosenCategory && isDescriber && (
                  <div>
                    <div className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">Pick a category</div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {categoryOptions.map((cat) => (
                        <Button className="w-full" key={cat} onClick={() => chooseCategory(cat)}>
                          {categoryLabel(cat)}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {turnStarted && !chosenCategory && !isDescriber && (
                  <div className="text-sm text-zinc-600 dark:text-zinc-400">
                    Waiting for <b>{describerName}</b> to choose category…
                  </div>
                )}

                {/* ✅ NEW: choose difficulty after category */}
                {turnStarted && chosenCategory && !difficulty && isDescriber && (
                  <div>
                    <div className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">
                      Choose difficulty
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      {DIFFS.map((d) => (
                        <Button className="w-full" key={d.key} onClick={() => chooseDifficulty(d.key)}>
                          <span className="font-bold">{d.label}</span>
                          <span className="ml-2 text-xs text-indigo-100">({d.hint})</span>
                        </Button>
                      ))}
                    </div>
                  </div>
                )}

                {turnStarted && chosenCategory && !difficulty && !isDescriber && (
                  <div className="text-sm text-zinc-600 dark:text-zinc-400">
                    Waiting for <b>{describerName}</b> to choose difficulty…
                  </div>
                )}
              </Card>
            )}

            {inCountdown && (
              <Card className="p-5 text-center sm:p-6">
                <div className="text-sm text-zinc-600 dark:text-zinc-400">Starting</div>
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
              <Card className="p-4 sm:p-5">
                <div className="grid grid-cols-2 gap-2">
                  {words.map((w) => (
                    <div
                      key={w}
                      className="rounded-xl border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-800 dark:bg-zinc-950"
                    >
                      <div className="font-semibold">{w}</div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {roundActive && (
              <Card className="p-4 sm:p-5">
                <div className="flex items-center justify-between">
                  <div className="font-bold">Guesser</div>
                  <div className="text-xs text-zinc-500">
                    {isGuesser ? "Type directly in the boxes" : "Live guesses"}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 sm:gap-3">
                  {boxes.map((b, idx) => (
                    <div
                      key={idx}
                      className={`relative min-w-0 overflow-hidden rounded-xl border p-2 transition sm:p-3 ${boxClass(b, isGuesser)}`}
                      onClick={() => {
                        if (!isGuesser) return;
                        inputRefs.current[idx]?.focus?.();
                      }}
                    >
                      {(b.status === "exact" || b.status === "close") && (
                        <div className="absolute right-2 top-2">
                          <Badge
                            className={
                              b.status === "exact"
                                ? "border-emerald-600/50 bg-emerald-600/10"
                                : "border-yellow-600/50 bg-yellow-600/10"
                            }
                          >
                            +{formatPts(displayedPoints(b.status, ct?.difficulty))}
                          </Badge>
                        </div>
                      )}

                      {isGuesser ? (
                        <input
                          ref={(el) => (inputRefs.current[idx] = el)}
                          className={`min-h-11 w-full min-w-0 bg-transparent text-base font-semibold outline-none placeholder:text-zinc-400 dark:placeholder:text-zinc-700 ${
                            b.status === "exact" || b.status === "close" ? "pr-10" : ""
                          }`}
                          placeholder="…"
                          value={b.text}
                          onChange={(e) => updateBoxText(idx, e.target.value)}
                          onBlur={(e) => flushBoxSubmission(idx, e.target.value)}
                          onCompositionStart={() => {
                            composingRef.current[idx] = true;
                            const timer = submitTimersRef.current[idx];
                            if (timer) {
                              clearTimeout(timer);
                              delete submitTimersRef.current[idx];
                            }
                          }}
                          onCompositionEnd={(e) => {
                            composingRef.current[idx] = false;
                            updateBoxText(idx, e.currentTarget.value);
                          }}
                          onKeyDown={(e) => {
                            if (e.key !== "Enter" || e.isComposing) return;
                            e.preventDefault();
                            flushBoxSubmission(idx, e.currentTarget.value);
                            focusNextBox(idx);
                          }}
                          disabled={b.locked}
                          maxLength={60}
                          aria-label={`Answer ${idx + 1}`}
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={false}
                          inputMode="text"
                          enterKeyHint={idx === boxes.length - 1 ? "done" : "next"}
                        />
                      ) : (
                        <div
                          className="flex min-h-11 min-w-0 items-center truncate text-base font-semibold text-zinc-800 dark:text-zinc-200"
                          title={b.text || undefined}
                        >
                          {b.text ? b.text : <span className="text-zinc-400 dark:text-zinc-700">…</span>}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="mt-3 text-xs leading-5 text-zinc-500">
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
