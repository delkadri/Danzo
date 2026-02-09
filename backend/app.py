import os
import json
import random
import re
import unicodedata
from typing import Dict, Any, List, Optional

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret_key")
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")
REST_ADMIN_TOKEN = os.getenv("REST_ADMIN_TOKEN", "")


socketio = SocketIO(
    app,
    cors_allowed_origins=CORS_ORIGIN,
    async_mode="eventlet"
)

@app.after_request
def add_cors_headers(resp):
    # REST CORS (Socket.IO a déjà cors_allowed_origins)
    resp.headers["Access-Control-Allow-Origin"] = CORS_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def api_preflight(_any):
    return ("", 204)


ALL_CATEGORIES = ["sport", "song", "movies", "geography", "history", "brand"]
WORDS_PATH = os.path.join(os.path.dirname(__file__), "data", "words.json")

# ✅ Fixed settings
DEFAULT_SETTINGS = {"time_limit": 40}
TARGET_SCORE = 50

WORDS_DB: Dict[str, List[str]] = {}
ROOMS: Dict[str, Dict[str, Any]] = {}


# -----------------------------
# Helpers
# -----------------------------
def normalize_room_id(room_id: str) -> str:
    rid = str(room_id or "").strip().upper()
    # ton jeu est en 4 digits : "0123"
    if not re.fullmatch(r"\d{4}", rid):
        return ""
    return rid


def require_admin_rest() -> Optional[Any]:
    """
    Retourne une réponse Flask (jsonify, code) si non autorisé, sinon None.
    Header attendu:
      Authorization: Bearer <REST_ADMIN_TOKEN>
    """
    if not REST_ADMIN_TOKEN:
        return jsonify({"error": "REST admin token not configured"}), 500

    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {REST_ADMIN_TOKEN}"
    if auth != expected:
        return jsonify({"error": "Unauthorized"}), 401
    return None


def remove_player_from_room(room_id: str, player_id: str, reason: str = "removed") -> bool:
    """
    Utilisable par REST et Socket events.
    - nettoie players/teams/draft_teams
    - gère host migration
    - si game en cours et teams invalides -> results
    - broadcast_room + notifs
    """
    room = ensure_room(room_id)
    if not room:
        return False

    player_id = str(player_id or "").strip()
    if not player_id or player_id not in room.get("players", {}):
        return False

    was_host = (room.get("host_id") == player_id)

    # remove player
    room["players"].pop(player_id, None)

    # remove from saved teams
    for t in room.get("teams", []):
        ps = t.get("players", [])
        if isinstance(ps, list) and player_id in ps:
            ps.remove(player_id)

    # remove from draft teams
    draft = room.get("draft_teams", [])
    if isinstance(draft, list):
        room["draft_teams"] = [[pid for pid in team if pid != player_id] for team in draft]

    # remove empty saved teams
    room["teams"] = [t for t in room.get("teams", []) if len(t.get("players", [])) > 0]

    # if no players -> delete room
    if len(room.get("players", {})) == 0:
        ROOMS.pop(room_id, None)
        return True

    # host migration
    if was_host:
        room["host_id"] = next(iter(room["players"].keys()))

    # if game running and teams invalid -> end game safely
    if room.get("phase") in ["playing", "ranking"] and not teams_are_valid(room):
        room["phase"] = "results"
        room["state"] = "results"
        room["ranking"] = compute_ranking(room)
        room["current_turn"] = {}
        stop_timer(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=room_id)
        broadcast_room(room_id)
        return True

    # if player left during active turn -> end turn
    ct = room.get("current_turn") or {}
    if room.get("phase") == "playing" and player_id in [ct.get("describer_id"), ct.get("guesser_id")]:
        end_team_turn(room_id, reason="player_left")
        return True

    broadcast_room(room_id)
    return True

def teams_are_valid(room: Dict[str, Any]) -> bool:
    teams = room.get("teams", [])
    if not isinstance(teams, list) or not teams:
        return False
    for t in teams:
        ps = t.get("players")
        if not isinstance(ps, list) or len(ps) != 2:
            return False
    return True

def points_multiplier(difficulty: str) -> float:
    d = (difficulty or "medium").lower()
    if d == "easy":
        return 0.5
    if d == "hard":
        return 2.0
    return 1.0

def load_words() -> None:
    global WORDS_DB
    with open(WORDS_PATH, "r", encoding="utf-8") as f:
        WORDS_DB = json.load(f)

    required_diffs = ["easy", "medium", "hard"]

    for cat in ALL_CATEGORIES:
        if cat not in WORDS_DB:
            raise ValueError(f"Missing category in words.json: {cat}")

        block = WORDS_DB[cat]

        # ✅ New format: {"easy":[...], "medium":[...], "hard":[...]}
        if isinstance(block, dict):
            for d in required_diffs:
                if d not in block:
                    raise ValueError(f"Missing difficulty '{d}' in category '{cat}'.")
                if not isinstance(block[d], list):
                    raise ValueError(f"Category '{cat}' difficulty '{d}' must be a list.")
                if len(block[d]) < 50:
                    raise ValueError(
                        f"Category '{cat}' difficulty '{d}' has too few words ({len(block[d])}/50)."
                    )

        # ✅ Old fallback format: ["word1","word2",...]
        elif isinstance(block, list):
            if len(block) < 50:
                raise ValueError(f"Category '{cat}' has too few words ({len(block)}/50).")

        else:
            raise ValueError(
                f"Invalid format for category '{cat}'. Expected list or dict with difficulties."
            )



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


def pick_words(category: str, difficulty: str, used_words: Dict[str, set], count: int = 5) -> List[str]:
    d = (difficulty or "medium").lower()
    if d not in ["easy", "medium", "hard"]:
        d = "medium"

    cat_block = WORDS_DB.get(category)

    # New format: WORDS_DB[category] = {"easy":[...], "medium":[...], "hard":[...]}
    if isinstance(cat_block, dict):
        words = cat_block.get(d, [])
    else:
        # fallback old format (all difficulties share same list)
        words = cat_block or []

    key = f"{category}:{d}"
    used = used_words.setdefault(key, set())

    remaining = [w for w in words if w not in used]
    if len(remaining) < count:
        used.clear()
        remaining = words[:]

    if len(remaining) < count:
        # not enough words in that difficulty
        return random.sample(words, min(count, len(words)))

    picked = random.sample(remaining, count)
    for w in picked:
        used.add(w)
    return picked

def ensure_room(room_id: str) -> Optional[Dict[str, Any]]:
    return ROOMS.get(room_id)


def is_host(room: Dict[str, Any], player_id: str) -> bool:
    return room["host_id"] == player_id


def compute_ranking(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    teams = room.get("teams", [])
    players = room.get("players", {})

    def names_for_team(t):
        ids = t.get("players", [])
        return [players.get(pid, {}).get("name", "Unknown") for pid in ids]

    ranking = sorted(teams, key=lambda x: x["score"], reverse=True)

    out = []
    for t in ranking:
        out.append({
            "team_id": t["team_id"],
            "players": t["players"],
            "player_names": names_for_team(t),   # ✅ NEW
            "score": t["score"]
        })
    return out



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
        cleaned = [pid for pid in team if pid in existing_ids]
        cleaned_draft.append(cleaned[:2])

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
        "round": current.get("round"),          # rotation count (1,2,3...)
        "turn_number": current.get("turn_number"),
        "turn_started": current.get("turn_started", False),
        "difficulty": current.get("difficulty"),
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
        "target_score": room.get("target_score", TARGET_SCORE),
        "players": players_list,
        "teams": teams_safe,
        "draft_teams": cleaned_draft,
        "current_turn": safe_turn,
        "last_turn_summary": room.get("last_turn_summary"),
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


# -----------------------------
# Turn logic
# -----------------------------
def prepare_next_turn(room: Dict[str, Any]) -> None:
    """
    Prepare next team turn but keep phase=ranking until describer presses Start Turn.
    A "round" here = one full rotation (all teams played once).
    """
    if not room.get("teams"):
        return

    # ✅ if teams are broken (disconnect/kick), end safely
    if not teams_are_valid(room):
        rid = room["room_id"]
        room["phase"] = "results"
        room["state"] = "results"
        room["ranking"] = compute_ranking(room)
        room["current_turn"] = {}
        stop_timer(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=rid)
        broadcast_room(rid)
        return

    if room.get("turn_order") is None:
        ids = [t["team_id"] for t in room["teams"]]
        random.shuffle(ids)
        room["turn_order"] = ids
        room["turn_index"] = 0
        room["current_round"] = 1
    else:
        n = len(room["turn_order"])
        room["turn_index"] = (room["turn_index"] + 1) % n
        if room["turn_index"] == 0:
            room["current_round"] += 1

    team_id = room["turn_order"][room["turn_index"]]
    team = next((t for t in room["teams"] if t["team_id"] == team_id), None)
    if not team:
        return

    ps = team.get("players", [])
    if not isinstance(ps, list) or len(ps) < 2:
        rid = room["room_id"]
        room["phase"] = "results"
        room["state"] = "results"
        room["ranking"] = compute_ranking(room)
        room["current_turn"] = {}
        stop_timer(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=rid)
        broadcast_room(rid)
        return

    p1, p2 = ps[0], ps[1]
    tp = int(team.get("turns_played", 0))

    if tp % 2 == 0:
        describer_id, guesser_id = p1, p2
    else:
        describer_id, guesser_id = p2, p1

    room["current_turn"] = {
        "team_id": team_id,
        "describer_id": describer_id,
        "guesser_id": guesser_id,
        "category_options": pick_two_categories(),
        "chosen_category": None,
        "difficulty": None,
        "words": None,
        "found_words": [],
        "remaining_time": None,
        "turn_started": False,
        "turn_points": 0,
        "round": room["current_round"],
        "turn_number": room["turn_number"],
    }

    room["turn_number"] += 1


def end_team_turn(room_id: str, reason: str) -> None:
    """
    End the current team turn, show ranking screen.
    If, at the end of a FULL rotation, best score >= TARGET_SCORE -> end game.
    Otherwise prepare next turn and stay on ranking until next describer presses Start Turn.
    """
    room = ROOMS.get(room_id)
    if not room:
        return

    stop_timer(room)

    ct = room.get("current_turn") or {}
    tn = int(ct.get("turn_number") or 0)

    # ✅ prevent double-end for same turn
    if tn and room.get("last_ended_turn_number") == tn:
        return
    room["last_ended_turn_number"] = tn

    team_id = ct.get("team_id")

    # optional stat
    team = next((t for t in room.get("teams", []) if t.get("team_id") == team_id), None)
    if team:
        team["turns_played"] = int(team.get("turns_played", 0)) + 1

    # ✅ store summary for frontend (Words card + Points X)
    room["last_turn_summary"] = {
        "team_id": team_id,
        "words": ct.get("words") or [],
        "points": int(ct.get("turn_points") or 0),
    }

    # show ranking screen
    room["phase"] = "ranking"
    room["ranking"] = compute_ranking(room)

    socketio.emit("turn_ended", {"reason": reason, "ranking": room["ranking"]}, room=room_id)
    broadcast_room(room_id)

    # no teams / order => stop
    if not room.get("teams") or not room.get("turn_order"):
        return

    n = len(room["turn_order"])
    current_index = room.get("turn_index", 0)
    next_index = (current_index + 1) % n
    finished_full_round = (next_index == 0)

    # ✅ end only at end of full rotation
    if finished_full_round:
        best = max((t["score"] for t in room["teams"]), default=0)
        if best >= room.get("target_score", TARGET_SCORE):
            room["phase"] = "results"
            room["state"] = "results"
            room["ranking"] = compute_ranking(room)
            room["current_turn"] = {}
            stop_timer(room)

            socketio.emit("game_end", {"room": room_public_state(room)}, room=room_id)
            broadcast_room(room_id)
            return

    # prepare next turn (but keep phase=ranking)
    prepare_next_turn(room)
    broadcast_room(room_id)


def start_round_after_countdown(room_id: str, delay: int = 3) -> None:
    def _run():
        socketio.sleep(delay)
        room = ROOMS.get(room_id)
        if not room:
            return
        ct = room.get("current_turn") or {}

        # If something changed (room ended / category reset), stop
        if room.get("phase") != "playing":
            return
        if not ct.get("chosen_category") or not ct.get("words"):
            return

        # Start the real round now
        ct["remaining_time"] = room["settings"]["time_limit"]  # 40
        broadcast_room(room_id)
        start_timer(room_id)

    socketio.start_background_task(_run)
# -----------------------------
# REST API
# -----------------------------
@app.get("/api/health")
def api_health():
    return jsonify({"ok": True})


@app.get("/api/meta")
def api_meta():
    return jsonify({
        "categories": ALL_CATEGORIES,
        "difficulties": ["easy", "medium", "hard"],
        "settings": DEFAULT_SETTINGS,
        "target_score": TARGET_SCORE,
    })


@app.get("/api/rooms/<room_id>")
def api_room_state(room_id):
    rid = normalize_room_id(room_id)
    if not rid:
        return jsonify({"error": "Invalid room_id"}), 400

    room = ensure_room(rid)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    return jsonify({"room": room_public_state(room)})


@app.get("/api/words/<category>")
def api_words(category):
    cat = str(category or "").strip().lower()
    if cat not in ALL_CATEGORIES:
        return jsonify({"error": "Invalid category"}), 400

    difficulty = str(request.args.get("difficulty", "medium")).strip().lower()
    if difficulty not in ["easy", "medium", "hard"]:
        difficulty = "medium"

    try:
        count = int(request.args.get("count", "50"))
    except Exception:
        count = 50
    count = max(1, min(200, count))

    block = WORDS_DB.get(cat)
    if isinstance(block, dict):
        words = block.get(difficulty, [])
    else:
        words = block or []

    # renvoie une sélection random stable côté API
    if len(words) <= count:
        out = list(words)
        random.shuffle(out)
        out = out[:count]
    else:
        out = random.sample(words, count)

    return jsonify({"category": cat, "difficulty": difficulty, "count": len(out), "words": out})


@app.post("/api/rooms/<room_id>/kick")
def api_kick(room_id):
    # ✅ sécurisé
    auth_err = require_admin_rest()
    if auth_err:
        return auth_err

    rid = normalize_room_id(room_id)
    if not rid:
        return jsonify({"error": "Invalid room_id"}), 400

    data = request.get_json(silent=True) or {}
    player_id = str(data.get("player_id", "")).strip()
    if not player_id:
        return jsonify({"error": "player_id is required"}), 400

    room = ensure_room(rid)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    # ne pas kicker l'host via REST non plus
    if player_id == room.get("host_id"):
        return jsonify({"error": "Cannot kick host"}), 400

    ok = remove_player_from_room(rid, player_id, reason="kicked")

    # notify + disconnect socket si possible
    try:
        socketio.emit("kicked", {"room_id": rid, "message": "Removed by admin (REST)."}, room=player_id)
        socketio.server.disconnect(player_id)
    except Exception:
        pass

    return jsonify({"ok": ok})


@app.post("/api/rooms/<room_id>/play_again")
def api_play_again(room_id):
    auth_err = require_admin_rest()
    if auth_err:
        return auth_err

    rid = normalize_room_id(room_id)
    if not rid:
        return jsonify({"error": "Invalid room_id"}), 400

    room = ensure_room(rid)
    if not room:
        return jsonify({"error": "Room not found"}), 404

    # même logique que host_play_again (mais REST)
    stop_timer(room)

    room["state"] = "lobby"
    room["phase"] = "lobby"

    for t in room.get("teams", []):
        t["score"] = 0
        t["turns_played"] = 0

    # tu voulais revenir au lobby "vide" -> on remet tout le monde unassigned
    room["teams"] = []
    room["draft_teams"] = []

    room["used_words"] = {}
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}
    room["ranking"] = []
    room["last_turn_summary"] = None

    broadcast_room(rid)
    socketio.emit("back_to_lobby", {"room": room_public_state(room)}, room=rid)

    return jsonify({"ok": True, "room": room_public_state(room)})

# -----------------------------
# Swagger / OpenAPI
# -----------------------------
def build_openapi_spec():
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Danzo / Ziago REST API",
            "version": "1.0.0",
            "description": "REST API for Danzo/Ziago (in addition to Socket.IO real-time API).",
        },
        "servers": [
            {"url": "/"}
        ],
        "tags": [
            {"name": "system"},
            {"name": "rooms"},
            {"name": "words"},
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "TOKEN"
                }
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {"error": {"type": "string"}},
                },
                "Health": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
                "Meta": {
                    "type": "object",
                    "properties": {
                        "categories": {"type": "array", "items": {"type": "string"}},
                        "difficulties": {"type": "array", "items": {"type": "string"}},
                        "settings": {"type": "object"},
                        "target_score": {"type": "integer"},
                    }
                },
                "RoomStateResponse": {
                    "type": "object",
                    "properties": {"room": {"type": "object"}},
                },
                "WordsResponse": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "difficulty": {"type": "string"},
                        "count": {"type": "integer"},
                        "words": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "KickRequest": {
                    "type": "object",
                    "properties": {
                        "player_id": {"type": "string"}
                    },
                    "required": ["player_id"]
                }
            }
        },
        "paths": {
            "/api/health": {
                "get": {
                    "tags": ["system"],
                    "summary": "Healthcheck",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Health"}}}
                        }
                    }
                }
            },
            "/api/meta": {
                "get": {
                    "tags": ["system"],
                    "summary": "API meta: categories, difficulties, settings",
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Meta"}}}
                        }
                    }
                }
            },
            "/api/rooms/{room_id}": {
                "get": {
                    "tags": ["rooms"],
                    "summary": "Get public room state",
                    "parameters": [
                        {
                            "name": "room_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "example": "1234"}
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Room state",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RoomStateResponse"}}}
                        },
                        "400": {
                            "description": "Invalid room_id",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        },
                        "404": {
                            "description": "Room not found",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        }
                    }
                }
            },
            "/api/words/{category}": {
                "get": {
                    "tags": ["words"],
                    "summary": "Get words for a category/difficulty",
                    "parameters": [
                        {
                            "name": "category",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "example": "sport"}
                        },
                        {
                            "name": "difficulty",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "enum": ["easy", "medium", "hard"], "default": "medium"}
                        },
                        {
                            "name": "count",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Words list",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/WordsResponse"}}}
                        },
                        "400": {
                            "description": "Invalid category",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        }
                    }
                }
            },
            "/api/rooms/{room_id}/kick": {
                "post": {
                    "tags": ["rooms"],
                    "summary": "Kick a player (admin token required)",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {
                            "name": "room_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "example": "1234"}
                        }
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/KickRequest"}}}
                    },
                    "responses": {
                        "200": {"description": "OK"},
                        "401": {
                            "description": "Unauthorized",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        },
                        "404": {
                            "description": "Room not found",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        }
                    }
                }
            },
            "/api/rooms/{room_id}/play_again": {
                "post": {
                    "tags": ["rooms"],
                    "summary": "Reset game back to lobby (admin token required)",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {
                            "name": "room_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "example": "1234"}
                        }
                    ],
                    "responses": {
                        "200": {"description": "OK"},
                        "401": {
                            "description": "Unauthorized",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        },
                        "400": {
                            "description": "Bad request",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        },
                        "404": {
                            "description": "Room not found",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
                        }
                    }
                }
            },
        }
    }


@app.get("/api/openapi.json")
def api_openapi_json():
    return jsonify(build_openapi_spec())


@app.get("/api/docs")
def api_docs():
    # Swagger UI via CDN (no dependency)
    html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>Danzo API Docs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style>
      body {{ margin:0; background:#0b0b0f; }}
      .topbar {{ display:none; }}
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({{
        url: "/api/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true
      }});
    </script>
  </body>
</html>
"""
    return html, 200, {"Content-Type": "text/html"}

# -----------------------------
# Socket events
# -----------------------------
@socketio.on("connect")
def on_connect():
    emit("connected", {"id": request.sid})


@socketio.on("disconnect")
def on_disconnect(reason=None):
    player_id = request.sid

    for room_id, room in list(ROOMS.items()):
        if player_id not in room.get("players", {}):
            continue

        was_host = (room.get("host_id") == player_id)

        room["players"].pop(player_id, None)

        # remove from saved teams
        for t in room.get("teams", []):
            ps = t.get("players", [])
            if isinstance(ps, list) and player_id in ps:
                ps.remove(player_id)

        # remove from draft teams too
        draft = room.get("draft_teams", [])
        if isinstance(draft, list):
            room["draft_teams"] = [[pid for pid in team if pid != player_id] for team in draft]

        # delete empty saved teams (but keep partially-filled teams; we handle validity below)
        room["teams"] = [t for t in room.get("teams", []) if len(t.get("players", [])) > 0]

        # room empty -> delete
        if len(room.get("players", {})) == 0:
            ROOMS.pop(room_id, None)
            continue

        # host migration
        if was_host:
            room["host_id"] = next(iter(room["players"].keys()))

        # ✅ if game is running and teams are now invalid -> end game safely
        if room.get("phase") in ["playing", "ranking"] and not teams_are_valid(room):
            room["phase"] = "results"
            room["state"] = "results"
            room["ranking"] = compute_ranking(room)
            room["current_turn"] = {}
            stop_timer(room)
            socketio.emit("game_end", {"room": room_public_state(room)}, room=room_id)
            broadcast_room(room_id)
            continue

        # if player left during active turn (and teams still valid) -> end turn
        ct = room.get("current_turn") or {}
        if room.get("phase") == "playing" and player_id in [ct.get("describer_id"), ct.get("guesser_id")]:
            end_team_turn(room_id, reason="player_left")
            continue

        broadcast_room(room_id)


@socketio.on("host_play_again")
def host_play_again(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        emit("error", {"message": "Only host can restart the game."})
        return

    # stop any running timer
    stop_timer(room)

    # reset game state back to lobby
    room["state"] = "lobby"
    room["phase"] = "lobby"

    # reset scores + turn rotation
    for t in room.get("teams", []):
        t["score"] = 0
        t["turns_played"] = 0

    # keep existing draft teams (or keep them as-is)
    room["draft_teams"] = [t["players"] for t in room.get("teams", [])] if room.get("teams") else room.get("draft_teams", [])

    room["used_words"] = {}
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}
    room["ranking"] = []
    room["last_turn_summary"] = None

    broadcast_room(room_id)
    socketio.emit("back_to_lobby", {"room": room_public_state(room)}, room=room_id)

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
        "target_score": TARGET_SCORE,
        "last_turn_summary": None,
        "players": {},
        "teams": [],
        "draft_teams": [],  # live teams in lobby

        "used_words": {},
        "timer_task": None,

        "turn_order": None,
        "turn_index": 0,
        "current_round": 1,   # rotation number
        "turn_number": 1,

        "current_turn": {},
        "ranking": [],
        "last_ended_turn_number": 0

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

    # clean draft teams from ghost ids
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
        room["draft_teams"] = [[pid for pid in team if pid != request.sid] for team in draft]

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

    cleaned_draft = cleaned_draft[:team_slots]
    while len(cleaned_draft) < team_slots:
        cleaned_draft.append([])

    room["draft_teams"] = cleaned_draft
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
        built.append({
            "team_id": idx,
            "players": [p1, p2],
            "score": 0,
            "turns_played": 0,
        })

    if used != all_players:
        emit("error", {"message": "All players must be assigned into teams of 2."})
        return

    room["teams"] = built
    room["draft_teams"] = [t["players"] for t in built]

    broadcast_room(room_id)

    # Frontend expects this
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

    # reset game state
    room["state"] = "playing"
    room["phase"] = "ranking"  # ✅ show ranking first

    room["used_words"] = {}
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}

    # ✅ ranking visible immediately (scores = 0)
    room["ranking"] = compute_ranking(room)

    broadcast_room(room_id)
    socketio.emit("game_started", {"room": room_public_state(room)}, room=room_id)

    # prepare next turn (still ranking)
    prepare_next_turn(room)
    broadcast_room(room_id)


@socketio.on("describer_start_turn")
def describer_start_turn(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    # allow from ranking too
    if room.get("phase") not in ["playing", "ranking"]:
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can start the turn."})
        return

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
    ct["difficulty"] = None
    ct["words"] = None
    ct["word_status"] = {}   # unfound | close | exact
    ct["word_claims"] = {}  # word -> box index
    ct["found_words"] = []
    ct["guess_boxes"] = ["", "", "", "", ""]
    ct["turn_points"] = 0

    # ✅ important: do NOT start the timer yet
    ct["remaining_time"] = None

    socketio.emit("category_chosen", {"category": category}, room=room_id)
    broadcast_room(room_id)

@socketio.on("choose_difficulty")
def choose_difficulty(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    difficulty = str((data or {}).get("difficulty", "")).strip().lower()

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can choose the difficulty."})
        return

    if not ct.get("turn_started"):
        emit("error", {"message": "Describer must press Start Turn first."})
        return

    # ✅ ONLY require category
    if not ct.get("chosen_category"):
        emit("error", {"message": "Choose a category first."})
        return

    if difficulty not in ["easy", "medium", "hard"]:
        emit("error", {"message": "Invalid difficulty."})
        return

    ct["difficulty"] = difficulty

    # ✅ NOW we pick words based on (category + difficulty)
    words = pick_words(ct["chosen_category"], difficulty, room["used_words"], count=5)
    ct["words"] = words
    ct["word_status"] = {w: "unfound" for w in words}
    ct["word_claims"] = {}
    ct["found_words"] = []
    ct["guess_boxes"] = ["", "", "", "", ""]
    ct["turn_points"] = 0

    # still countdown phase
    ct["remaining_time"] = None

    socketio.emit("difficulty_chosen", {"difficulty": difficulty, "words": words}, room=room_id)
    broadcast_room(room_id)

    # ✅ start real round AFTER 3 seconds
    start_round_after_countdown(room_id, delay=3)


@socketio.on("guess_boxes_typing")
def guess_boxes_typing(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    index = (data or {}).get("index")
    text = str((data or {}).get("text", ""))[:60]

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("guesser_id"):
        return
    if ct.get("remaining_time") is None:
        return

    if not isinstance(index, int) or index < 0 or index > 4:
        return

    if "guess_boxes" not in ct or not isinstance(ct["guess_boxes"], list):
        ct["guess_boxes"] = ["", "", "", "", ""]
    if not ct.get("difficulty"):
        return
    ct["guess_boxes"][index] = text
    socketio.emit("guess_boxes_update", {"boxes": ct["guess_boxes"]}, room=room_id)


@socketio.on("submit_guess_box")
def submit_guess_box(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    index = (data or {}).get("index")
    guess = str((data or {}).get("guess", "")).strip()[:60]

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    ct = room.get("current_turn") or {}
    if request.sid != ct.get("guesser_id"):
        return

    # block submit during countdown (round not started)
    if ct.get("remaining_time") is None:
        return

    if not isinstance(index, int) or index < 0 or index > 4:
        return

    if not ct.get("words"):
        return

    # ensure structures exist
    if "word_status" not in ct or not isinstance(ct["word_status"], dict):
        ct["word_status"] = {w: "unfound" for w in ct["words"]}
    if "word_claims" not in ct or not isinstance(ct["word_claims"], dict):
        ct["word_claims"] = {}

    if not guess:
        socketio.emit("guess_box_result", {"index": index, "status": ""}, room=room_id)
        return

    norm_guess = normalize_text(guess)

    # ✅ IMPORTANT: only exclude EXACT words, NOT CLOSE
    candidates = [w for w in ct["words"] if ct["word_status"].get(w) != "exact"]
    if not candidates:
        socketio.emit("guess_box_result", {"index": index, "status": "wrong"}, room=room_id)
        return

    best_word = None
    best_dist = 999

    for w in candidates:
        dist = levenshtein(norm_guess, normalize_text(w))
        if dist < best_dist:
            best_dist = dist
            best_word = w

    status = "wrong"
    points_delta = 0

    if best_word is not None:
        prev_status = ct["word_status"].get(best_word, "unfound")

        # prevent two boxes claiming same word (unless same box upgrading)
        claimed_by = ct["word_claims"].get(best_word)
        if claimed_by is not None and claimed_by != index:
            # already claimed by another box -> reject
            socketio.emit("guess_box_result", {"index": index, "status": "wrong"}, room=room_id)
            return

        if best_dist == 0:
            status = "exact"
            # score logic:
            # unfound -> exact = +2
            # close -> exact = +1 (upgrade)
            if prev_status == "unfound":
                points_delta = 2
            elif prev_status == "close":
                points_delta = 1

            ct["word_status"][best_word] = "exact"
            ct["word_claims"][best_word] = index

        elif best_dist <= 2:
            status = "close"
            # unfound -> close = +1
            if prev_status == "unfound":
                points_delta = 1
                ct["word_status"][best_word] = "close"
                ct["word_claims"][best_word] = index
            # close stays close (editable), no extra points
            # exact cannot happen here since exact words excluded from candidates

    mult = points_multiplier(ct.get("difficulty"))
    points_delta = points_delta * mult

    # ✅ broadcast box status to everyone
    socketio.emit("guess_box_result", {"index": index, "status": status}, room=room_id)

    # ✅ update score if needed
    if points_delta > 0:
        team_id = ct.get("team_id")
        team = next((t for t in room["teams"] if t["team_id"] == team_id), None)
        if team:
            team["score"] = float(team.get("score", 0)) + float(points_delta)
        ct["turn_points"] = float(ct.get("turn_points", 0)) + float(points_delta)
        socketio.emit("score_update", {"teams": room.get("teams", [])}, room=room_id)
        broadcast_room(room_id)

    # ✅ end condition suggestion:
    # End only when ALL words are exact (since close is editable)
    exact_count = sum(1 for w in ct["words"] if ct["word_status"].get(w) == "exact")
    if exact_count >= 5:
        end_team_turn(room_id, reason="all_found")
    if not ct.get("difficulty"):
        return


@socketio.on("host_kick_player")
def host_kick_player(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    player_id = str((data or {}).get("player_id", "")).strip()

    room = ensure_room(room_id)
    if not room:
        return
    if not is_host(room, request.sid):
        return

    # cannot kick the host via UI safety (still keep server safe)
    if player_id == room.get("host_id"):
        return

    if player_id not in room.get("players", {}):
        return

    # remove from players
    room["players"].pop(player_id, None)

    # remove from saved teams
    for t in room.get("teams", []):
        if player_id in t.get("players", []):
            t["players"].remove(player_id)

    # remove from draft teams
    draft = room.get("draft_teams", [])
    if isinstance(draft, list):
        room["draft_teams"] = [[pid for pid in team if pid != player_id] for team in draft]

    # delete empty saved teams
    room["teams"] = [t for t in room.get("teams", []) if len(t.get("players", [])) > 0]

    # force that socket to leave the room
    try:
        leave_room(room_id, sid=player_id)
    except Exception:
        pass

    # notify kicked user (frontend can react if you want)
    socketio.emit("kicked", {"room_id": room_id}, room=player_id)

    # if no players left -> remove room
    if len(room["players"]) == 0:
        ROOMS.pop(room_id, None)
        return
# ✅ if game is running and teams are now invalid -> end game safely
    if room.get("phase") in ["playing", "ranking"] and not teams_are_valid(room):
        room["phase"] = "results"
        room["state"] = "results"
        room["ranking"] = compute_ranking(room)
        room["current_turn"] = {}
        stop_timer(room)
        socketio.emit("game_end", {"room": room_public_state(room)}, room=room_id)
        broadcast_room(room_id)
        return
    
    broadcast_room(room_id)


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
load_words()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port)
