import json
from contextlib import contextmanager
from typing import Any, Iterator

from redis import Redis
from redis.exceptions import LockError, RedisError


class RoomStoreError(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if isinstance(value, set):
        return {"__danzo_set__": sorted(value)}
    raise TypeError(f"Unsupported room value: {type(value).__name__}")


def _json_object_hook(value: dict[str, Any]) -> Any:
    if set(value) == {"__danzo_set__"}:
        return set(value["__danzo_set__"])
    return value


class RoomStore:
    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 43_200,
        key_prefix: str = "danzo:local",
    ):
        self.ttl_seconds = max(int(ttl_seconds), 300)
        self.key_prefix = key_prefix.strip(":") or "danzo:local"
        self.configuration_error: str | None = None
        try:
            self.client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            ) if redis_url else None
        except (TypeError, ValueError) as exc:
            self.client = None
            self.configuration_error = str(exc)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _room_key(self, room_id: str) -> str:
        return f"{self.key_prefix}:room:{room_id}"

    def _lock_key(self, room_id: str) -> str:
        return f"{self.key_prefix}:lock:{room_id}"

    @staticmethod
    def _serialize(room: dict[str, Any]) -> str:
        return json.dumps(
            room,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize(payload: str) -> dict[str, Any]:
        value = json.loads(payload, object_hook=_json_object_hook)
        if not isinstance(value, dict):
            raise RoomStoreError("Stored room payload is not an object.")
        return value

    def get(self, room_id: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        try:
            payload = self.client.get(self._room_key(room_id))
            return self._deserialize(payload) if payload else None
        except (RedisError, TypeError, ValueError) as exc:
            raise RoomStoreError(f"Unable to read room {room_id} from Redis.") from exc

    def save(self, room: dict[str, Any]) -> None:
        if not self.client:
            return
        room_id = str(room.get("room_id") or "").strip().upper()
        if not room_id:
            raise RoomStoreError("Cannot save a room without a room_id.")
        try:
            self.client.setex(
                self._room_key(room_id),
                self.ttl_seconds,
                self._serialize(room),
            )
        except (RedisError, TypeError, ValueError) as exc:
            raise RoomStoreError(f"Unable to save room {room_id} to Redis.") from exc

    def create(self, room: dict[str, Any]) -> bool:
        if not self.client:
            return True
        room_id = str(room.get("room_id") or "").strip().upper()
        if not room_id:
            raise RoomStoreError("Cannot create a room without a room_id.")
        try:
            return bool(
                self.client.set(
                    self._room_key(room_id),
                    self._serialize(room),
                    ex=self.ttl_seconds,
                    nx=True,
                )
            )
        except (RedisError, TypeError, ValueError) as exc:
            raise RoomStoreError(f"Unable to create room {room_id} in Redis.") from exc

    def exists(self, room_id: str) -> bool:
        if not self.client:
            return False
        try:
            return bool(self.client.exists(self._room_key(room_id)))
        except RedisError as exc:
            raise RoomStoreError(f"Unable to check room {room_id} in Redis.") from exc

    def ping(self) -> bool:
        if not self.client:
            return False
        try:
            return bool(self.client.ping())
        except RedisError as exc:
            raise RoomStoreError("Unable to connect to Redis.") from exc

    def delete(self, room_id: str) -> None:
        if not self.client:
            return
        try:
            self.client.delete(self._room_key(room_id))
        except RedisError as exc:
            raise RoomStoreError(f"Unable to delete room {room_id} from Redis.") from exc

    @contextmanager
    def lock(self, room_id: str) -> Iterator[bool]:
        if not self.client or not room_id:
            yield False
            return

        lock = self.client.lock(
            self._lock_key(room_id),
            timeout=15,
            blocking_timeout=5,
        )
        acquired = False
        try:
            acquired = bool(lock.acquire())
            if not acquired:
                raise RoomStoreError(f"Timed out waiting for room {room_id} lock.")
            yield True
        except RedisError as exc:
            raise RoomStoreError(f"Unable to lock room {room_id} in Redis.") from exc
        finally:
            if acquired:
                try:
                    lock.release()
                except (LockError, RedisError):
                    pass
