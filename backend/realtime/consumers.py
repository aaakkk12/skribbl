import asyncio
import json
import math
import random
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Set, Tuple

import redis.asyncio as redis
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model

from .models import Room, RoomMember
from .lobby import rooms_snapshot
from .lifecycle import cleanup_inactive_rooms, sync_room_empty_state

MAX_PLAYERS = 8
CHAT_HISTORY_LIMIT = 500
DRAW_HISTORY_LIMIT = 2000
CHAT_WINDOW_SECONDS = 4
CHAT_MAX_BURST = 3
DISCONNECT_GRACE_SECONDS = 60
ROUND_BREAK_SECONDS = 5
KICK_VOTE_SECONDS = 20
MAX_CHAT_COOLDOWN = 12
ROOM_HISTORY_TTL_SECONDS = int(getattr(settings, "ROOM_HISTORY_TTL_SECONDS", 60 * 60 * 24 * 7))
ROOM_STATE_TTL_SECONDS = int(getattr(settings, "ROOM_STATE_TTL_SECONDS", 60 * 60 * 24))
REDIS_LOCK_TIMEOUT_SECONDS = 10
REDIS_LOCK_WAIT_SECONDS = 5
TIMER_OWNER_GRACE_SECONDS = 15

WORDS = [
    "tree",
    "house",
    "river",
    "mountain",
    "phone",
    "pencil",
    "laptop",
    "camera",
    "bridge",
    "bicycle",
    "guitar",
    "pizza",
    "football",
    "rocket",
    "car",
    "elephant",
    "flower",
    "sun",
    "moon",
    "cloud",
    "boat",
    "castle",
    "train",
    "airplane",
    "robot",
    "glasses",
    "clock",
    "coffee",
    "chair",
    "table",
    "book",
    "banana",
    "apple",
    "shoes",
    "umbrella",
    "window",
    "key",
    "pizza slice",
    "snowman",
    "ice cream",
    "tree house",
    "volcano",
    "light bulb",
    "backpack",
    "telescope",
    "horse",
    "lion",
    "tiger",
    "owl",
    "cat",
    "dog",
    "spider",
    "bridge",
    "road",
    "candle",
    "campfire",
    "cup",
    "hat",
    "ring",
    "watch",
    "map",
    "star",
    "planet",
    "sandcastle",
    "waterfall",
    "kite",
    "panda",
    "snowflake",
    "flower pot",
    "drum",
    "microphone",
    "headphones",
    "sunglasses",
    "rainbow",
    "tree trunk",
    "chocolate",
    "burger",
    "diamond",
    "tower",
    "pyramid",
    "paintbrush",
    "palmtree",
    "fish",
    "whale",
    "shark",
    "submarine",
    "hot air balloon",
    "camera lens",
    "mountain peak",
]


@dataclass
class GameState:
    code: str
    status: str = "waiting"
    round_index: int = 0
    max_rounds: int = 10
    round_seconds: int = 120
    drawer_id: Optional[int] = None
    word: Optional[str] = None
    scores: Dict[int, int] = field(default_factory=dict)
    guessed: Set[int] = field(default_factory=set)
    revealed_indices: Set[int] = field(default_factory=set)
    started_at: float = 0.0
    task: Optional[asyncio.Task] = None
    last_drawer_id: Optional[int] = None
    connections: Dict[int, Set[str]] = field(default_factory=dict)
    chat_history: Dict[int, Deque[float]] = field(default_factory=dict)
    chat_penalties: Dict[int, int] = field(default_factory=dict)
    chat_cooldowns: Dict[int, float] = field(default_factory=dict)
    disconnect_tasks: Dict[int, asyncio.Task] = field(default_factory=dict)
    kick_votes: Dict[int, Set[int]] = field(default_factory=dict)
    kick_responses: Dict[int, Set[int]] = field(default_factory=dict)
    kick_timeout_tasks: Dict[int, asyncio.Task] = field(default_factory=dict)


ROOM_STATES: Dict[str, GameState] = {}
ROOM_LOCKS: Dict[str, asyncio.Lock] = {}
_REDIS_CLIENT: Optional[redis.Redis] = None


def get_state(code: str) -> GameState:
    state = ROOM_STATES.get(code)
    if not state:
        state = GameState(code=code)
        ROOM_STATES[code] = state
    return state


def get_lock(code: str) -> asyncio.Lock:
    lock = ROOM_LOCKS.get(code)
    if not lock:
        lock = asyncio.Lock()
        ROOM_LOCKS[code] = lock
    return lock


async def get_redis_client() -> Optional[redis.Redis]:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        try:
            _REDIS_CLIENT = redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:
            _REDIS_CLIENT = None
    return _REDIS_CLIENT


def chat_key(code: str) -> str:
    return f"room:{code}:chat"


def draw_key(code: str) -> str:
    return f"room:{code}:draw"


def game_state_key(code: str) -> str:
    return f"room:{code}:game_state"


def room_lock_key(code: str) -> str:
    return f"room:{code}:lock"


def timer_owner_key(code: str) -> str:
    return f"room:{code}:timer_owner"


def connection_count_key(code: str, user_id: int) -> str:
    return f"room:{code}:connections:{user_id}"


def mask_word(word: str, revealed: Set[int]) -> str:
    letters = []
    for idx, char in enumerate(word):
        if char == " ":
            letters.append(" ")
        elif idx in revealed:
            letters.append(char.upper())
        else:
            letters.append("_")
    return " ".join(letters)


def serialize_scores(scores: Dict[int, int]) -> Dict[str, int]:
    return {str(key): value for key, value in scores.items()}


def state_payload(state: GameState) -> Dict:
    return {
        "status": state.status,
        "round_index": state.round_index,
        "max_rounds": state.max_rounds,
        "round_seconds": state.round_seconds,
        "drawer_id": state.drawer_id,
        "word": state.word,
        "scores": serialize_scores(state.scores),
        "guessed": [int(user_id) for user_id in sorted(state.guessed)],
        "revealed_indices": [int(idx) for idx in sorted(state.revealed_indices)],
        "started_at": state.started_at,
        "last_drawer_id": state.last_drawer_id,
        "kick_votes": {
            str(target_id): [int(voter_id) for voter_id in sorted(voters)]
            for target_id, voters in state.kick_votes.items()
        },
        "kick_responses": {
            str(target_id): [int(voter_id) for voter_id in sorted(voters)]
            for target_id, voters in state.kick_responses.items()
        },
    }


def apply_state_payload(state: GameState, payload: Dict) -> GameState:
    state.status = payload.get("status", "waiting")
    state.round_index = int(payload.get("round_index", 0))
    state.max_rounds = int(payload.get("max_rounds", 10))
    state.round_seconds = int(payload.get("round_seconds", 120))
    state.drawer_id = payload.get("drawer_id")
    state.word = payload.get("word")
    raw_scores = payload.get("scores") or {}
    state.scores = {int(key): int(value) for key, value in raw_scores.items()}
    state.guessed = {int(value) for value in (payload.get("guessed") or [])}
    state.revealed_indices = {int(value) for value in (payload.get("revealed_indices") or [])}
    state.started_at = float(payload.get("started_at", 0.0))
    state.last_drawer_id = payload.get("last_drawer_id")
    raw_kick_votes = payload.get("kick_votes") or {}
    state.kick_votes = {
        int(target_id): {int(voter_id) for voter_id in voters}
        for target_id, voters in raw_kick_votes.items()
    }
    raw_kick_responses = payload.get("kick_responses") or {}
    state.kick_responses = {
        int(target_id): {int(voter_id) for voter_id in voters}
        for target_id, voters in raw_kick_responses.items()
    }
    return state


class RoomConsumer(AsyncJsonWebsocketConsumer):
    @asynccontextmanager
    async def state_lock(self):
        local_lock = get_lock(self.code)
        redis_lock = None
        async with local_lock:
            client = await get_redis_client()
            if client:
                redis_lock = client.lock(
                    room_lock_key(self.code),
                    timeout=REDIS_LOCK_TIMEOUT_SECONDS,
                    blocking_timeout=REDIS_LOCK_WAIT_SECONDS,
                )
                acquired = await redis_lock.acquire(blocking=True)
                if not acquired:
                    raise RuntimeError("Could not acquire distributed room lock")
            try:
                yield
            finally:
                if redis_lock:
                    try:
                        await redis_lock.release()
                    except Exception:
                        pass

    async def load_state_from_redis(self, state: GameState):
        client = await get_redis_client()
        if not client:
            return state
        try:
            raw = await client.get(game_state_key(self.code))
            if not raw:
                return state
            payload = json.loads(raw)
            return apply_state_payload(state, payload)
        except Exception:
            return state

    async def save_state_to_redis(self, state: GameState):
        client = await get_redis_client()
        if not client:
            return
        try:
            await client.set(
                game_state_key(self.code),
                json.dumps(state_payload(state)),
                ex=ROOM_STATE_TTL_SECONDS,
            )
        except Exception:
            return

    async def increment_connection_count(self, user_id: int):
        client = await get_redis_client()
        if not client:
            return
        try:
            key = connection_count_key(self.code, user_id)
            await client.incr(key)
            await client.expire(key, DISCONNECT_GRACE_SECONDS * 4)
        except Exception:
            return

    async def decrement_connection_count(self, user_id: int):
        client = await get_redis_client()
        if not client:
            return
        try:
            key = connection_count_key(self.code, user_id)
            count = await client.decr(key)
            if count <= 0:
                await client.delete(key)
        except Exception:
            return

    async def reset_connection_count(self, user_id: int):
        client = await get_redis_client()
        if not client:
            return
        try:
            await client.delete(connection_count_key(self.code, user_id))
        except Exception:
            return

    async def get_connection_count(self, user_id: int) -> int:
        client = await get_redis_client()
        if not client:
            state = get_state(self.code)
            return len(state.connections.get(user_id, set()))
        try:
            raw = await client.get(connection_count_key(self.code, user_id))
            return int(raw or 0)
        except Exception:
            return 0

    async def claim_timer_owner(self, round_index: int, started_at: float) -> bool:
        client = await get_redis_client()
        if not client:
            return True
        payload = json.dumps(
            {
                "channel": self.channel_name,
                "round_index": round_index,
                "started_at": started_at,
            }
        )
        try:
            claimed = bool(
                await client.set(
                    timer_owner_key(self.code),
                    payload,
                    nx=True,
                    ex=max(10, TIMER_OWNER_GRACE_SECONDS + 2),
                )
            )
            if claimed:
                return True
            current = await client.get(timer_owner_key(self.code))
            if not current:
                return False
            try:
                current_payload = json.loads(current)
            except Exception:
                current_payload = {}
            current_round = int(current_payload.get("round_index", -1))
            current_started_at = float(current_payload.get("started_at", 0.0))
            if current_round != int(round_index) or abs(current_started_at - float(started_at)) > 0.01:
                await client.set(
                    timer_owner_key(self.code),
                    payload,
                    ex=max(10, TIMER_OWNER_GRACE_SECONDS + 2),
                )
                return True
            return current_payload.get("channel") == self.channel_name
        except Exception:
            return True

    async def renew_timer_owner(self, seconds: int):
        client = await get_redis_client()
        if not client:
            return
        try:
            if not await self.is_timer_owner():
                return
            ttl = max(10, seconds + TIMER_OWNER_GRACE_SECONDS)
            await client.expire(timer_owner_key(self.code), ttl)
        except Exception:
            return

    async def release_timer_owner(self):
        client = await get_redis_client()
        if not client:
            return
        try:
            owner = await client.get(timer_owner_key(self.code))
            if owner:
                try:
                    owner_payload = json.loads(owner)
                    owner_channel = owner_payload.get("channel")
                except Exception:
                    owner_channel = owner
            else:
                owner_channel = None
            if owner_channel == self.channel_name:
                await client.delete(timer_owner_key(self.code))
        except Exception:
            return

    async def is_timer_owner(self) -> bool:
        client = await get_redis_client()
        if not client:
            return True
        try:
            owner = await client.get(timer_owner_key(self.code))
            if not owner:
                return False
            try:
                owner_payload = json.loads(owner)
                owner_channel = owner_payload.get("channel")
            except Exception:
                owner_channel = owner
            return owner_channel == self.channel_name
        except Exception:
            return True

    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"].upper()
        self.room_group_name = f"room_{self.code}"
        user = self.scope.get("user")

        if not user or isinstance(user, AnonymousUser) or user.is_anonymous:
            await self.close(code=4401)
            return

        await self.cleanup_inactive_rooms_db()
        room = await self.get_room(self.code)
        if not room:
            await self.close(code=4404)
            return

        if not await self.is_user_allowed(user.id):
            await self.close(code=4403)
            return

        # Membership must be established by REST join flow to enforce room rules.
        if not await self.is_member_active(room, user.id):
            await self.close(code=4403)
            return

        self.room = room
        self.user = user
        self.user_info = await self.get_public_user(user.id)

        state = get_state(self.code)
        async with self.state_lock():
            await self.load_state_from_redis(state)
            state.connections.setdefault(user.id, set()).add(self.channel_name)
            state.scores.setdefault(user.id, 0)
            task = state.disconnect_tasks.pop(user.id, None)
            if task:
                task.cancel()
            await self.save_state_to_redis(state)
            await self.increment_connection_count(user.id)

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        await self.broadcast_presence()
        await self.send_game_state(state)
        await self.send_history()

        await self.maybe_start_game(state)

    async def disconnect(self, close_code):
        if not hasattr(self, "user") or not hasattr(self, "room") or not hasattr(self, "code"):
            await self.channel_layer.group_discard(getattr(self, "room_group_name", ""), self.channel_name)
            return
        state = get_state(self.code)
        async with self.state_lock():
            await self.load_state_from_redis(state)
            channels = state.connections.get(self.user.id, set())
            channels.discard(self.channel_name)
            if not channels:
                state.connections.pop(self.user.id, None)
                if self.user.id not in state.disconnect_tasks:
                    is_active = await self.is_member_active(self.room, self.user.id)
                    if is_active:
                        state.disconnect_tasks[self.user.id] = asyncio.create_task(
                            self.mark_inactive_later(self.user.id)
                        )
            await self.save_state_to_redis(state)
            await self.decrement_connection_count(self.user.id)
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def mark_inactive_later(self, user_id: int):
        await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
        state = get_state(self.code)
        async with self.state_lock():
            await self.load_state_from_redis(state)
            if await self.get_connection_count(user_id) > 0:
                return
            state.connections.pop(user_id, None)
            await self.save_state_to_redis(state)
        await self.set_member_inactive(self.room, user_id)
        await self.sync_room_empty_state_db()
        await self.cleanup_inactive_rooms_db()
        await self.cleanup_kick_votes(state, user_id)
        await self.broadcast_presence()
        await self.maybe_pause_game(state)

    async def receive_json(self, content, **kwargs):
        if not await self.is_member_active(self.room, self.user.id):
            await self.close(code=4003)
            return
        message_type = content.get("type")
        state = get_state(self.code)
        await self.load_state_from_redis(state)

        if message_type == "draw":
            if state.status != "running" or state.drawer_id != self.user.id:
                return
            payload = content.get("payload")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "draw",
                    "payload": payload,
                    "user": self.user_info,
                },
            )
            await self.store_draw(payload)
        elif message_type == "chat":
            message = (content.get("message") or "").strip()
            client_id = content.get("client_id")
            if not message:
                return
            await self.handle_chat_guess(state, message, client_id)
        elif message_type == "clear":
            if state.status == "running" and state.drawer_id == self.user.id:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "clear",
                        "user": self.user_info,
                    },
                )
                await self.clear_draw_history()
        elif message_type == "start_game":
            await self.start_game(state)
        elif message_type == "kick_request":
            target_id = content.get("target_id")
            try:
                target_id = int(target_id)
            except (TypeError, ValueError):
                return
            await self.handle_kick_request(state, target_id)
        elif message_type == "kick_vote":
            target_id = content.get("target_id")
            approve = content.get("approve", True)
            try:
                target_id = int(target_id)
            except (TypeError, ValueError):
                return
            await self.handle_kick_vote(state, target_id, bool(approve))
        elif message_type == "leave":
            await self.handle_leave(state)
        elif message_type == "ping":
            await self.send_json({"type": "pong"})

    async def handle_chat_guess(self, state: GameState, message: str, client_id: Optional[str] = None):
        if state.status == "running" and state.drawer_id == self.user.id:
            await self.send_json(
                {
                    "type": "chat_blocked",
                    "reason": "Chat disabled while drawing.",
                    "client_id": client_id,
                }
            )
            return

        allowed, cooldown = self.check_chat_allowed(state, self.user.id)
        if not allowed:
            await self.send_json(
                {"type": "chat_cooldown", "seconds": cooldown, "client_id": client_id}
            )
            return

        normalized = message.lower()
        is_candidate = (
            state.status == "running"
            and state.word
            and self.user.id != state.drawer_id
            and self.user.id not in state.guessed
            and normalized == state.word.lower()
        )

        if is_candidate:
            end_due_to_all_guessed = False
            async with self.state_lock():
                await self.load_state_from_redis(state)
                is_still_candidate = (
                    state.status == "running"
                    and state.word
                    and self.user.id != state.drawer_id
                    and self.user.id not in state.guessed
                    and normalized == state.word.lower()
                )
                if not is_still_candidate:
                    return

                points = max(20, 100 - 10 * len(state.guessed))
                state.guessed.add(self.user.id)
                state.scores[self.user.id] = state.scores.get(self.user.id, 0) + points
                if state.drawer_id:
                    state.scores[state.drawer_id] = state.scores.get(state.drawer_id, 0) + 10
                await self.save_state_to_redis(state)
                active_ids = await self.get_active_member_ids(self.code)
                end_due_to_all_guessed = len(state.guessed) >= max(0, len(active_ids) - 1)

            system_message = f"[Correct] {self.user_info['name']} guessed correctly (+{points})"
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "guess_correct",
                    "user": self.user_info,
                    "points": points,
                    "scores": serialize_scores(state.scores),
                },
            )
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat",
                    "message": system_message,
                    "system": True,
                },
            )
            await self.store_chat_message(
                {
                    "id": f"{time.time()}-{random.random()}",
                    "message": system_message,
                    "system": True,
                }
            )
            if end_due_to_all_guessed:
                await self.end_round(state, reason="all_guessed")
            return

        payload = {
            "type": "chat",
            "message": message,
            "user": self.user_info,
            "system": False,
            "client_id": client_id,
        }
        await self.channel_layer.group_send(self.room_group_name, payload)
        await self.store_chat_message(
            {
                "id": f"{time.time()}-{random.random()}",
                "message": message,
                "user": self.user_info,
                "system": False,
                "client_id": client_id,
            }
        )

    async def handle_kick_request(self, state: GameState, target_id: int):
        if target_id == self.user.id:
            return
        async with self.state_lock():
            await self.load_state_from_redis(state)
            if state.kick_votes:
                await self.send_json({"type": "error", "message": "Kick vote already in progress."})
                return
            active_ids = await self.get_active_member_ids(self.code)
            if target_id not in active_ids:
                return
            voters = state.kick_votes.setdefault(target_id, set())
            voters.add(self.user.id)
            responses = state.kick_responses.setdefault(target_id, set())
            responses.add(self.user.id)
            required = self.required_votes(active_ids, target_id)
            await self.save_state_to_redis(state)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "kick_request",
                "target_id": target_id,
                "requester_id": self.user.id,
                "votes": len(voters),
                "required": required,
            },
        )

        await self.store_chat_message(
            {
                "id": f"{time.time()}-{random.random()}",
                "message": f"Kick vote started for player {target_id}.",
                "system": True,
            }
        )

        if len(voters) >= required:
            await self.kick_user(state, target_id, "Voted out")
            return

        if target_id not in state.kick_timeout_tasks:
            state.kick_timeout_tasks[target_id] = asyncio.create_task(
                self.kick_timeout(state, target_id)
            )

    async def handle_kick_vote(self, state: GameState, target_id: int, approve: bool):
        if target_id == self.user.id:
            return
        async with self.state_lock():
            await self.load_state_from_redis(state)
            if target_id not in state.kick_votes:
                return
            active_ids = await self.get_active_member_ids(self.code)
            eligible = [user_id for user_id in active_ids if user_id != target_id]
            if self.user.id not in eligible:
                return

            voters = state.kick_votes.setdefault(target_id, set())
            responses = state.kick_responses.setdefault(target_id, set())
            if self.user.id in responses:
                return
            responses.add(self.user.id)

            if approve:
                voters.add(self.user.id)

            voters.intersection_update(eligible)
            responses.intersection_update(eligible)
            required = self.required_votes(active_ids, target_id)
            await self.save_state_to_redis(state)

        if len(voters) >= required:
            await self.kick_user(state, target_id, "Voted out")
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "kick_update",
                "target_id": target_id,
                "votes": len(voters),
                "required": required,
                "responded": len(responses),
                "eligible": len(eligible),
            },
        )

    async def handle_leave(self, state: GameState):
        user_id = self.user.id
        task = state.disconnect_tasks.pop(user_id, None)
        if task:
            task.cancel()
        async with self.state_lock():
            await self.load_state_from_redis(state)
            state.connections.pop(user_id, None)
            await self.save_state_to_redis(state)
            await self.reset_connection_count(user_id)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "direct_disconnect_user",
                "target_id": user_id,
                "close_code": 4003,
            },
        )
        await self.set_member_inactive(self.room, user_id)
        await self.sync_room_empty_state_db()
        await self.cleanup_inactive_rooms_db()
        await self.broadcast_presence()
        await self.maybe_pause_game(state)

    async def maybe_pause_game(self, state: GameState):
        active_ids = await self.get_active_member_ids(self.code)
        if len(active_ids) >= 2:
            return
        if state.status == "running":
            async with self.state_lock():
                await self.load_state_from_redis(state)
                state.status = "waiting"
                if state.task and not state.task.done():
                    state.task.cancel()
                state.word = None
                state.drawer_id = None
                await self.save_state_to_redis(state)
                await self.release_timer_owner()
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "round_paused",
                    "message": "Need at least 2 players to continue.",
                },
            )

    async def kick_timeout(self, state: GameState, target_id: int):
        await asyncio.sleep(KICK_VOTE_SECONDS)
        await self.load_state_from_redis(state)
        if target_id in state.kick_votes:
            await self.cancel_kick_vote(state, target_id, "Vote expired")

    async def cancel_kick_vote(self, state: GameState, target_id: int, reason: str):
        task = state.kick_timeout_tasks.pop(target_id, None)
        if task:
            task.cancel()
        async with self.state_lock():
            await self.load_state_from_redis(state)
            state.kick_votes.pop(target_id, None)
            state.kick_responses.pop(target_id, None)
            await self.save_state_to_redis(state)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "kick_cancel",
                "target_id": target_id,
                "reason": reason,
            },
        )

    async def cleanup_kick_votes(self, state: GameState, user_id: int):
        cancel_target_id: Optional[int] = None
        async with self.state_lock():
            await self.load_state_from_redis(state)
            if user_id in state.kick_votes:
                cancel_target_id = user_id
            if not state.kick_votes:
                return
            if cancel_target_id is None:
                target_id = next(iter(state.kick_votes.keys()))
                active_ids = await self.get_active_member_ids(self.code)
                eligible = [uid for uid in active_ids if uid != target_id]
                voters = state.kick_votes.get(target_id, set())
                responses = state.kick_responses.get(target_id, set())
                voters.discard(user_id)
                responses.discard(user_id)
                voters.intersection_update(eligible)
                responses.intersection_update(eligible)
                required = self.required_votes(active_ids, target_id)
            await self.save_state_to_redis(state)

        if cancel_target_id is not None:
            await self.cancel_kick_vote(state, cancel_target_id, "Player left")
            return

        if len(voters) >= required:
            await self.kick_user(state, target_id, "Voted out")
            return
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "kick_update",
                "target_id": target_id,
                "votes": len(voters),
                "required": required,
                "responded": len(responses),
                "eligible": len(eligible),
            },
        )

    async def kick_user(self, state: GameState, target_id: int, reason: str):
        await self.cancel_kick_vote(state, target_id, reason)
        await self.store_chat_message(
            {
                "id": f"{time.time()}-{random.random()}",
                "message": f"Player {target_id} was removed ({reason}).",
                "system": True,
            }
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "system",
                "message": f"Player {target_id} was removed ({reason}).",
            },
        )
        await self.send_to_user(target_id, {"type": "kicked", "reason": reason})
        async with self.state_lock():
            await self.load_state_from_redis(state)
            state.connections.pop(target_id, None)
            await self.save_state_to_redis(state)
            await self.reset_connection_count(target_id)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "direct_disconnect_user",
                "target_id": target_id,
                "close_code": 4003,
            },
        )
        await self.set_member_inactive(self.room, target_id)
        await self.sync_room_empty_state_db()
        await self.cleanup_inactive_rooms_db()
        await self.broadcast_presence()

    async def send_game_state(self, state: GameState):
        await self.load_state_from_redis(state)
        if state.status == "running" and state.word:
            masked = mask_word(state.word, state.revealed_indices)
            seconds_left = max(0, int(state.round_seconds - (time.time() - state.started_at)))
            await self.send_json(
                {
                    "type": "game_state",
                    "status": state.status,
                    "round": state.round_index,
                    "max_rounds": state.max_rounds,
                    "drawer_id": state.drawer_id,
                    "masked_word": masked,
                    "seconds_left": seconds_left,
                    "scores": serialize_scores(state.scores),
                }
            )
            if self.user.id == state.drawer_id:
                await self.send_json({"type": "round_secret", "word": state.word})
        else:
            await self.send_json(
                {
                    "type": "game_state",
                    "status": state.status,
                    "round": state.round_index,
                    "max_rounds": state.max_rounds,
                    "scores": serialize_scores(state.scores),
                }
            )

    async def send_history(self):
        chat = await self.get_chat_history()
        draw = await self.get_draw_history()
        if chat or draw:
            await self.send_json({"type": "history", "chat": chat, "draw": draw})

    async def maybe_start_game(self, state: GameState):
        await self.load_state_from_redis(state)
        if state.status != "waiting" or state.round_index > 0:
            return
        active_ids = await self.get_active_member_ids(self.code)
        if len(active_ids) >= 2:
            await self.start_round(state)

    async def start_game(self, state: GameState):
        await self.load_state_from_redis(state)
        if state.status == "running":
            return
        await self.start_round(state)

    async def start_round(self, state: GameState):
        needs_players = False
        finish_now = False
        timer_owner = False
        round_payload = None

        async with self.state_lock():
            await self.load_state_from_redis(state)
            if state.status == "running":
                return

            active_ids = await self.get_active_member_ids(self.code)
            if len(active_ids) < 2:
                needs_players = True
            else:
                next_round = state.round_index + 1
                if next_round > state.max_rounds:
                    finish_now = True
                else:
                    state.status = "running"
                    state.round_index = next_round
                    state.word = random.choice(WORDS)
                    state.guessed = set()
                    state.revealed_indices = set()
                    state.started_at = time.time()

                    drawer_id = self.choose_drawer(active_ids, state.last_drawer_id)
                    state.drawer_id = drawer_id
                    state.last_drawer_id = drawer_id
                    masked = mask_word(state.word, state.revealed_indices)
                    await self.clear_draw_history()
                    await self.save_state_to_redis(state)
                    timer_owner = await self.claim_timer_owner(
                        round_index=state.round_index,
                        started_at=state.started_at,
                    )

                    round_payload = {
                        "round": state.round_index,
                        "max_rounds": state.max_rounds,
                        "drawer_id": state.drawer_id,
                        "masked_word": masked,
                        "duration": state.round_seconds,
                        "scores": serialize_scores(state.scores),
                        "word": state.word,
                    }

        if needs_players:
            await self.send_json(
                {"type": "error", "message": "Need at least 2 players to start."}
            )
            return

        if finish_now:
            await self.finish_game(state)
            return

        if not round_payload:
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "clear",
                "user": {"id": round_payload["drawer_id"]},
            },
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "round_start",
                "round": round_payload["round"],
                "max_rounds": round_payload["max_rounds"],
                "drawer_id": round_payload["drawer_id"],
                "masked_word": round_payload["masked_word"],
                "duration": round_payload["duration"],
                "scores": round_payload["scores"],
            },
        )

        await self.send_to_user(
            round_payload["drawer_id"],
            {"type": "round_secret", "word": round_payload["word"]},
        )

        if state.task and not state.task.done():
            state.task.cancel()
        if timer_owner:
            state.task = asyncio.create_task(self.round_timer(state))

    async def round_timer(self, state: GameState):
        if not await self.is_timer_owner():
            return

        hint_marks = {90, 60, 30}
        while True:
            await self.load_state_from_redis(state)
            if state.status != "running" or not await self.is_timer_owner():
                return

            seconds_left = max(0, int(state.round_seconds - (time.time() - state.started_at)))
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "timer",
                    "seconds_left": seconds_left,
                },
            )

            if seconds_left in hint_marks and state.word:
                masked = None
                async with self.state_lock():
                    await self.load_state_from_redis(state)
                    if state.status == "running" and state.word:
                        self.reveal_hint(state)
                        await self.save_state_to_redis(state)
                        masked = mask_word(state.word, state.revealed_indices)
                if masked is not None:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {"type": "hint", "masked_word": masked},
                    )

            if seconds_left <= 0:
                break

            await self.renew_timer_owner(seconds_left)
            await asyncio.sleep(1)

        await self.end_round(state, reason="time")

    def reveal_hint(self, state: GameState):
        if not state.word:
            return
        candidates = [
            idx
            for idx, char in enumerate(state.word)
            if char != " " and idx not in state.revealed_indices
        ]
        if not candidates:
            return
        reveal_count = 1
        picks = random.sample(candidates, k=min(reveal_count, len(candidates)))
        state.revealed_indices.update(picks)

    async def end_round(self, state: GameState, reason: str):
        word = ""
        scores_payload = {}
        current_round = 0
        max_rounds = 0

        async with self.state_lock():
            await self.load_state_from_redis(state)
            if state.status != "running":
                return
            state.status = "waiting"
            word = state.word or ""
            scores_payload = serialize_scores(state.scores)
            current_round = state.round_index
            max_rounds = state.max_rounds
            state.word = None
            state.drawer_id = None
            state.guessed = set()
            state.revealed_indices = set()
            await self.save_state_to_redis(state)
            await self.release_timer_owner()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "round_end",
                "word": word,
                "scores": scores_payload,
                "next_round_in": ROUND_BREAK_SECONDS,
                "reason": reason,
            },
        )
        await self.store_chat_message(
            {
                "id": f"{time.time()}-{random.random()}",
                "message": f"Word was: {word}",
                "system": True,
            }
        )

        await asyncio.sleep(ROUND_BREAK_SECONDS)

        if current_round < max_rounds:
            await self.start_round(state)
        else:
            await self.finish_game(state)

    async def finish_game(self, state: GameState):
        async with self.state_lock():
            await self.load_state_from_redis(state)
            state.status = "finished"
            state.word = None
            state.drawer_id = None
            scores_payload = serialize_scores(state.scores)
            await self.save_state_to_redis(state)
            await self.release_timer_owner()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "game_over",
                "scores": scores_payload,
            },
        )

    def choose_drawer(self, active_ids, last_drawer_id):
        if not active_ids:
            return None
        if len(active_ids) == 1:
            return active_ids[0]
        choices = [user_id for user_id in active_ids if user_id != last_drawer_id]
        if not choices:
            choices = active_ids
        return random.choice(choices)

    def required_votes(self, active_ids, target_id: int) -> int:
        eligible = [uid for uid in active_ids if uid != target_id]
        return max(1, math.ceil(len(eligible) * 0.8))

    async def send_to_user(self, user_id: int, payload):
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "direct_to_user",
                "target_id": user_id,
                "payload": payload,
            },
        )

    async def direct_to_user(self, event):
        if self.user.id != event.get("target_id"):
            return
        await self.send_json(event.get("payload", {}))

    async def direct_disconnect_user(self, event):
        if self.user.id != event.get("target_id"):
            return
        await self.close(code=event.get("close_code", 4003))

    async def presence(self, event):
        await self.send_json({"type": "presence", "members": event["members"]})

    async def draw(self, event):
        await self.send_json(
            {
                "type": "draw",
                "payload": event.get("payload"),
                "user": event.get("user"),
            }
        )

    async def chat(self, event):
        await self.send_json(
            {
                "type": "chat",
                "message": event.get("message"),
                "user": event.get("user"),
                "system": event.get("system", False),
                "client_id": event.get("client_id"),
            }
        )

    async def clear(self, event):
        await self.send_json({"type": "clear", "user": event.get("user")})

    async def round_start(self, event):
        await self.send_json(event)

    async def round_end(self, event):
        await self.send_json(event)

    async def game_over(self, event):
        await self.send_json(event)

    async def admin_close(self, event):
        await self.send_json(event)
        await self.close(code=4500)

    async def round_paused(self, event):
        await self.send_json(event)

    async def hint(self, event):
        await self.send_json(event)

    async def timer(self, event):
        await self.send_json(event)

    async def guess_correct(self, event):
        await self.send_json(event)

    async def kick_request(self, event):
        await self.send_json(event)

    async def kick_update(self, event):
        await self.send_json(event)

    async def kick_cancel(self, event):
        await self.send_json(event)

    async def system(self, event):
        await self.send_json(event)

    async def broadcast_presence(self):
        members = await self.get_active_members(self.room)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "presence",
                "members": members,
            },
        )
        await self.broadcast_lobby_update()

    async def broadcast_lobby_update(self):
        rooms = await self.get_rooms_snapshot()
        await self.channel_layer.group_send(
            "rooms_lobby",
            {
                "type": "rooms_list",
                "rooms": rooms,
            },
        )

    async def store_chat_message(self, payload: Dict):
        client = await get_redis_client()
        if not client:
            return
        try:
            key = chat_key(self.code)
            await client.rpush(key, json.dumps(payload))
            await client.ltrim(key, -CHAT_HISTORY_LIMIT, -1)
            await client.expire(key, ROOM_HISTORY_TTL_SECONDS)
        except Exception:
            return

    async def get_chat_history(self):
        client = await get_redis_client()
        if not client:
            return []
        try:
            data = await client.lrange(chat_key(self.code), 0, -1)
            return [json.loads(item) for item in data]
        except Exception:
            return []

    async def store_draw(self, payload: Dict):
        client = await get_redis_client()
        if not client:
            return
        try:
            key = draw_key(self.code)
            await client.rpush(key, json.dumps(payload))
            await client.ltrim(key, -DRAW_HISTORY_LIMIT, -1)
            await client.expire(key, ROOM_HISTORY_TTL_SECONDS)
        except Exception:
            return

    async def get_draw_history(self):
        client = await get_redis_client()
        if not client:
            return []
        try:
            data = await client.lrange(draw_key(self.code), 0, -1)
            return [json.loads(item) for item in data]
        except Exception:
            return []

    async def clear_draw_history(self):
        client = await get_redis_client()
        if not client:
            return
        try:
            await client.delete(draw_key(self.code))
        except Exception:
            return

    def check_chat_allowed(self, state: GameState, user_id: int) -> Tuple[bool, int]:
        now = time.time()
        cooldown_until = state.chat_cooldowns.get(user_id, 0)
        if now < cooldown_until:
            return False, max(1, int(cooldown_until - now))

        history = state.chat_history.get(user_id)
        if history is None:
            history = deque()
            state.chat_history[user_id] = history
        while history and now - history[0] > CHAT_WINDOW_SECONDS:
            history.popleft()

        if len(history) >= CHAT_MAX_BURST:
            penalty = min(MAX_CHAT_COOLDOWN, state.chat_penalties.get(user_id, 0) + 2)
            state.chat_penalties[user_id] = penalty
            state.chat_cooldowns[user_id] = now + penalty
            return False, penalty

        history.append(now)
        current_penalty = state.chat_penalties.get(user_id, 0)
        if current_penalty > 0:
            state.chat_penalties[user_id] = max(0, current_penalty - 1)
        return True, 0

    @database_sync_to_async
    def get_room(self, code):
        return Room.objects.filter(code=code, is_active=True).first()

    @database_sync_to_async
    def sync_room_empty_state_db(self):
        return sync_room_empty_state(self.room.id)

    @database_sync_to_async
    def cleanup_inactive_rooms_db(self):
        return cleanup_inactive_rooms()

    @database_sync_to_async
    def is_user_allowed(self, user_id: int) -> bool:
        from authapp.models import PlayerProfile, UserStatus

        status_row, _ = UserStatus.objects.get_or_create(user_id=user_id)
        if status_row.is_banned or status_row.is_deleted:
            return False
        profile, _ = PlayerProfile.objects.get_or_create(user_id=user_id)
        return bool((profile.display_name or "").strip())

    @database_sync_to_async
    def set_member_inactive(self, room, user_id):
        RoomMember.objects.filter(room=room, user_id=user_id).update(is_active=False)

    @database_sync_to_async
    def get_active_members(self, room):
        from authapp.models import PlayerProfile

        members = (
            RoomMember.objects.filter(room=room, is_active=True)
            .select_related("user")
            .order_by("joined_at")
        )
        result = []
        for member in members:
            user = member.user
            profile, _ = PlayerProfile.objects.get_or_create(user=user)
            name = profile.display_name.strip() if profile.display_name else ""
            if not name:
                name = user.first_name or user.email.split("@")[0] or f"Player {user.id}"
            result.append(
                {
                    "id": member.user_id,
                    "name": name,
                    "avatar": {
                        "color": profile.avatar_color,
                        "eyes": profile.avatar_eyes,
                        "mouth": profile.avatar_mouth,
                        "accessory": profile.avatar_accessory,
                    },
                }
            )
        return result

    @database_sync_to_async
    def get_active_member_ids(self, code):
        room = Room.objects.filter(code=code, is_active=True).first()
        if not room:
            return []
        return list(
            RoomMember.objects.filter(room=room, is_active=True).values_list(
                "user_id", flat=True
            )
        )

    @database_sync_to_async
    def is_member_active(self, room, user_id: int) -> bool:
        return RoomMember.objects.filter(room=room, user_id=user_id, is_active=True).exists()

    @database_sync_to_async
    def get_rooms_snapshot(self):
        return rooms_snapshot()

    @database_sync_to_async
    def get_public_user(self, user_id: int):
        User = get_user_model()
        from authapp.models import PlayerProfile

        user = User.objects.filter(id=user_id).first()
        if not user:
            return {
                "id": user_id,
                "name": f"Player {user_id}",
                "avatar": {
                    "color": "#5eead4",
                    "eyes": "dot",
                    "mouth": "smile",
                    "accessory": "none",
                },
            }
        profile, _ = PlayerProfile.objects.get_or_create(user=user)
        name = profile.display_name.strip() if profile.display_name else ""
        if not name:
            name = user.first_name or user.email.split("@")[0] or f"Player {user.id}"
        return {
            "id": user.id,
            "name": name,
            "avatar": {
                "color": profile.avatar_color,
                "eyes": profile.avatar_eyes,
                "mouth": profile.avatar_mouth,
                "accessory": profile.avatar_accessory,
            },
        }


class LobbyConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or user.is_anonymous:
            await self.close(code=4401)
            return
        if not await self.is_user_allowed(user.id):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add("rooms_lobby", self.channel_name)
        await self.accept()
        await self.send_rooms_list()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("rooms_lobby", self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def rooms_list(self, event):
        await self.send_json({"type": "rooms_list", "rooms": event.get("rooms", [])})

    async def send_rooms_list(self):
        rooms = await self.get_rooms_snapshot()
        await self.send_json({"type": "rooms_list", "rooms": rooms})

    @database_sync_to_async
    def get_rooms_snapshot(self):
        return rooms_snapshot()

    @database_sync_to_async
    def is_user_allowed(self, user_id: int) -> bool:
        from authapp.models import UserStatus

        status_row, _ = UserStatus.objects.get_or_create(user_id=user_id)
        return not status_row.is_deleted and not status_row.is_banned
