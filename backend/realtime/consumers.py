import asyncio
import json
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Set, Tuple

import redis.asyncio as redis
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth.models import AnonymousUser

from .models import Room, RoomMember
from .lobby import rooms_snapshot

MAX_PLAYERS = 8
CHAT_HISTORY_LIMIT = 500
DRAW_HISTORY_LIMIT = 2000
CHAT_WINDOW_SECONDS = 4
CHAT_MAX_BURST = 3
DISCONNECT_GRACE_SECONDS = 60
ROUND_BREAK_SECONDS = 5
KICK_VOTE_SECONDS = 20
MAX_CHAT_COOLDOWN = 12

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


class RoomConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.code = self.scope["url_route"]["kwargs"]["code"].upper()
        self.room_group_name = f"room_{self.code}"
        user = self.scope.get("user")

        if not user or isinstance(user, AnonymousUser) or user.is_anonymous:
            await self.close(code=4401)
            return

        room = await self.get_room(self.code)
        if not room:
            await self.close(code=4404)
            return

        if not await self.is_user_allowed(user.id):
            await self.close(code=4403)
            return

        allowed = await self.ensure_member_active(room, user)
        if not allowed:
            await self.close(code=4403)
            return

        self.room = room
        self.user = user
        self.user_info = {
            "id": user.id,
            "name": (user.get_full_name() or user.email or user.username),
            "email": user.email,
        }

        state = get_state(self.code)
        lock = get_lock(self.code)
        async with lock:
            state.connections.setdefault(user.id, set()).add(self.channel_name)
            state.scores.setdefault(user.id, 0)
            task = state.disconnect_tasks.pop(user.id, None)
            if task:
                task.cancel()

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
        lock = get_lock(self.code)
        async with lock:
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
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def mark_inactive_later(self, user_id: int):
        await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
        state = get_state(self.code)
        lock = get_lock(self.code)
        async with lock:
            if user_id in state.connections:
                return
        await self.set_member_inactive(self.room, user_id)
        await self.cleanup_kick_votes(state, user_id)
        await self.broadcast_presence()
        await self.maybe_pause_game(state)

    async def receive_json(self, content, **kwargs):
        message_type = content.get("type")
        state = get_state(self.code)

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
        if (
            state.status == "running"
            and state.word
            and self.user.id != state.drawer_id
            and self.user.id not in state.guessed
            and normalized == state.word.lower()
        ):
            points = max(20, 100 - 10 * len(state.guessed))
            state.guessed.add(self.user.id)
            state.scores[self.user.id] = state.scores.get(self.user.id, 0) + points
            if state.drawer_id:
                state.scores[state.drawer_id] = state.scores.get(state.drawer_id, 0) + 10

            system_message = f"✅ {self.user_info['name']} guessed correctly! (+{points}) 🎉"
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

            active_ids = self.get_connected_user_ids(state)
            if not active_ids:
                active_ids = await self.get_active_member_ids(self.code)
            if len(state.guessed) >= max(0, len(active_ids) - 1):
                await self.end_round(state, reason="all_guessed")
        else:
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
        if state.kick_votes:
            await self.send_json({"type": "error", "message": "Kick vote already in progress."})
            return

        active_ids = self.get_connected_user_ids(state)
        if not active_ids:
            active_ids = await self.get_active_member_ids(self.code)
        if target_id not in active_ids:
            return

        voters = state.kick_votes.setdefault(target_id, set())
        voters.add(self.user.id)
        responses = state.kick_responses.setdefault(target_id, set())
        responses.add(self.user.id)

        required = self.required_votes(active_ids, target_id)

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
        if target_id not in state.kick_votes:
            return
        if target_id == self.user.id:
            return

        active_ids = self.get_connected_user_ids(state)
        if not active_ids:
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
        for channel_name in list(state.connections.get(user_id, set())):
            await self.channel_layer.send(channel_name, {"type": "kick_disconnect"})
        state.connections.pop(user_id, None)
        await self.set_member_inactive(self.room, user_id)
        await self.broadcast_presence()
        await self.maybe_pause_game(state)

    async def maybe_pause_game(self, state: GameState):
        active_ids = self.get_connected_user_ids(state)
        if not active_ids:
            active_ids = await self.get_active_member_ids(self.code)
        if len(active_ids) >= 2:
            return
        if state.status == "running":
            state.status = "waiting"
            if state.task and not state.task.done():
                state.task.cancel()
            state.word = None
            state.drawer_id = None
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "round_paused",
                    "message": "Need at least 2 players to continue.",
                },
            )

    async def kick_timeout(self, state: GameState, target_id: int):
        await asyncio.sleep(KICK_VOTE_SECONDS)
        if target_id in state.kick_votes:
            await self.cancel_kick_vote(state, target_id, "Vote expired")

    async def cancel_kick_vote(self, state: GameState, target_id: int, reason: str):
        task = state.kick_timeout_tasks.pop(target_id, None)
        if task:
            task.cancel()
        state.kick_votes.pop(target_id, None)
        state.kick_responses.pop(target_id, None)
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "kick_cancel",
                "target_id": target_id,
                "reason": reason,
            },
        )

    async def cleanup_kick_votes(self, state: GameState, user_id: int):
        if user_id in state.kick_votes:
            await self.cancel_kick_vote(state, user_id, "Player left")
            return
        if not state.kick_votes:
            return
        target_id = next(iter(state.kick_votes.keys()))
        active_ids = self.get_connected_user_ids(state)
        if not active_ids:
            active_ids = await self.get_active_member_ids(self.code)
        eligible = [uid for uid in active_ids if uid != target_id]
        voters = state.kick_votes.get(target_id, set())
        responses = state.kick_responses.get(target_id, set())
        voters.discard(user_id)
        responses.discard(user_id)
        voters.intersection_update(eligible)
        responses.intersection_update(eligible)
        required = self.required_votes(active_ids, target_id)
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
        for channel_name in list(state.connections.get(target_id, set())):
            await self.channel_layer.send(channel_name, {"type": "kick_disconnect"})
        state.connections.pop(target_id, None)
        await self.set_member_inactive(self.room, target_id)
        await self.broadcast_presence()

    async def send_game_state(self, state: GameState):
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
        if state.status != "waiting" or state.round_index > 0:
            return
        active_ids = self.get_connected_user_ids(state)
        if not active_ids:
            active_ids = await self.get_active_member_ids(self.code)
        if len(active_ids) >= 2:
            await self.start_round(state)

    async def start_game(self, state: GameState):
        if state.status == "running":
            return
        await self.start_round(state)

    async def start_round(self, state: GameState):
        lock = get_lock(self.code)
        async with lock:
            if state.status == "running":
                return
            active_ids = self.get_connected_user_ids(state)
            if not active_ids:
                active_ids = await self.get_active_member_ids(self.code)
            if len(active_ids) < 2:
                await self.send_json(
                    {"type": "error", "message": "Need at least 2 players to start."}
                )
                return

            next_round = state.round_index + 1
            if next_round > state.max_rounds:
                await self.finish_game(state)
                return

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
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "clear",
                    "user": {"id": state.drawer_id},
                },
            )

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "round_start",
                    "round": state.round_index,
                    "max_rounds": state.max_rounds,
                    "drawer_id": state.drawer_id,
                    "masked_word": masked,
                    "duration": state.round_seconds,
                    "scores": serialize_scores(state.scores),
                },
            )

            await self.send_to_user(state.drawer_id, {"type": "round_secret", "word": state.word})

            if state.task and not state.task.done():
                state.task.cancel()
            state.task = asyncio.create_task(self.round_timer(state))

    async def round_timer(self, state: GameState):
        hint_marks = {90, 60, 30}
        for remaining in range(state.round_seconds, -1, -1):
            if state.status != "running":
                return
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "timer",
                    "seconds_left": remaining,
                },
            )
            if remaining in hint_marks and state.word:
                self.reveal_hint(state)
                masked = mask_word(state.word, state.revealed_indices)
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {"type": "hint", "masked_word": masked},
                )
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
        if state.status != "running":
            return
        state.status = "waiting"
        word = state.word or ""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "round_end",
                "word": word,
                "scores": serialize_scores(state.scores),
                "next_round_in": ROUND_BREAK_SECONDS,
                "reason": reason,
            },
        )
        await self.store_chat_message(
            {
                "id": f"{time.time()}-{random.random()}",
                "message": f"✨ Word was: {word}",
                "system": True,
            }
        )
        state.word = None
        state.drawer_id = None

        await asyncio.sleep(ROUND_BREAK_SECONDS)
        if state.round_index < state.max_rounds:
            await self.start_round(state)
        else:
            await self.finish_game(state)

    async def finish_game(self, state: GameState):
        state.status = "finished"
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "game_over",
                "scores": serialize_scores(state.scores),
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

    def get_connected_user_ids(self, state: GameState):
        return list(state.connections.keys())

    def required_votes(self, active_ids, target_id: int) -> int:
        eligible = [uid for uid in active_ids if uid != target_id]
        return max(1, math.ceil(len(eligible) * 0.8))

    async def send_to_user(self, user_id: int, payload):
        state = get_state(self.code)
        for channel_name in state.connections.get(user_id, set()):
            await self.channel_layer.send(channel_name, {"type": "direct", "payload": payload})

    async def direct(self, event):
        await self.send_json(event.get("payload", {}))

    async def kick_disconnect(self, event):
        await self.close(code=4003)

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
            await client.rpush(chat_key(self.code), json.dumps(payload))
            await client.ltrim(chat_key(self.code), -CHAT_HISTORY_LIMIT, -1)
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
            await client.rpush(draw_key(self.code), json.dumps(payload))
            await client.ltrim(draw_key(self.code), -DRAW_HISTORY_LIMIT, -1)
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
    def is_user_allowed(self, user_id: int) -> bool:
        from authapp.models import UserStatus

        status_row, _ = UserStatus.objects.get_or_create(user_id=user_id)
        return not (status_row.is_banned or status_row.is_deleted)

    @database_sync_to_async
    def ensure_member_active(self, room, user):
        member = RoomMember.objects.filter(room=room, user=user).first()
        if member and member.is_active:
            return True

        active_count = RoomMember.objects.filter(room=room, is_active=True).count()
        if active_count >= MAX_PLAYERS:
            return False

        if member:
            member.is_active = True
            member.save(update_fields=["is_active"])
        else:
            RoomMember.objects.create(room=room, user=user, is_active=True)
        return True

    @database_sync_to_async
    def set_member_inactive(self, room, user_id):
        RoomMember.objects.filter(room=room, user_id=user_id).update(is_active=False)

    @database_sync_to_async
    def get_active_members(self, room):
        members = (
            RoomMember.objects.filter(room=room, is_active=True)
            .select_related("user")
            .order_by("joined_at")
        )
        return [
            {
                "id": member.user_id,
                "name": member.user.get_full_name() or member.user.email,
                "email": member.user.email,
            }
            for member in members
        ]

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


class LobbyConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or user.is_anonymous:
            await self.close(code=4401)
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
