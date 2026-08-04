import math
import random
import re
import time
import unicodedata
import uuid
from functools import wraps
from typing import Dict, Any, List, Optional, Tuple

from flask import jsonify, request
from flask_socketio import emit, join_room, leave_room

from .auth import require_admin_rest
from .constants import ALL_CATEGORIES, DEFAULT_SETTINGS, DIFFICULTIES, TARGET_SCORE
from .core import app
from .extensions import socketio
from .room_store import RoomStore, RoomStoreError
from .services import catalog_service


# -----------------------------
# Game constants
# -----------------------------
RECONNECT_GRACE_SECONDS = int(app.config["RECONNECT_GRACE_SECONDS"])
ROOM_STORE = RoomStore(
    redis_url=app.config["REDIS_URL"],
    ttl_seconds=app.config["ROOM_TTL_SECONDS"],
    key_prefix=app.config["ROOM_STORE_PREFIX"],
)

# -----------------------------
# Local connection cache
# -----------------------------
# Redis is authoritative in production. This cache keeps the currently handled
# room object available to nested helpers on the same instance.
ROOMS: Dict[str, Dict[str, Any]] = {}

# SESSIONS maps current socket sid -> session info
# This lets us know (room_id, player_id) when the socket disconnects.
SESSIONS: Dict[str, Dict[str, str]] = {}
ACTIVE_TIMER_ROOMS: set[str] = set()


# -----------------------------
# Helpers (IDs, auth, validation)
# -----------------------------
def get_player_sid(room: Dict[str, Any], player_id: str) -> Optional[str]:
    p = (room.get("players") or {}).get(player_id)
    if not p:
        return None
    sid = p.get("sid")
    return sid if isinstance(sid, str) and sid else None


def new_player_id() -> str:
    return uuid.uuid4().hex

def normalize_room_id(room_id: Any) -> str:
    rid = str(room_id or "").strip().upper()
    if not re.fullmatch(r"\d{4}", rid):
        return ""
    return rid

def bind_session(room_id: str, player_id: str, sid: str) -> None:
    SESSIONS[sid] = {"room_id": room_id, "player_id": player_id}

def get_session_player(room_id: str, sid: str) -> Optional[str]:
    s = SESSIONS.get(sid)
    if not s:
        return None
    if s.get("room_id") != room_id:
        return None
    return s.get("player_id")

def ensure_room(room_id: str) -> Optional[Dict[str, Any]]:
    room_id = normalize_room_id(room_id)
    if not room_id:
        return None

    if ROOM_STORE.enabled:
        try:
            room = ROOM_STORE.get(room_id)
            if room is None:
                ROOMS.pop(room_id, None)
                return None
            ROOMS[room_id] = room
            return room
        except RoomStoreError:
            app.logger.exception("Unable to load room %s from Redis.", room_id)

    return ROOMS.get(room_id)


def persist_room(room: Dict[str, Any]) -> None:
    room_id = normalize_room_id(room.get("room_id"))
    if not room_id:
        return
    ROOMS[room_id] = room
    if ROOM_STORE.enabled:
        try:
            ROOM_STORE.save(room)
        except RoomStoreError:
            app.logger.exception("Unable to persist room %s to Redis.", room_id)


def room_exists(room_id: str) -> bool:
    room_id = normalize_room_id(room_id)
    if not room_id:
        return False
    if ROOM_STORE.enabled:
        try:
            return ROOM_STORE.exists(room_id)
        except RoomStoreError:
            app.logger.exception("Unable to check room %s in Redis.", room_id)
    return room_id in ROOMS


def delete_room(room_id: str) -> None:
    room_id = normalize_room_id(room_id)
    if not room_id:
        return
    ROOMS.pop(room_id, None)
    if ROOM_STORE.enabled:
        try:
            ROOM_STORE.delete(room_id)
        except RoomStoreError:
            app.logger.exception("Unable to delete room %s from Redis.", room_id)


def synchronized_room_event(handler):
    @wraps(handler)
    def wrapped(data=None, *args, **kwargs):
        payload = data if isinstance(data, dict) else {}
        room_id = normalize_room_id(payload.get("room_id"))
        if not room_id:
            return handler(data, *args, **kwargs)
        try:
            with ROOM_STORE.lock(room_id):
                return handler(data, *args, **kwargs)
        except RoomStoreError:
            app.logger.exception("Unable to synchronize room event for %s.", room_id)
            emit("error", {"message": "The room is temporarily unavailable. Please retry."})
            return None

    return wrapped


def synchronized_room_route(handler):
    @wraps(handler)
    def wrapped(room_id, *args, **kwargs):
        normalized = normalize_room_id(room_id)
        try:
            with ROOM_STORE.lock(normalized):
                return handler(room_id, *args, **kwargs)
        except RoomStoreError:
            app.logger.exception("Unable to synchronize room route for %s.", normalized)
            return jsonify({"error": "The room is temporarily unavailable."}), 503

    return wrapped

def is_host(room: Dict[str, Any], player_id: str) -> bool:
    return room.get("host_id") == player_id

def teams_are_valid(room: Dict[str, Any]) -> bool:
    teams = room.get("teams", [])
    if not isinstance(teams, list) or not teams:
        return False
    for t in teams:
        ps = t.get("players")
        if not isinstance(ps, list) or len(ps) != 2:
            return False
    return True


# -----------------------------
# Words / scoring helpers
# -----------------------------
def points_multiplier(difficulty: str) -> float:
    d = (difficulty or "medium").lower()
    if d == "easy":
        return 0.5
    if d == "hard":
        return 2.0
    return 1.0

def pick_two_categories() -> List[str]:
    return random.sample(ALL_CATEGORIES, 2)

def pick_words(category: str, difficulty: str, used_words: Dict[str, set], count: int = 5) -> List[str]:
    d = (difficulty or "medium").lower()
    if d not in DIFFICULTIES:
        d = "medium"

    key = f"{category}:{d}"
    used = used_words.setdefault(key, set())

    words = catalog_service.get_words(
        category=category,
        difficulty=d,
        count=count,
        exclude_words=list(used),
    )

    if len(words) < count:
        used.clear()
        words = catalog_service.get_words(
            category=category,
            difficulty=d,
            count=count,
        )

    for w in words:
        used.add(w)
    return words


# -----------------------------
# Text match helpers
# -----------------------------
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


# -----------------------------
# Room state helpers / broadcast
# -----------------------------
def compute_ranking(room: Dict[str, Any]) -> List[Dict[str, Any]]:
    teams = room.get("teams", [])
    players = room.get("players", {})

    def names_for_team(t):
        ids = t.get("players", [])
        return [players.get(pid, {}).get("name", "Unknown") for pid in ids]

    ranking = sorted(teams, key=lambda x: x.get("score", 0), reverse=True)

    out = []
    for t in ranking:
        out.append({
            "team_id": t["team_id"],
            "players": t["players"],
            "player_names": names_for_team(t),
            "score": t.get("score", 0)
        })
    return out

def room_public_state(room: Dict[str, Any]) -> Dict[str, Any]:
    players_list = []
    for pid, p in room.get("players", {}).items():
        players_list.append({
            "id": pid,                         # ✅ stable player_id
            "name": p.get("name", "Player"),
            "connected": p.get("connected", True),
        })

    existing_ids = set(room.get("players", {}).keys())
    draft_raw = room.get("draft_teams", [])
    if not isinstance(draft_raw, list):
        draft_raw = []

    cleaned_draft = []
    for team in draft_raw:
        if not isinstance(team, list):
            cleaned_draft.append([])
            continue
        cleaned = [pid for pid in team if pid in existing_ids]
        cleaned_draft.append(cleaned[:2])

    room["draft_teams"] = cleaned_draft

    current = room.get("current_turn") or {}
    safe_turn = {
        "team_id": current.get("team_id"),
        "describer_id": current.get("describer_id"),     # player_id
        "guesser_id": current.get("guesser_id"),         # player_id
        "category_options": current.get("category_options"),
        "chosen_category": current.get("chosen_category"),
        "difficulty": current.get("difficulty"),
        "words": current.get("words"),
        "found_words": current.get("found_words", []),
        "word_status": current.get("word_status", {}),
        "word_claims": current.get("word_claims", {}),
        "guess_boxes": current.get("guess_boxes", ["", "", "", "", ""]),
        "guess_box_revisions": current.get("guess_box_revisions", [0, 0, 0, 0, 0]),
        "countdown_deadline_at": current.get("countdown_deadline_at"),
        "remaining_time": current.get("remaining_time"),
        "round": current.get("round"),
        "turn_number": current.get("turn_number"),
        "turn_started": current.get("turn_started", False),
    }

    teams_safe = []
    for t in room.get("teams", []):
        teams_safe.append({
            "team_id": t["team_id"],
            "players": t["players"],   # player_ids
            "score": t.get("score", 0)
        })

    return {
        "room_id": room.get("room_id"),
        "host_id": room.get("host_id"),  # player_id
        "state": room.get("state", "lobby"),
        "phase": room.get("phase", "lobby"),
        "settings": room.get("settings", dict(DEFAULT_SETTINGS)),
        "target_score": room.get("target_score", TARGET_SCORE),
        "players": players_list,
        "teams": teams_safe,
        "draft_teams": cleaned_draft,
        "current_turn": safe_turn,
        "last_turn_summary": room.get("last_turn_summary"),
        "ranking": room.get("ranking", []),
    }

def broadcast_room(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    public_state = room_public_state(room)
    persist_room(room)
    socketio.emit("room_state", {"room": public_state}, room=room_id)


# -----------------------------
# Timer
# -----------------------------
def stop_timer(room: Dict[str, Any]) -> None:
    room["timer_task"] = None

def start_timer(room_id: str, resume: bool = False) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    ct = room.get("current_turn") or {}
    remaining = int(ct.get("remaining_time") or 0)
    if remaining <= 0:
        return

    stop_timer(room)
    room["timer_task"] = True
    if not resume or not ct.get("deadline_at"):
        ct["deadline_at"] = time.time() + remaining
    persist_room(room)

    if room_id in ACTIVE_TIMER_ROOMS:
        return
    ACTIVE_TIMER_ROOMS.add(room_id)
    socketio.start_background_task(timer_loop, room_id)

def timer_loop(room_id: str) -> None:
    try:
        while True:
            try:
                with ROOM_STORE.lock(room_id):
                    room = ensure_room(room_id)
                    if not room or room.get("timer_task") is None:
                        return

                    ct = room.get("current_turn")
                    if not ct:
                        return

                    deadline = float(ct.get("deadline_at") or time.time())
                    remaining = max(0, math.ceil(deadline - time.time()))
                    ct["remaining_time"] = remaining

                    if remaining <= 0:
                        socketio.emit("timer_update", {"remaining": 0}, room=room_id)
                        end_team_turn(room_id, reason="time_up")
                        return

                    persist_room(room)
                    socketio.emit("timer_update", {"remaining": remaining}, room=room_id)
            except RoomStoreError:
                app.logger.exception("Timer synchronization failed for room %s.", room_id)
                return
            socketio.sleep(1)
    finally:
        ACTIVE_TIMER_ROOMS.discard(room_id)


def resume_room_timer(room_id: str, room: Dict[str, Any]) -> None:
    ct = room.get("current_turn") or {}
    if (
        room.get("phase") == "playing"
        and room.get("timer_task") is not None
        and ct.get("remaining_time") is not None
    ):
        start_timer(room_id, resume=True)


# -----------------------------
# Turn logic
# -----------------------------
def prepare_next_turn(room: Dict[str, Any]) -> None:
    if not room.get("teams"):
        room["current_turn"] = {}
        return

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
    if not team or not isinstance(team.get("players"), list) or len(team["players"]) != 2:
        room["current_turn"] = {}
        return

    p1, p2 = team["players"][0], team["players"][1]
    tp = int(team.get("turns_played", 0))

    if tp % 2 == 0:
        describer_id, guesser_id = p1, p2
    else:
        describer_id, guesser_id = p2, p1

    room["current_turn"] = {
        "team_id": team_id,
        "describer_id": describer_id,   # player_id
        "guesser_id": guesser_id,       # player_id
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
        "word_status": {},
        "word_claims": {},
        "guess_boxes": ["", "", "", "", ""],
        "guess_box_revisions": [0, 0, 0, 0, 0],
        "countdown_deadline_at": None,
    }
    room["turn_number"] += 1

def end_team_turn(room_id: str, reason: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return

    stop_timer(room)

    ct = room.get("current_turn") or {}
    tn = int(ct.get("turn_number") or 0)

    if tn and room.get("last_ended_turn_number") == tn:
        return
    room["last_ended_turn_number"] = tn

    team_id = ct.get("team_id")

    team = next((t for t in room.get("teams", []) if t.get("team_id") == team_id), None)
    if team:
        team["turns_played"] = int(team.get("turns_played", 0)) + 1

    room["last_turn_summary"] = {
        "team_id": team_id,
        "words": ct.get("words") or [],
        "word_status": dict(ct.get("word_status") or {}),
        "points": float(ct.get("turn_points") or 0),
    }

    room["phase"] = "ranking"
    room["ranking"] = compute_ranking(room)

    socketio.emit("turn_ended", {"reason": reason, "ranking": room["ranking"]}, room=room_id)
    broadcast_room(room_id)

    if not room.get("teams") or not room.get("turn_order"):
        return

    n = len(room["turn_order"])
    current_index = room.get("turn_index", 0)
    next_index = (current_index + 1) % n
    finished_full_round = (next_index == 0)

    if finished_full_round:
        best = max((t.get("score", 0) for t in room["teams"]), default=0)
        if best >= room.get("target_score", TARGET_SCORE):
            room["phase"] = "results"
            room["state"] = "results"
            room["ranking"] = compute_ranking(room)
            room["current_turn"] = {}
            stop_timer(room)
            socketio.emit("game_end", {"room": room_public_state(room)}, room=room_id)
            broadcast_room(room_id)
            return

    prepare_next_turn(room)
    broadcast_room(room_id)

def start_round_after_countdown(room_id: str, delay: int = 3) -> None:
    def _run():
        socketio.sleep(delay)
        try:
            with ROOM_STORE.lock(room_id):
                room = ensure_room(room_id)
                if not room:
                    return
                ct = room.get("current_turn") or {}

                if room.get("phase") != "playing":
                    return
                if not ct.get("chosen_category") or not ct.get("words"):
                    return

                ct["countdown_deadline_at"] = None
                ct["remaining_time"] = room["settings"]["time_limit"]
                broadcast_room(room_id)
                start_timer(room_id)
        except RoomStoreError:
            app.logger.exception("Countdown synchronization failed for room %s.", room_id)

    socketio.start_background_task(_run)


# -----------------------------
# Player removal (shared)
# -----------------------------
def remove_player_from_room(room_id: str, player_id: str, reason: str = "removed") -> bool:
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

    # remove empty teams
    room["teams"] = [t for t in room.get("teams", []) if len(t.get("players", [])) > 0]

    # if no players -> delete room
    if len(room.get("players", {})) == 0:
        delete_room(room_id)
        return True

    # host migration
    if was_host:
        room["host_id"] = next(iter(room["players"].keys()))

    # if game running and teams invalid -> end safely
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


# -----------------------------
# REST API
# -----------------------------
@app.get("/api/health")
def api_health():
    health = catalog_service.healthcheck()
    if not app.config["REDIS_URL_VALID"]:
        redis_status = "invalid_configuration"
    else:
        try:
            redis_status = "up" if ROOM_STORE.ping() else "disabled"
        except RoomStoreError:
            redis_status = "unavailable"
    redis_ready = redis_status == "up"
    response = {
        **health,
        "ok": bool(health.get("ok")) and (
            redis_ready or not app.config["REDIS_REQUIRED"]
        ),
        "redis": redis_status,
        "redis_required": app.config["REDIS_REQUIRED"],
        "shared_rooms": redis_ready,
    }
    return jsonify(response), 503 if app.config["REDIS_REQUIRED"] and not redis_ready else 200

@app.get("/api/meta")
def api_meta():
    return jsonify({
        **catalog_service.get_public_meta(),
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
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"

    try:
        count = int(request.args.get("count", "50"))
    except Exception:
        count = 50
    count = max(1, min(200, count))

    out = catalog_service.get_words(cat, difficulty, count)

    return jsonify({"category": cat, "difficulty": difficulty, "count": len(out), "words": out})

@app.post("/api/rooms/<room_id>/kick")
@synchronized_room_route
def api_kick(room_id):
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

    if player_id == room.get("host_id"):
        return jsonify({"error": "Cannot kick host"}), 400

    # Notify and remove the player from the room, but keep the socket connected
    # so they can immediately join again from the home screen.
    target_sid = get_player_sid(room, player_id)

    ok = remove_player_from_room(rid, player_id, reason="kicked")

    if target_sid:
        try:
            socketio.emit("kicked", {"room_id": rid, "message": "Removed by admin (REST)."}, to=target_sid)
            leave_room(rid, sid=target_sid)
        except Exception:
            pass
        SESSIONS.pop(target_sid, None)

    return jsonify({"ok": ok})


@app.post("/api/rooms/<room_id>/play_again")
@synchronized_room_route
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

    stop_timer(room)

    room["state"] = "lobby"
    room["phase"] = "lobby"

    # reset to lobby with everyone unassigned
    room["teams"] = []
    room["draft_teams"] = []
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}
    room["ranking"] = []
    room["last_turn_summary"] = None
    room["last_ended_turn_number"] = 0

    # reset used_words properly
    room["used_words"] = {cat: set() for cat in ALL_CATEGORIES}

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
        "servers": [{"url": "/"}],
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
                    "properties": {"player_id": {"type": "string"}},
                    "required": ["player_id"]
                }
            }
        },
        "paths": {
            "/api/health": {
                "get": {
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
                    "summary": "Get public room state",
                    "parameters": [
                        {"name": "room_id", "in": "path", "required": True, "schema": {"type": "string", "example": "1234"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "Room state",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RoomStateResponse"}}}
                        },
                        "400": {"description": "Invalid room_id", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Room not found", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                    }
                }
            },
            "/api/words/{category}": {
                "get": {
                    "summary": "Get words for a category/difficulty",
                    "parameters": [
                        {"name": "category", "in": "path", "required": True, "schema": {"type": "string", "example": "sport"}},
                        {"name": "difficulty", "in": "query", "required": False, "schema": {"type": "string", "enum": ["easy", "medium", "hard"], "default": "medium"}},
                        {"name": "count", "in": "query", "required": False, "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}},
                    ],
                    "responses": {
                        "200": {"description": "Words list", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/WordsResponse"}}}},
                        "400": {"description": "Invalid category", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                    }
                }
            },
            "/api/rooms/{room_id}/kick": {
                "post": {
                    "summary": "Kick a player (admin token required)",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {"name": "room_id", "in": "path", "required": True, "schema": {"type": "string", "example": "1234"}}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/KickRequest"}}}
                    },
                    "responses": {
                        "200": {"description": "OK"},
                        "401": {"description": "Unauthorized", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "400": {"description": "Bad request", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Room not found", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                    }
                }
            },
            "/api/rooms/{room_id}/play_again": {
                "post": {
                    "summary": "Reset game back to lobby (admin token required)",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {"name": "room_id", "in": "path", "required": True, "schema": {"type": "string", "example": "1234"}}
                    ],
                    "responses": {
                        "200": {"description": "OK"},
                        "401": {"description": "Unauthorized", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "400": {"description": "Bad request", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                        "404": {"description": "Room not found", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
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
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>Danzo API Docs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
    <style>
      body { margin:0; background:#0b0b0f; }
      .topbar { display:none; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: "/api/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true
      });
    </script>
  </body>
</html>
"""
    return html, 200, {"Content-Type": "text/html"}


# -----------------------------
# Socket events
# Notes:
# - Players are keyed by player_id (stable).
# - current_turn stores player_ids for describer/guesser.
# - We always send player_id from frontend in create/join events.
# - Refresh works: same player_id reconnects, no duplicate.
# -----------------------------
@socketio.on("connect")
def on_connect():
    emit("connected", {"sid": request.sid})


@socketio.on("disconnect")
def on_disconnect(reason=None):
    sid = request.sid
    session = SESSIONS.pop(sid, None)
    if not session:
        return

    room_id = normalize_room_id(session.get("room_id"))
    player_id = str(session.get("player_id") or "").strip()
    if not room_id or not player_id:
        return
    try:
        with ROOM_STORE.lock(room_id):
            room = ensure_room(room_id)
            if not room:
                return

            p = room.get("players", {}).get(player_id)
            if not p:
                return

            # A refreshed page can reconnect before the previous socket emits
            # its disconnect event. Ignore that stale disconnect so it cannot
            # overwrite the newer player session.
            if p.get("sid") != sid:
                return

            # mark disconnected (do not delete immediately)
            p["connected"] = False
            p["sid"] = None
            broadcast_room(room_id)
    except RoomStoreError:
        app.logger.exception("Disconnect synchronization failed for room %s.", room_id)
        return

    def cleanup_later():
        socketio.sleep(RECONNECT_GRACE_SECONDS)
        try:
            with ROOM_STORE.lock(room_id):
                r = ensure_room(room_id)
                if not r:
                    return
                pp = r.get("players", {}).get(player_id)
                if not pp:
                    return
                if pp.get("connected") is True:
                    return  # reconnected

                # During a game, keep the player's roster/team position so a
                # mobile refresh or a longer interruption can still rejoin.
                ct = r.get("current_turn") or {}
                if r.get("phase") in ["playing", "ranking", "results"]:
                    if r.get("phase") == "playing" and player_id in [
                        ct.get("describer_id"),
                        ct.get("guesser_id"),
                    ]:
                        end_team_turn(room_id, reason="player_left")
                    return

                # remove for real
                remove_player_from_room(room_id, player_id, reason="disconnect_timeout")
        except RoomStoreError:
            app.logger.exception("Disconnect cleanup failed for room %s.", room_id)

    socketio.start_background_task(cleanup_later)


@socketio.on("create_room")
def create_room(data):
    name = str((data or {}).get("name", "")).strip()[:20]
    player_id = str((data or {}).get("player_id", "")).strip()

    if not name:
        emit("error", {"message": "Nickname is required."})
        return

    if not player_id:
        player_id = new_player_id()

    if app.config["REDIS_REQUIRED"] and not ROOM_STORE.enabled:
        app.logger.error("REDIS_URL is required but is not configured.")
        emit("error", {"message": "The room service is not configured. Please retry later."})
        return

    # Generate and atomically reserve a 4-digit room code.
    chars = "0123456789"
    room_id = ""
    room = None
    for _ in range(100):
        room_id = "".join(random.choice(chars) for _ in range(4))
        candidate = {
            "room_id": room_id,
            "host_id": player_id,
            "state": "lobby",
            "phase": "lobby",
            "settings": dict(DEFAULT_SETTINGS),
            "target_score": TARGET_SCORE,
            "last_turn_summary": None,
            "players": {
                player_id: {
                    "id": player_id,
                    "sid": request.sid,
                    "name": name,
                    "connected": True,
                }
            },
            "teams": [],
            "draft_teams": [],
            "used_words": {cat: set() for cat in ALL_CATEGORIES},
            "timer_task": None,
            "turn_order": None,
            "turn_index": 0,
            "current_round": 1,
            "turn_number": 1,
            "current_turn": {},
            "ranking": [],
            "last_ended_turn_number": 0,
        }

        try:
            if ROOM_STORE.enabled:
                if not ROOM_STORE.create(candidate):
                    continue
            elif room_exists(room_id):
                continue
        except RoomStoreError:
            app.logger.exception("Unable to create a room in Redis.")
            emit("error", {"message": "Unable to create a room right now. Please retry."})
            return

        room = candidate
        ROOMS[room_id] = room
        break

    if room is None:
        emit("error", {"message": "Unable to generate an available room code."})
        return

    bind_session(room_id, player_id, request.sid)
    join_room(room_id)

    emit(
        "room_joined",
        {
            "room_id": room_id,
            "player_id": player_id,
            "room": room_public_state(room),
        },
    )
    broadcast_room(room_id)
    resume_room_timer(room_id, room)


@socketio.on("join_room")
@synchronized_room_event
def join_room_event(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    name = str((data or {}).get("name", "")).strip()[:20]
    player_id = str((data or {}).get("player_id", "")).strip()

    if not room_id:
        emit("error", {"message": "Room code is required."})
        return
    if not name:
        emit("error", {"message": "Nickname is required."})
        return
    if not player_id:
        player_id = new_player_id()

    room = ensure_room(room_id)
    if not room:
        emit("error", {"message": "Room not found."})
        return

    already = player_id in room.get("players", {})

    # new player can join only if lobby
    if not already and room.get("phase") not in ["lobby", "team_setup"]:
        emit("error", {"message": "Game already started. Create a new room."})
        return

    if not already:
        room["players"][player_id] = {
            "id": player_id,
            "sid": request.sid,
            "name": name,
            "connected": True
        }
    else:
        # reconnect: update sid, mark connected
        previous_sid = room["players"][player_id].get("sid")
        if previous_sid and previous_sid != request.sid:
            SESSIONS.pop(previous_sid, None)
            try:
                leave_room(room_id, sid=previous_sid)
            except Exception:
                pass
        room["players"][player_id]["sid"] = request.sid
        room["players"][player_id]["connected"] = True
        room["players"][player_id]["name"] = name  # optional

    bind_session(room_id, player_id, request.sid)
    join_room(room_id)

    emit(
        "room_joined",
        {
            "room_id": room_id,
            "player_id": player_id,
            "room": room_public_state(room),
        },
    )
    broadcast_room(room_id)
    resume_room_timer(room_id, room)


@socketio.on("leave_room")
@synchronized_room_event
def leave_room_event(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    SESSIONS.pop(request.sid, None)

    try:
        leave_room(room_id)
    except Exception:
        pass

    if room.get("phase") in ["playing", "ranking", "results"]:
        player = room.get("players", {}).get(player_id)
        if player:
            player["connected"] = False
            player["sid"] = None

        ct = room.get("current_turn") or {}
        if room.get("phase") == "playing" and player_id in [
            ct.get("describer_id"),
            ct.get("guesser_id"),
        ]:
            end_team_turn(room_id, reason="player_left")
        else:
            broadcast_room(room_id)
        return

    remove_player_from_room(room_id, player_id, reason="left")


@socketio.on("host_update_draft_teams")
@synchronized_room_event
def host_update_draft_teams(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    draft = (data or {}).get("draft_teams", [])

    room = ensure_room(room_id)
    if not room:
        return

    host_pid = get_session_player(room_id, request.sid)
    if not host_pid or not is_host(room, host_pid):
        return

    if not isinstance(draft, list):
        draft = []

    existing_ids = set(room["players"].keys())
    team_slots = (len(existing_ids) + 1) // 2

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
@synchronized_room_event
def host_set_teams(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    teams_data = (data or {}).get("teams", [])

    room = ensure_room(room_id)
    if not room:
        return

    host_pid = get_session_player(room_id, request.sid)
    if not host_pid or not is_host(room, host_pid):
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
            "score": 0.0,
            "turns_played": 0,
        })

    if used != all_players:
        emit("error", {"message": "All players must be assigned into teams of 2."})
        return

    room["teams"] = built
    room["draft_teams"] = [t["players"] for t in built]
    broadcast_room(room_id)
    emit("teams_saved", {"ok": True})


@socketio.on("host_start_game")
@synchronized_room_event
def host_start_game(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    host_pid = get_session_player(room_id, request.sid)
    if not host_pid or not is_host(room, host_pid):
        emit("error", {"message": "Only host can start the game."})
        return

    if len(room["players"]) < 2:
        emit("error", {"message": "Need at least 2 players."})
        return

    if not room.get("teams") or any(len(t["players"]) != 2 for t in room["teams"]):
        emit("error", {"message": "Host must create teams of 2 first."})
        return

    room["state"] = "playing"
    room["phase"] = "ranking"

    room["used_words"] = {cat: set() for cat in ALL_CATEGORIES}
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}

    room["ranking"] = compute_ranking(room)
    broadcast_room(room_id)
    socketio.emit("game_started", {"room": room_public_state(room)}, room=room_id)

    prepare_next_turn(room)
    broadcast_room(room_id)


@socketio.on("describer_start_turn")
@synchronized_room_event
def describer_start_turn(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    if room.get("phase") not in ["playing", "ranking"]:
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    ct = room.get("current_turn") or {}
    if player_id != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can start the turn."})
        return

    room["phase"] = "playing"
    room["state"] = "playing"
    ct["turn_started"] = True

    broadcast_room(room_id)
    socketio.emit("turn_started", {"turn": room_public_state(room)["current_turn"]}, room=room_id)


@socketio.on("choose_category")
@synchronized_room_event
def choose_category(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    category = str((data or {}).get("category", "")).strip().lower()

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    ct = room.get("current_turn") or {}
    if player_id != ct.get("describer_id"):
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
    ct["word_status"] = {}
    ct["word_claims"] = {}
    ct["found_words"] = []
    ct["guess_boxes"] = ["", "", "", "", ""]
    ct["guess_box_revisions"] = [0, 0, 0, 0, 0]
    ct["turn_points"] = 0.0
    ct["countdown_deadline_at"] = None
    ct["remaining_time"] = None

    socketio.emit("category_chosen", {"category": category}, room=room_id)
    broadcast_room(room_id)


@socketio.on("choose_difficulty")
@synchronized_room_event
def choose_difficulty(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    difficulty = str((data or {}).get("difficulty", "")).strip().lower()

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    ct = room.get("current_turn") or {}
    if player_id != ct.get("describer_id"):
        emit("error", {"message": "Only the describer can choose the difficulty."})
        return

    if not ct.get("turn_started"):
        emit("error", {"message": "Describer must press Start Turn first."})
        return

    if not ct.get("chosen_category"):
        emit("error", {"message": "Choose a category first."})
        return

    if difficulty not in ["easy", "medium", "hard"]:
        emit("error", {"message": "Invalid difficulty."})
        return

    ct["difficulty"] = difficulty

    words = pick_words(ct["chosen_category"], difficulty, room["used_words"], count=5)
    ct["words"] = words
    ct["word_status"] = {w: "unfound" for w in words}
    ct["word_claims"] = {}
    ct["found_words"] = []
    ct["guess_boxes"] = ["", "", "", "", ""]
    ct["guess_box_revisions"] = [0, 0, 0, 0, 0]
    ct["turn_points"] = 0.0
    ct["countdown_deadline_at"] = time.time() + 3
    ct["remaining_time"] = None

    socketio.emit("difficulty_chosen", {"difficulty": difficulty, "words": words}, room=room_id)
    broadcast_room(room_id)

    start_round_after_countdown(room_id, delay=3)


@socketio.on("guess_boxes_typing")
@synchronized_room_event
def guess_boxes_typing(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    index = (data or {}).get("index")
    text = str((data or {}).get("text", ""))[:60]
    revision = (data or {}).get("revision")

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    ct = room.get("current_turn") or {}
    if player_id != ct.get("guesser_id"):
        return
    if ct.get("remaining_time") is None:
        return
    if not isinstance(index, int) or index < 0 or index > 4:
        return

    ct.setdefault("guess_boxes", ["", "", "", "", ""])
    revisions = ct.get("guess_box_revisions")
    if not isinstance(revisions, list) or len(revisions) != 5:
        revisions = [0, 0, 0, 0, 0]
        ct["guess_box_revisions"] = revisions
    current_revision = revisions[index]
    if not isinstance(current_revision, int):
        current_revision = 0
    if not isinstance(revision, int):
        revision = current_revision + 1
    if revision < current_revision:
        return

    revisions[index] = revision
    ct["guess_boxes"][index] = text
    persist_room(room)
    socketio.emit(
        "guess_boxes_update",
        {"boxes": ct["guess_boxes"], "revisions": revisions},
        room=room_id,
    )


@socketio.on("submit_guess_box")
@synchronized_room_event
def submit_guess_box(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    index = (data or {}).get("index")
    raw_guess = str((data or {}).get("guess", ""))[:60]
    guess = raw_guess.strip()
    revision = (data or {}).get("revision")

    room = ensure_room(room_id)
    if not room or room.get("phase") != "playing":
        return

    player_id = get_session_player(room_id, request.sid)
    if not player_id:
        return

    ct = room.get("current_turn") or {}
    if player_id != ct.get("guesser_id"):
        return
    if ct.get("remaining_time") is None:
        return
    if not isinstance(index, int) or index < 0 or index > 4:
        return
    if not ct.get("words"):
        return

    ct.setdefault("word_status", {w: "unfound" for w in ct["words"]})
    ct.setdefault("word_claims", {})
    ct.setdefault("guess_boxes", ["", "", "", "", ""])
    revisions = ct.get("guess_box_revisions")
    if not isinstance(revisions, list) or len(revisions) != 5:
        revisions = [0, 0, 0, 0, 0]
        ct["guess_box_revisions"] = revisions
    current_revision = revisions[index]
    if not isinstance(current_revision, int):
        current_revision = 0
    if not isinstance(revision, int):
        revision = current_revision
    if revision < current_revision:
        return

    revisions[index] = revision
    ct["guess_boxes"][index] = raw_guess
    persist_room(room)

    if not guess:
        socketio.emit(
            "guess_box_result",
            {"index": index, "status": "", "revision": revision},
            room=room_id,
        )
        return

    norm_guess = normalize_text(guess)

    candidates = [w for w in ct["words"] if ct["word_status"].get(w) != "exact"]
    if not candidates:
        socketio.emit(
            "guess_box_result",
            {"index": index, "status": "wrong", "revision": revision},
            room=room_id,
        )
        return

    best_word = None
    best_dist = 999
    for w in candidates:
        dist = levenshtein(norm_guess, normalize_text(w))
        if dist < best_dist:
            best_dist = dist
            best_word = w

    status = "wrong"
    points_delta = 0.0

    if best_word is not None:
        prev_status = ct["word_status"].get(best_word, "unfound")
        claimed_by = ct["word_claims"].get(best_word)
        if claimed_by is not None and claimed_by != index:
            socketio.emit(
                "guess_box_result",
                {"index": index, "status": "wrong", "revision": revision},
                room=room_id,
            )
            return

        if best_dist == 0:
            status = "exact"
            if prev_status == "unfound":
                points_delta = 2.0
            elif prev_status == "close":
                points_delta = 1.0
            ct["word_status"][best_word] = "exact"
            ct["word_claims"][best_word] = index

        elif best_dist <= 2:
            status = "close"
            if prev_status == "unfound":
                points_delta = 1.0
                ct["word_status"][best_word] = "close"
                ct["word_claims"][best_word] = index

    mult = points_multiplier(str(ct.get("difficulty") or "medium"))
    points_delta = float(points_delta) * float(mult)

    socketio.emit(
        "guess_box_result",
        {"index": index, "status": status, "revision": revision},
        room=room_id,
    )

    if points_delta > 0:
        team_id = ct.get("team_id")
        team = next((t for t in room.get("teams", []) if t.get("team_id") == team_id), None)
        if team:
            team["score"] = float(team.get("score", 0)) + points_delta
        ct["turn_points"] = float(ct.get("turn_points", 0)) + points_delta
        socketio.emit("score_update", {"teams": room.get("teams", [])}, room=room_id)
        broadcast_room(room_id)

    exact_count = sum(1 for w in ct["words"] if ct["word_status"].get(w) == "exact")
    if exact_count >= 5:
        end_team_turn(room_id, reason="all_found")


@socketio.on("host_kick_player")
@synchronized_room_event
def host_kick_player(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    target_player_id = str((data or {}).get("player_id", "")).strip()

    room = ensure_room(room_id)
    if not room:
        return

    actor_player_id = get_session_player(room_id, request.sid)
    if not actor_player_id or not is_host(room, actor_player_id):
        emit("error", {"message": "Only host can kick players."})
        return

    if target_player_id == room.get("host_id"):
        return

    if target_player_id not in room.get("players", {}):
        return

    target_sid = get_player_sid(room, target_player_id)

    if target_sid:
        socketio.emit(
            "kicked",
            {"room_id": room_id, "message": "You were kicked by the host."},
            to=target_sid
        )

        try:
            leave_room(room_id, sid=target_sid)
        except Exception:
            pass

        SESSIONS.pop(target_sid, None)

    remove_player_from_room(room_id, target_player_id, reason="kicked")

    if ensure_room(room_id):
        broadcast_room(room_id)



@socketio.on("host_play_again")
@synchronized_room_event
def host_play_again(data):
    room_id = str((data or {}).get("room_id", "")).strip().upper()
    room = ensure_room(room_id)
    if not room:
        return

    host_pid = get_session_player(room_id, request.sid)
    if not host_pid or not is_host(room, host_pid):
        emit("error", {"message": "Only host can restart the game."})
        return

    stop_timer(room)

    room["state"] = "lobby"
    room["phase"] = "lobby"

    # reset to lobby with everyone unassigned
    room["teams"] = []
    room["draft_teams"] = []
    room["turn_order"] = None
    room["turn_index"] = 0
    room["current_round"] = 1
    room["turn_number"] = 1
    room["current_turn"] = {}
    room["ranking"] = []
    room["last_turn_summary"] = None
    room["last_ended_turn_number"] = 0
    room["used_words"] = {cat: set() for cat in ALL_CATEGORIES}

    broadcast_room(room_id)
    socketio.emit("back_to_lobby", {"room": room_public_state(room)}, room=room_id)
