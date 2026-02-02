import { useEffect, useMemo, useRef, useState } from "react";
import { socket } from "../lib/socket";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { categoryLabel } from "../lib/utils";

const EMPTY_BOXES = Array.from({ length: 5 }, () => ({
  text: "",
  status: "empty", // empty | exact | close | wrong
  locked: false,   // ✅ lock only exact now
}));

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

export default function Game({ myId, room, roomId, onLeave }) {
  const [remaining, setRemaining] = useState(null);

  // ✅ 5 boxes visible to everyone; guesser edits them directly
  const [boxes, setBoxes] = useState(EMPTY_BOXES);

  // ✅ local immediate response for start turn UI
  const [localTurnStarted, setLocalTurnStarted] = useState(false);

  // ✅ 3s countdown after category chosen
  const [countdown, setCountdown] = useState(null); // number | null
  const [countdownCat, setCountdownCat] = useState(null);

  // debounce submit per box
  const submitTimersRef = useRef({});
  const inputRefs = useRef(Array.from({ length: 5 }, () => null));

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
  const words = ct.words || [];

  // ✅ last turn summary (words + points)
  const lastTurnSummary = room?.last_turn_summary || room?.last_turn || null;
  const lastTurnWords = Array.isArray(lastTurnSummary?.words) ? lastTurnSummary.words : [];
  const lastTurnPoints =
    typeof lastTurnSummary?.points === "number" ? lastTurnSummary.points : null;

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

  // helper: turn team players ids -> names
  const playerNameById = useMemo(() => {
    const m = new Map();
    for (const p of players) m.set(p.id, p.name);
    return (id) => m.get(id) || (typeof id === "string" ? id.slice(0, 6) : "—");
  }, [players]);

  // reset UI when new turn changes (team change)
  useEffect(() => {
    setRemaining(null);
    setLocalTurnStarted(!!ct.turn_started);
    setBoxes(EMPTY_BOXES);
    setCountdown(null);
    setCountdownCat(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ct.team_id, ct.turn_number]);

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
    }

    // ✅ backend broadcasts the 5 texts live to everyone
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

    // ✅ backend returns per-box status (exact/close/wrong)
    function onGuessBoxResult(payload) {
      const idx = payload?.index;
      const status = payload?.status; // exact | close | wrong | ""

      if (typeof idx !== "number" || idx < 0 || idx > 4) return;

      setBoxes((prev) => {
        const next = [...prev];
        const cur = next[idx] || { text: "", status: "empty", locked: false };

        // ✅ lock ONLY exact (green). close (yellow) stays editable.
        const shouldLock = status === "exact";

        // if backend sends empty status, keep previous status unless empty
        const nextStatus =
          status === "exact" || status === "close" || status === "wrong"
            ? status
            : (cur.text ? cur.status : "empty");

        next[idx] = {
          ...cur,
          status: nextStatus,
          locked: shouldLock ? true : false,
        };
        return next;
      });
    }

    // ✅ start 3s countdown after category chosen (for everyone)
    function onCategoryChosen(payload) {
      const cat = payload?.category || chosenCategory;
      setCountdownCat(cat || null);

      setBoxes(EMPTY_BOXES);
      setRemaining(null);

      setCountdown(3);
      let c = 3;
      const t = setInterval(() => {
        c -= 1;
        if (c <= 0) {
          clearInterval(t);
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

    return () => {
      socket.off("timer_update", onTimerUpdate);
      socket.off("turn_started", onTurnStarted);
      socket.off("turn_ended", onTurnEnded);

      socket.off("guess_boxes_update", onGuessBoxesUpdate);
      socket.off("guess_box_result", onGuessBoxResult);

      socket.off("category_chosen", onCategoryChosen);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const turnStarted = !!ct.turn_started || localTurnStarted;

  const startTurn = () => {
    socket.emit("describer_start_turn", { room_id: roomId });
  };

  const chooseCategory = (cat) => {
    socket.emit("choose_category", { room_id: roomId, category: cat });
  };

  // ✅ Guesser typing: auto-submit debounced
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

  // ✅ UI phase control
  const inCountdown = typeof countdown === "number";
  const roundActive = !!chosenCategory && !inCountdown;
  const showTurnControl = phase === "playing" && !roundActive && !inCountdown;

  const onPlayAgain = () => {
    // primary
    socket.emit("host_play_again", { room_id: roomId });
    // fallback (if your backend uses another name)
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
            {isDescriber && (
              <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>
            )}

            <Badge>Guesser</Badge>
            <span className="font-semibold">{guesserName}</span>
            {isGuesser && (
              <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>
            )}
          </div>

          {/* ✅ show timer only during active round */}
          {roundActive && typeof remaining === "number" && (
            <div className="text-lg font-black">⏱ {remaining}s</div>
          )}
        </div>

        {/* ✅ Ranking stays until next describer presses Start Turn */}
        {(phase === "ranking" || phase === "results") && (
          <>
            <Card className="p-5 mt-5">
              <div className="text-xl font-black mb-2">
                {phase === "results" ? "Final Ranking" : "Ranking"}
              </div>

              <div className="space-y-2">
                {ranking.length === 0 ? (
                  <div className="text-sm text-zinc-400">
                    Waiting for teams…
                  </div>
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
                            <span className="text-xs text-zinc-500">
                              Score
                            </span>
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

              {/* ✅ Play again only for admin at end */}
              {phase === "results" && isHost && (
                <div className="mt-4">
                  <Button className="w-full" onClick={onPlayAgain}>
                    Play again
                  </Button>
                </div>
              )}
            </Card>

            {/* ✅ After each turn: show words + points */}
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

        {/* PLAYING */}
        {phase === "playing" && (
          <div className="mt-5 grid gap-4">
            {/* ✅ ONLY turn control BEFORE the round */}
            {showTurnControl && (
              <Card className="p-5">
                <div className="font-bold mb-2">Turn Control</div>

                {!turnStarted && isDescriber && (
                  <Button onClick={startTurn}>Start Turn</Button>
                )}

                {!turnStarted && !isDescriber && (
                  <div className="text-sm text-zinc-400">
                    Waiting for <b>{describerName}</b> to press <b>Start Turn</b>…
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
                    Waiting for <b>{describerName}</b> to choose category…
                  </div>
                )}
              </Card>
            )}

            {/* ✅ COUNTDOWN 3s visible to everyone */}
            {inCountdown && (
              <Card className="p-6 text-center">
                <div className="text-sm text-zinc-400">Category</div>
                <div className="text-2xl font-black mt-1">
                  {countdownCat ? categoryLabel(countdownCat) : "Starting…"}
                </div>
                <div className="text-5xl font-black mt-4">{countdown}</div>
              </Card>
            )}

            {/* ✅ WORDS visible to spectators + describer ONLY during active round */}
            {roundActive && !isGuesser && words && words.length > 0 && (
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

            {/* ✅ GUESSER CARD only during active round */}
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
                      className={`p-4 rounded-2xl border transition ${boxClass(
                        b,
                        isGuesser
                      )}`}
                      onClick={() => {
                        if (!isGuesser) return;
                        inputRefs.current[idx]?.focus?.();
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-xs text-zinc-500">Word #{idx + 1}</div>

                        {b.status === "exact" && (
                          <Badge className="border-emerald-600/50 bg-emerald-600/10">
                            +2
                          </Badge>
                        )}
                        {b.status === "close" && (
                          <Badge className="border-yellow-600/50 bg-yellow-600/10">
                            +1
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
                          disabled={b.locked} // ✅ only exact locks
                          autoComplete="off"
                          autoCorrect="off"
                          spellCheck={false}
                          inputMode="text"
                        />
                      ) : (
                        <div className="mt-2 text-base sm:text-lg font-semibold text-zinc-200 min-h-[28px]">
                          {b.text ? (
                            b.text
                          ) : (
                            <span className="text-zinc-700">…</span>
                          )}
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
                  ✅ Exact = green (+2) • 1–2 typos = yellow (+1)
                </div>
              </Card>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
