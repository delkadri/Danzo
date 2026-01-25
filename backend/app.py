import os
import json
import random
import string
import re
import unicodedata
from typing import Dict, Any, List, Optional

from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret_key")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")

socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ORIGIN,
    async_mode="eventlet"
)

ALL_CATEGORIES = ["sport", "song", "movies", "geography", "history", "brand"]
WORDS_PATH = os.path.join(os.path.dirname(__file__), "data", "words.json")

DEFAULT_SETTINGS = {
    "time_limit": 60,  # seconds
    "rounds": 5
}

WORDS_DB: Dict[str, List[str]] = {}
ROOMS: Dict[str, Dict[str, Any]] = {}


# -----------------------------
# Helpers
# -----------------------------
def load_words() -> None:
    global WORDS_DB
    with open(WORDS_PATH, "r", encoding="utf-8") as f:
        WORDS_DB = json.load(f)

    for cat in ALL_CATEGORIES:
        if cat not in WORDS_DB:
            raise ValueError(f"Missing category in words.json: {cat}")
        if len(WORDS_DB[cat]) < 50:
            raise ValueError(f"Category '{cat}' has too few words.")


def generate_room_code(length: int = 4) -> str:
    # ✅ 4 digits only
    chars = "0123456789"
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        if code not in ROOMS:
            return code


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def levenshtein(a: str, b: str) -> int:
    """Classic Levenshtein edit distance."""
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            repl = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, repl))
        prev = cur
    return prev[-1]


def pick_two_categories() -> List[str]:
    return random.sample(ALL_CATEGORIES, 2)


def pick_words(category: str, used_words: Dict[str, set], count: int = 5) -> List[str]:
    words = WORDS_DB.get(category, [])
    used = used_words.setdefault(category, set())

    remaining = [w for w in words if w not in used]
    if len(remaining) < count:
        used.clear()
        remaining = words[:]

    picked = random.sample(remaining, count)
    for w in picked:
        used.add(w)
    return picked


def ensure_room(room_id: str) -> Optional[Dict[str, Any]]:
    return ROOMS.get(room_id)


def is_host(room: Dict[str, Any], player_id: str) -> bool:
    return room["host_id"] == player_id


def room_public_state(room: Dict[str, Any]) -> Dict[str, Any]:
    players_list = []
    for pid, p in room["players"].items():
        players_list.append({
            "id": pid,
            "name": p["name"],
            "connected": p.get("connected", True),
        })

    # ✅ CLEAN draft teams: remove any player ids that no longer exist
    existing_ids = set(room["players"].keys())
    draft_raw = room.get("draft_teams", [])
    if not isinstance(draft_raw, list):
        draft_raw = []

    cleaned_draft = []
    for team in draft_raw:
        if not isinstance(team, list):
            continue
        # keep only players that still exist
        cleaned = [pid for pid in team if pid in existing_ids]
        # safety: max 2 per team
        cleaned_draft.append(cleaned[:2])

    # ✅ keep server memory clean too
    room["draft_teams"] = cleaned_draft

    current = room.get("current_turn") or {}
    safe_turn = {
        "team_id": current.get("team_id"),
        "describer_id": current.get("describer_id"),
        "guesser_id": current.get("guesser_id"),
        "category_options": current.get("category_options"),
        "chosen_category": current.get("chosen_category"),
        "words": current.get("words"),
        "found_words": current.get("found_words", []),
        "remaining_time": current.get("remaining_time"),
        "round": current.get("round"),
        "turn_number": current.get("turn_number"),
        "turn_started": current.get("turn_started", False),
        "phase": room.get("phase", "lobby")
    }

    teams_safe = []
    for t in room.get("teams", []):
        teams_safe.append({
            "team_id": t["team_id"],
            "players": t["players"],
            "score": t["score"]
        })

    return {
        "room_id": room["room_id"],
        "host_id": room["host_id"],
        "state": room["state"],
        "phase": room.get("phase", "lobby"),
        "settings": room["settings"],
        "players": players_list,
        "teams": teams_safe,

        # ✅ cleaned version only
        "draft_teams": cleaned_draft,

        "current_turn": safe_turn,
        "ranking": room.get("ranking", [])
    }



def broadcast_room(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    socketio.emit("room_state", {"room": room_public_state(room)}, room=room_id)


def stop_timer(room: Dict[str, Any]) -> None:
    room["timer_task"] = None


def start_timer(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    stop_timer(room)
    room["timer_task"] = True
    socketio.start_background_task(timer_loop, room_id)


def timer_loop(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return

    while True:
        if room.get("timer_task") is None:
            return

        ct = room.get("current_turn")
        if not ct:
            return

        remaining = ct.get("remaining_time", 0)
        if remaining <= 0:
            socketio.emit("timer_update", {"remaining": 0}, room=room_id)
            end_team_turn(room_id, reason="time_up")
            return

        socketio.emit("timer_update", {"remaining": remaining}, room=room_id)
        ct["remaining_time"] = remaining - 1
        socketio.sleep(1)


def compute_ranking(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    ranking = sorted(room.get("teams", []), key=lambda x: x["score"], reverse=True)
    return [{"team_id": t["team_id"], "players": t["players"], "score": t["score"]} for t in ranking]


def next_team_turn(room: Dict[str, Any]) -> None:
    """Select next team turn. Random first team, then rotate."""
    if not room.get("teams"):
        return

    if room.get("turn_order") is None:
        ids = [t["team_id"] for t in room["teams"]]
        random.shuffle(ids)
        room["turn_order"] = ids
        room["turn_index"] = 0
    else:
        room["turn_index"] = (room["turn_index"] + 1) % len(room["turn_order"])
        if room["turn_index"] == 0:
            room["current_round"] += 1

    if room["current_round"] > room["settings"]["rounds"]:
        room["phase"] = "results"
        room["state"] = "results"
        room["current_turn"] = {}
        stop_timer(room)
        room["ranking"] = compute_ranking(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=room["room_id"])
        broadcast_room(room["room_id"])
        return

    team_id = room["turn_order"][room["turn_index"]]
    team = next((t for t in room["teams"] if t["team_id"] == team_id), None)
    if not team:
        return

    describer_id = team["players"][0]
    guesser_id = team["players"][1]

    room["phase"] = "playing"
    room["current_turn"] = {
        "team_id": team_id,
        "describer_id": describer_id,
        "guesser_id": guesser_id,
        "category_options": pick_two_categories(),
        "chosen_category": None,
        "words": None,
        "found_words": [],
        "remaining_time": None,
        "turn_started": False,
        "round": room["current_round"],
        "turn_number": room["turn_number"]
    }

    room["turn_number"] += 1
    broadcast_room(room["room_id"])
    socketio.emit("team_turn_ready", {"turn": room_public_state(room)["current_turn"]}, room=room["room_id"])

def prepare_next_turn(room: Dict[str, Any]) -> None:
    """Prepare the next team turn but keep phase=ranking until describer presses Start Turn."""
    if not room.get("teams"):
        return

    # init order on first time
    if room.get("turn_order") is None:
        ids = [t["team_id"] for t in room["teams"]]
        random.shuffle(ids)
        room["turn_order"] = ids
        room["turn_index"] = 0
    else:
        room["turn_index"] = (room["turn_index"] + 1) % len(room["turn_order"])
        if room["turn_index"] == 0:
            room["current_round"] += 1

    # game finished
    if room["current_round"] > room["settings"]["rounds"]:
        room["phase"] = "results"
        room["state"] = "results"
        room["current_turn"] = {}
        stop_timer(room)
        room["ranking"] = compute_ranking(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=room["room_id"])
        return

    team_id = room["turn_order"][room["turn_index"]]
    team = next((t for t in room["teams"] if t["team_id"] == team_id), None)
    if not team:
        return

    describer_id = team["players"][0]
    guesser_id = team["players"][1]

    # ✅ keep phase ranking, just prepare the upcoming turn
    room["current_turn"] = {
        "team_id": team_id,
        "describer_id": describer_id,
        "guesser_id": guesser_id,
        "category_options": pick_two_categories(),
        "chosen_category": None,
        "words": None,
        "found_words": [],
        "remaining_time": None,
        "turn_started": False,
        "round": room["current_round"],
        "turn_number": room["turn_number"],
    }

    room["turn_number"] += 1


def end_team_turn(room_id: str, reason: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return

    stop_timer(room)

    # ✅ keep ranking screen
    room["phase"] = "ranking"
    room["ranking"] = compute_ranking(room)

    socketio.emit("turn_ended", {"reason": reason, "ranking": room["ranking"]}, room=room_id)
    broadcast_room(room_id)

    # ✅ PREPARE next turn immediately (but DO NOT switch phase to playing)
    prepare_next_turn(room)
    broadcast_room(room_id)



def delayed_next_turn(room_id: str) -> None:
    socketio.sleep(4)
    room = ROOMS.get(room_id)
    if not room:
        return
    next_team_turn(room)


# -----------------------------
# Socket events
# -----------------------------
@socketio.on("connect")
def on_connect():
    emit("connected", {"id": request.sid})


@socketio.on("disconnect")
def on_disconnect():
    player_id = request.sid

    for room_id, room in list(ROOMS.items()):
        if player_id in room["players"]:
            was_host = (room["host_id"] == player_id)

            room["players"].pop(player_id, None)

            # remove from saved teams
            for t in room.get("teams", []):
                if player_id in t["players"]:
                    t["players"].remove(player_id)

            # remove from draft teams too
            draft = room.get("draft_teams", [])
            if isinstance(draft, list):
                room["draft_teams"] = [ [pid for pid in team if pid != player_id] for team in draft ]

            # delete empty saved teams
            room["teams"] = [t for t in room.get("teams", []) if len(t["players"]) > 0]

            if len(room["players"]) == 0:
                ROOMS.pop(room_id, None)
                continue

            if was_host:
                room["host_id"] = next(iter(room["players"].keys()))

            ct = room.get("current_turn") or {}
            if room.get("phase") == "playing" and player_id in [ct.get("describer_id"), ct.get("guesser_id")]:
                end_team_turn(room_id, reason="player_left")

            broadcast_room(room_id)


@socketio.on("create_room")
def create_room(data):
    name = str((data or {}).get("name", "")).strip()[:20]
    if not name:
        emit("error", {"message": "Nickname is required."})
        return

    room_id = generate_room_code()

    ROOMS[room_id] = {
        "room_id": room_id,
        "host_id": request.sid,
        "state": "lobby",
        "phase": "lobby",
        "settings": dict(DEFAULT_SETTINGS),
        "players": {},
        "teams": [],

        # ✅ live teams in lobby
        "draft_teams": [],

        "used_words": {cat: set() for cat in ALL_CATEGORIES},
        "timer_task": None,
        "turn_order": None,
        "turn_index": 0,
        "current_round": 1,
        "turn_number": 1,
        "current_turn": {},
        "ranking": []
    }

    room = ROOMS[room_id]
    room["players"][request.sid] = {"id": request.sid, "name": name, "connected": True}

    join_room(room_id)
    emit("room_joined", {"room_id": room_id})
    broadcast_room(room_id)


@socketio.on("join_room")
def join_existing_room(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    name = str((data or {}).get("name", "")).strip()[:20]

    if not name:
        emit("error", {"message": "Nickname is required."})
        return

    room = ensure_room(room_id)
    if not room:
        emit("error", {"message": "Room not found."})
        return

    if room["phase"] not in ["lobby", "team_setup"]:
        emit("error", {"message": "Game already started. Create a new room."})
        return

    room["players"][request.sid] = {"id": request.sid, "name": name, "connected": True}
    # ✅ Clean draft teams from any ghost ids
    existing_ids = set(room["players"].keys())
    draft = room.get("draft_teams", [])
    if isinstance(draft, list):
        room["draft_teams"] = [[pid for pid in team if pid in existing_ids][:2] for team in draft]
    join_room(room_id)
    emit("room_joined", {"room_id": room_id})
    broadcast_room(room_id)


@socketio.on("leave_room")
def leave_existing_room(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    room["players"].pop(request.sid, None)

    # remove from saved teams
    for t in room.get("teams", []):
        if request.sid in t["players"]:
            t["players"].remove(request.sid)

    # remove from draft teams
    draft = room.get("draft_teams", [])
    if isinstance(draft, list):
        room["draft_teams"] = [ [pid for pid in team if pid != request.sid] for team in draft ]

    room["teams"] = [t for t in room.get("teams", []) if len(t["players"]) > 0]

    leave_room(room_id)

    if len(room["players"]) == 0:
        ROOMS.pop(room_id, None)
        return

    if room["host_id"] == request.sid:
        room["host_id"] = next(iter(room["players"].keys()))

    broadcast_room(room_id)


# ✅ LIVE DRAFT TEAMS (admin drag & drop)
@socketio.on("host_update_draft_teams")
def host_update_draft_teams(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    draft = (data or {}).get("draft_teams", [])

    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        return

    if not isinstance(draft, list):
        draft = []

    existing_ids = set(room["players"].keys())

    # ✅ compute expected number of teams
    team_slots = (len(existing_ids) + 1) // 2  # ceil(n/2)

    cleaned_draft = []
    used = set()

    for team in draft:
        if not isinstance(team, list):
            cleaned_draft.append([])
            continue

        clean_team = []
        for pid in team:
            if pid in existing_ids and pid not in used and len(clean_team) < 2:
                clean_team.append(pid)
                used.add(pid)

        cleaned_draft.append(clean_team)

    # ✅ force correct number of slots
    cleaned_draft = cleaned_draft[:team_slots]
    while len(cleaned_draft) < team_slots:
        cleaned_draft.append([])

    room["draft_teams"] = cleaned_draft
    broadcast_room(room_id)


# ✅ LIVE SETTINGS (time/rounds)
@socketio.on("host_update_settings")
def host_update_settings(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        return

    time_limit = int((data or {}).get("time_limit", room["settings"]["time_limit"]))
    rounds = int((data or {}).get("rounds", room["settings"]["rounds"]))

    room["settings"]["time_limit"] = max(20, min(180, time_limit))
    room["settings"]["rounds"] = max(1, min(20, rounds))

    broadcast_room(room_id)


@socketio.on("host_set_teams")
def host_set_teams(data):
    """
    Expected data:
    teams = [
      {"players":[id1,id2]},
      {"players":[id3,id4]},
      ...
    ]
    """
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    teams_data = (data or {}).get("teams", [])

    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        emit("error", {"message": "Only host can set teams."})
        return

    if not isinstance(teams_data, list) or len(teams_data) == 0:
        emit("error", {"message": "Invalid teams."})
        return

    all_players = set(room["players"].keys())
    used = set()

    built = []
    for idx, t in enumerate(teams_data):
        ps = t.get("players", [])
        if not isinstance(ps, list) or len(ps) != 2:
            emit("error", {"message": "Each team must have exactly 2 players."})
            return

        p1, p2 = ps[0], ps[1]
        if p1 not in all_players or p2 not in all_players or p1 == p2:
            emit("error", {"message": "Invalid players in a team."})
            return
        if p1 in used or p2 in used:
            emit("error", {"message": "A player cannot be in multiple teams."})
            return

        used.add(p1)
        used.add(p2)
        built.append({"team_id": idx, "players": [p1, p2], "score": 0})

    if used != all_players:
        emit("error", {"message": "All players must be assigned into teams of 2."})
        return

    room["teams"] = built

    # ✅ keep draft in sync too
    room["draft_teams"] = [t["players"] for t in built]

    broadcast_room(room_id)

    # ✅ FRONTEND expects this to auto-start game
    emit("teams_saved", {"ok": True})


@socketio.on("host_start_game")
def host_start_game(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        emit("error", {"message": "Only host can start the game."})
        return

    if len(room["players"]) < 2:
        emit("error", {"message": "Need at least 2 players."})
        return

    if not room.get("teams") or any(len(t["players"]) != 2 for t in room["teams"]):
        emit("error", {"message": "Host must create teams of 2 first."})
        return

    room["state"] = "playing"
    room["phase"] = "playing"

    room["used_words"] = {cat: set() for cat in ALL_CATEGORIES}
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["ranking"] = []

    room["current_turn"] = {}

    broadcast_room(room_id)
    socketio.emit("game_started", {"room": room_public_state(room)}, room=room_id)

    # ✅ show ranking first with next turn ready
    room["phase"] = "ranking"

    # ✅ ranking visible immediately
    room["ranking"] = compute_ranking(room)

    prepare_next_turn(room)
    broadcast_room(room_id)




@socketio.on("describer_start_turn")
def describer_start_turn(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    # ✅ allow from ranking too
    if room.get("phase") not in ["playing", "ranking"]:
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can start the turn."})
        return

    # ✅ switch to playing now
    room["phase"] = "playing"
    room["state"] = "playing"

    ct["turn_started"] = True
    broadcast_room(room_id)
    socketio.emit("turn_started", {"turn": room_public_state(room)["current_turn"]}, room=room_id)



@socketio.on("choose_category")
def choose_category(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    category = str((data or {}).get("category", "")).strip().lower()

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can choose the category."})
        return

    if not ct.get("turn_started"):
        emit("error", {"message": "Describer must press Start Turn first."})
        return

    options = ct.get("category_options") or []
    if category not in options:
        emit("error", {"message": "Category not available."})
        return

    ct["chosen_category"] = category
    words = pick_words(category, room["used_words"], count=5)
    ct["words"] = words
    ct["found_words"] = []
    ct["remaining_time"] = room["settings"]["time_limit"]

    socketio.emit("category_chosen", {"category": category, "words": words}, room=room_id)

    broadcast_room(room_id)
    start_timer(room_id)


@socketio.on("guess_typing")
def guess_typing(data):
    """Live typing from guesser -> broadcast to everyone."""
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    text = str((data or {}).get("text", ""))[:60]

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("guesser_id"):
        return

    socketio.emit("guess_typing_update", {"text": text, "guesser_id": request.sid}, room=room_id)


@socketio.on("submit_guess")
def submit_guess(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    guess = str((data or {}).get("guess", "")).strip()[:60]

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("guesser_id"):
        emit("error", {"message": "Only the guesser can submit guesses for this team."})
        return

    if not ct.get("words"):
        emit("error", {"message": "Wait for the category selection."})
        return

    if not guess:
        return

    norm_guess = normalize_text(guess)

    remaining_words = [w for w in ct["words"] if w not in ct["found_words"]]
    best_word = None
    best_dist = 999

    for w in remaining_words:
        dist = levenshtein(norm_guess, normalize_text(w))
        if dist < best_dist:
            best_dist = dist
            best_word = w

    points = 0
    result = "wrong"

    if best_word is not None:
        if best_dist == 0:
            points = 2
            result = "exact"
        elif best_dist <= 2:
            points = 1
            result = "close"

    socketio.emit(
        "guess_result",
        {"guess": guess, "result": result, "points": points, "matched_word": best_word},
        room=room_id
    )

    if points > 0 and best_word:
        if best_word not in ct["found_words"]:
            ct["found_words"].append(best_word)

        team_id = ct.get("team_id")
        team = next((t for t in room["teams"] if t["team_id"] == team_id), None)
        if team:
            team["score"] += points

        socketio.emit("score_update", {"teams": room.get("teams", [])}, room=room_id)
        broadcast_room(room_id)

        if len(ct["found_words"]) >= 5:
            end_team_turn(room_id, reason="all_found")


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    load_words()
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
else:
    load_words()
