import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { socket } from "../lib/socket";

export default function Results({ myId, room, roomId, onLeave }) {
  const players = room?.players || [];
  const scores = room?.scores || {};

  const restart = () => {
    // simplest restart = leave then rejoin
    onLeave();
  };

  return (
    <div className="grid gap-4">
      <Card className="p-4 sm:p-6">
        <div className="text-2xl font-black">Game Over</div>
        <div className="text-sm text-zinc-600 dark:text-zinc-400">
          Room <span className="font-mono text-zinc-800 dark:text-zinc-200">{roomId}</span>
        </div>

        <div className="mt-6 text-xl font-bold">Final scores</div>

        {room?.settings?.mode === "TEAM" ? (
          <div className="mt-4 grid md:grid-cols-2 gap-3">
            <div className="flex justify-between rounded-2xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950">
              <span className="font-semibold">Team A</span>
              <span className="font-black">{scores.A || 0}</span>
            </div>
            <div className="flex justify-between rounded-2xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950">
              <span className="font-semibold">Team B</span>
              <span className="font-black">{scores.B || 0}</span>
            </div>
          </div>
        ) : (
          <div className="mt-4 grid md:grid-cols-2 gap-3">
            {players
              .map((p) => ({ ...p, score: scores[p.id] || 0 }))
              .sort((a, b) => b.score - a.score)
              .map((p, idx) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-2xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">
                      #{idx + 1} {p.name}
                    </span>
                    {p.id === myId && <Badge className="bg-indigo-700/40 border-indigo-700">YOU</Badge>}
                  </div>
                  <span className="font-black">{p.score}</span>
                </div>
              ))}
          </div>
        )}

        <div className="mt-6 grid gap-2 sm:grid-cols-2">
          <Button className="w-full" onClick={restart}>Back to Home</Button>
          <Button className="w-full" variant="danger" onClick={onLeave}>
            Leave room
          </Button>
        </div>
      </Card>
    </div>
  );
}
