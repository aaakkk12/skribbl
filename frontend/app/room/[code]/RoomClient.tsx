"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  apiFetch,
  getFriends,
  listRoomInvites,
  respondRoomInvite,
  sendRoomInvite,
  type FriendUser,
  type IncomingInvite,
} from "../../../lib/api";
import PlayerAvatar, { type AvatarConfig } from "../../../components/PlayerAvatar";

type Member = {
  id: number;
  name: string;
  avatar?: AvatarConfig;
};

type MeResponse = {
  id: number;
  email: string;
  first_name: string;
  display_name: string;
  profile_completed: boolean;
  avatar: AvatarConfig;
};

type DrawPayload = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  color: string;
  size: number;
};

type ChatMessage = {
  id: string;
  user?: Member;
  message: string;
  system?: boolean;
};

type RoundInfo = {
  round: number;
  maxRounds: number;
  drawerId: number | null;
  maskedWord: string;
  timeLeft: number;
  word: string;
};

type RoundBreak = {
  word: string;
  seconds: number;
};

type KickModal = {
  targetId: number;
  targetName: string;
  requesterId: number;
  votes: number;
  required: number;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function RoomClient({ code }: { code: string }) {
  const router = useRouter();
  const [members, setMembers] = useState<Member[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatCooldown, setChatCooldown] = useState(0);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("connecting");
  const [color, setColor] = useState("#5eead4");
  const [size, setSize] = useState(3);
  const [me, setMe] = useState<Member | null>(null);
  const [scores, setScores] = useState<Record<number, number>>({});
  const [gameStatus, setGameStatus] = useState("waiting");
  const [roundInfo, setRoundInfo] = useState<RoundInfo>({
    round: 0,
    maxRounds: 10,
    drawerId: null,
    maskedWord: "_ _ _",
    timeLeft: 0,
    word: "",
  });
  const [roundBreak, setRoundBreak] = useState<RoundBreak | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [kickModal, setKickModal] = useState<KickModal | null>(null);
  const [friends, setFriends] = useState<FriendUser[]>([]);
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [inviteSendingId, setInviteSendingId] = useState<number | null>(null);
  const [incomingInvites, setIncomingInvites] = useState<IncomingInvite[]>([]);
  const [inviteRespondingId, setInviteRespondingId] = useState<number | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const pingTimer = useRef<NodeJS.Timeout | null>(null);
  const shouldReconnect = useRef(true);
  const roundBreakTimer = useRef<NodeJS.Timeout | null>(null);
  const toastTimer = useRef<NodeJS.Timeout | null>(null);
  const cooldownTimer = useRef<NodeJS.Timeout | null>(null);
  const membersRef = useRef<Member[]>([]);
  const meRef = useRef<Member | null>(null);
  const pendingChatIds = useRef<Set<string>>(new Set());
  const chatListRef = useRef<HTMLDivElement | null>(null);
  const invitesPollTimer = useRef<NodeJS.Timeout | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const canvasWrapRef = useRef<HTMLDivElement | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);

  const isDrawer = Boolean(
    me && roundInfo.drawerId === me.id && gameStatus === "running"
  );
  const hintText = isDrawer
    ? roundInfo.word || "..."
    : roundInfo.maskedWord || "_ _ _";

  const leaderboard = useMemo(() => {
    return [...members]
      .sort((a, b) => (scores[b.id] ?? 0) - (scores[a.id] ?? 0))
      .slice(0, 8);
  }, [members, scores]);

  const showToast = (message: string, duration = 2500) => {
    setToast(message);
    if (toastTimer.current) {
      clearTimeout(toastTimer.current);
    }
    toastTimer.current = setTimeout(() => setToast(null), duration);
  };

  const startChatCooldown = (seconds: number) => {
    if (cooldownTimer.current) {
      clearInterval(cooldownTimer.current);
    }
    setChatCooldown(seconds);
    cooldownTimer.current = setInterval(() => {
      setChatCooldown((prev) => {
        if (prev <= 1) {
          if (cooldownTimer.current) {
            clearInterval(cooldownTimer.current);
            cooldownTimer.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const startRoundBreak = (word: string, seconds: number) => {
    if (roundBreakTimer.current) {
      clearInterval(roundBreakTimer.current);
    }
    setRoundBreak({ word, seconds });
    roundBreakTimer.current = setInterval(() => {
      setRoundBreak((prev) => {
        if (!prev) return null;
        if (prev.seconds <= 1) {
          if (roundBreakTimer.current) {
            clearInterval(roundBreakTimer.current);
            roundBreakTimer.current = null;
          }
          return null;
        }
        return { ...prev, seconds: prev.seconds - 1 };
      });
    }, 1000);
  };

  const fetchFriends = useCallback(async () => {
    try {
      const response = await getFriends();
      setFriends(response.friends || []);
    } catch {
      setFriends([]);
    }
  }, []);

  const fetchIncomingInvites = useCallback(async () => {
    try {
      const response = await listRoomInvites();
      setIncomingInvites(response.received || []);
    } catch {
      // silent poll
    }
  }, []);

  useEffect(() => {
    const ensureAuth = async () => {
      let meData: MeResponse;
      try {
        meData = await apiFetch<MeResponse>("/api/auth/me/", { method: "GET" });
      } catch {
        router.push("/login");
        return;
      }
      if (!meData.profile_completed) {
        router.push("/profile/setup");
        return;
      }
      setMe({
        id: meData.id,
        name: meData.display_name || meData.first_name || meData.email.split("@")[0],
        avatar: meData.avatar,
      });
      await fetchFriends();
      await fetchIncomingInvites();
      try {
        await apiFetch("/api/rooms/join/", {
          method: "POST",
          body: JSON.stringify({ code }),
        });
      } catch {
        router.push("/rooms");
      }
    };
    ensureAuth();
  }, [code, fetchFriends, fetchIncomingInvites, router]);

  useEffect(() => {
    membersRef.current = members;
  }, [members]);

  useEffect(() => {
    meRef.current = me;
  }, [me]);

  useEffect(() => {
    if (!me) return;
    fetchIncomingInvites();
    if (invitesPollTimer.current) {
      clearInterval(invitesPollTimer.current);
    }
    invitesPollTimer.current = setInterval(() => {
      fetchIncomingInvites();
    }, 5000);
    return () => {
      if (invitesPollTimer.current) {
        clearInterval(invitesPollTimer.current);
        invitesPollTimer.current = null;
      }
    };
  }, [fetchIncomingInvites, me]);

  useEffect(() => {
    if (!chatListRef.current) return;
    chatListRef.current.scrollTop = chatListRef.current.scrollHeight;
  }, [chatMessages]);

  useEffect(() => {
    const resizeCanvas = () => {
      const canvas = canvasRef.current;
      const wrapper = canvasWrapRef.current;
      if (!canvas || !wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
      }
    };

    resizeCanvas();
    const observer = new ResizeObserver(resizeCanvas);
    if (canvasWrapRef.current) {
      observer.observe(canvasWrapRef.current);
    }
    window.addEventListener("resize", resizeCanvas);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resizeCanvas);
    };
  }, []);

  useEffect(() => {
    shouldReconnect.current = true;

    const connectSocket = () => {
      if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
        return;
      }

      const socket = new WebSocket(`${WS_BASE}/ws/rooms/${code.toUpperCase()}/`);
      socketRef.current = socket;

      socket.onopen = () => {
        setStatus("connected");
        reconnectAttempts.current = 0;
        if (pingTimer.current) {
          clearInterval(pingTimer.current);
        }
        pingTimer.current = setInterval(() => {
          sendSocket({ type: "ping" });
        }, 20000);
      };

      socket.onclose = (event) => {
        const fatalCodes = [4003, 4401, 4403, 4404];
        if (fatalCodes.includes(event.code)) {
          shouldReconnect.current = false;
          if (event.code === 4401) {
            router.push("/login");
          } else if (event.code === 4403 || event.code === 4404) {
            showToast("Room access denied.");
            setTimeout(() => router.push("/rooms"), 500);
          }
        }
        setStatus("disconnected");
        if (pingTimer.current) {
          clearInterval(pingTimer.current);
          pingTimer.current = null;
        }
        if (shouldReconnect.current) {
          const nextAttempt = Math.min(reconnectAttempts.current + 1, 6);
          reconnectAttempts.current = nextAttempt;
          const delay = Math.min(10000, 1000 * 2 ** (nextAttempt - 1));
          reconnectTimer.current = setTimeout(connectSocket, delay);
        }
      };

      socket.onerror = () => {
        setStatus("error");
        socket.close();
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "presence") {
          setMembers(data.members || []);
        } else if (data.type === "draw") {
          if (data.payload) {
            drawFromPayload(data.payload as DrawPayload);
          }
        } else if (data.type === "chat") {
          const message = data.message || "";
          const user = data.user as Member | undefined;
          const clientId = data.client_id as string | undefined;
          if (clientId && pendingChatIds.current.has(clientId)) {
            pendingChatIds.current.delete(clientId);
            return;
          }
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              user,
              message,
              system: data.system || false,
            },
          ]);
        } else if (data.type === "guess_correct") {
          setScores(data.scores || {});
          showToast("🎉 Correct guess!");
        } else if (data.type === "clear") {
          clearCanvas();
        } else if (data.type === "round_start") {
          setGameStatus("running");
          setRoundInfo((prev) => ({
            ...prev,
            round: data.round,
            maxRounds: data.max_rounds,
            drawerId: data.drawer_id,
            maskedWord: data.masked_word,
            timeLeft: data.duration,
            word: "",
          }));
          setScores(data.scores || {});
          if (roundBreakTimer.current) {
            clearInterval(roundBreakTimer.current);
            roundBreakTimer.current = null;
          }
          setRoundBreak(null);
          showToast(`Round ${data.round} started!`);
        } else if (data.type === "round_end") {
          setGameStatus("waiting");
          setScores(data.scores || {});
          setRoundInfo((prev) => ({
            ...prev,
            maskedWord: data.word,
            word: "",
          }));
          const nextIn = data.next_round_in || 5;
          startRoundBreak(data.word, nextIn);
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              message: `✨ Word was: ${data.word}`,
              system: true,
            },
          ]);
        } else if (data.type === "round_paused") {
          setGameStatus("waiting");
          setRoundInfo((prev) => ({
            ...prev,
            word: "",
          }));
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              message: data.message || "Need at least 2 players to continue.",
              system: true,
            },
          ]);
          showToast(data.message || "Waiting for players...");
        } else if (data.type === "admin_close") {
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              message: data.message || "Room closed by admin.",
              system: true,
            },
          ]);
          showToast(data.message || "Room closed by admin.");
          setTimeout(() => router.push("/rooms"), 1200);
        } else if (data.type === "game_over") {
          setGameStatus("finished");
          setScores(data.scores || {});
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              message: "Game finished!",
              system: true,
            },
          ]);
        } else if (data.type === "hint") {
          setRoundInfo((prev) => ({
            ...prev,
            maskedWord: data.masked_word,
          }));
        } else if (data.type === "timer") {
          setRoundInfo((prev) => ({
            ...prev,
            timeLeft: data.seconds_left,
          }));
        } else if (data.type === "round_secret") {
          setRoundInfo((prev) => ({
            ...prev,
            word: data.word,
          }));
        } else if (data.type === "game_state") {
          setGameStatus(data.status || "waiting");
          setRoundInfo((prev) => ({
            ...prev,
            round: data.round || 0,
            maxRounds: data.max_rounds || 10,
            drawerId: data.drawer_id ?? null,
            maskedWord: data.masked_word || prev.maskedWord,
            timeLeft: data.seconds_left ?? prev.timeLeft,
          }));
          if (data.scores) {
            setScores(data.scores);
          }
        } else if (data.type === "history") {
          if (Array.isArray(data.chat)) {
            setChatMessages(
              data.chat.map((item: ChatMessage) => ({
                id: item.id || `${Date.now()}-${Math.random()}`,
                user: item.user,
                message: item.message,
                system: item.system || false,
              }))
            );
          }
          if (Array.isArray(data.draw)) {
            clearCanvas();
            data.draw.forEach((payload: DrawPayload) => {
              drawFromPayload(payload);
            });
          }
        } else if (data.type === "kick_request") {
          const targetId = data.target_id;
          const requesterId = data.requester_id;
          const currentMembers = membersRef.current;
          const currentMe = meRef.current;
          const target = currentMembers.find((m) => m.id === targetId);
          if (currentMe && targetId === currentMe.id) {
            showToast("Kick vote started against you.");
            return;
          }
          if (currentMe && requesterId === currentMe.id) {
            showToast("Kick vote started.");
            return;
          }
          setKickModal({
            targetId,
            targetName: target?.name || `Player ${targetId}`,
            requesterId,
            votes: data.votes || 0,
            required: data.required || 1,
          });
        } else if (data.type === "kick_update") {
          setKickModal((prev) => {
            if (!prev || prev.targetId !== data.target_id) return prev;
            return {
              ...prev,
              votes: data.votes || prev.votes,
              required: data.required || prev.required,
            };
          });
        } else if (data.type === "kick_cancel") {
          setKickModal((prev) => {
            if (!prev || prev.targetId !== data.target_id) return prev;
            return null;
          });
          if (data.reason) {
            showToast(data.reason);
          }
        } else if (data.type === "kicked") {
          setChatMessages((prev) => [
            ...prev,
            {
              id: `${Date.now()}-${Math.random()}`,
              message: data.reason || "You were removed from the room.",
              system: true,
            },
          ]);
          setTimeout(() => router.push("/rooms"), 1200);
        } else if (data.type === "chat_cooldown") {
          const seconds = Number(data.seconds || 2);
          const clientId = data.client_id as string | undefined;
          if (clientId && pendingChatIds.current.has(clientId)) {
            pendingChatIds.current.delete(clientId);
            setChatMessages((prev) => prev.filter((item) => item.id !== clientId));
          }
          startChatCooldown(seconds);
          showToast(`Slow down. Wait ${seconds}s`);
        } else if (data.type === "chat_blocked") {
          const clientId = data.client_id as string | undefined;
          if (clientId && pendingChatIds.current.has(clientId)) {
            pendingChatIds.current.delete(clientId);
            setChatMessages((prev) => prev.filter((item) => item.id !== clientId));
          }
          if (data.reason) {
            showToast(data.reason);
          }
        } else if (data.type === "error") {
          if (data.message) {
            setChatMessages((prev) => [
              ...prev,
              {
                id: `${Date.now()}-${Math.random()}`,
                message: data.message,
                system: true,
              },
            ]);
          } else {
            setError("Something went wrong");
          }
        }
      };
    };

    connectSocket();

    const handlePageLeave = () => {
      sendSocket({ type: "leave" });
    };
    window.addEventListener("beforeunload", handlePageLeave);
    window.addEventListener("pagehide", handlePageLeave);

    return () => {
      shouldReconnect.current = false;
      handlePageLeave();
      window.removeEventListener("beforeunload", handlePageLeave);
      window.removeEventListener("pagehide", handlePageLeave);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (pingTimer.current) {
        clearInterval(pingTimer.current);
      }
      if (roundBreakTimer.current) {
        clearInterval(roundBreakTimer.current);
      }
      if (toastTimer.current) {
        clearTimeout(toastTimer.current);
      }
      if (cooldownTimer.current) {
        clearInterval(cooldownTimer.current);
      }
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, [code, router]);

  const sendSocket = (payload: Record<string, unknown>) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(payload));
    }
  };

  const getPoint = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const wrapper = canvasWrapRef.current;
    if (!wrapper) return { x: 0, y: 0 };
    const rect = wrapper.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    return { x, y };
  };

  const drawFromPayload = (payload: DrawPayload) => {
    const canvas = canvasRef.current;
    const wrapper = canvasWrapRef.current;
    if (!canvas || !wrapper) return;
    const rect = wrapper.getBoundingClientRect();
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.strokeStyle = payload.color;
    ctx.lineWidth = payload.size;
    ctx.beginPath();
    ctx.moveTo(payload.x0 * rect.width, payload.y0 * rect.height);
    ctx.lineTo(payload.x1 * rect.width, payload.y1 * rect.height);
    ctx.stroke();
  };

  const clearCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawer) return;
    event.preventDefault();
    drawingRef.current = true;
    lastPointRef.current = getPoint(event);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current || !lastPointRef.current || !isDrawer) return;
    const point = getPoint(event);
    const payload: DrawPayload = {
      x0: lastPointRef.current.x,
      y0: lastPointRef.current.y,
      x1: point.x,
      y1: point.y,
      color,
      size,
    };
    drawFromPayload(payload);
    sendSocket({ type: "draw", payload });
    lastPointRef.current = point;
  };

  const handlePointerUp = () => {
    drawingRef.current = false;
    lastPointRef.current = null;
  };

  const handleChatSend = (event: React.FormEvent) => {
    event.preventDefault();
    if (!chatInput.trim() || chatCooldown > 0 || (isDrawer && gameStatus === "running")) return;
    const clientId = `${Date.now()}-${Math.random()}`;
    const message = chatInput.trim();
    pendingChatIds.current.add(clientId);
    setChatMessages((prev) => [
      ...prev,
      {
        id: clientId,
        user: me || undefined,
        message,
        system: false,
      },
    ]);
    sendSocket({ type: "chat", message, client_id: clientId });
    setChatInput("");
  };

  const handleClear = () => {
    if (!isDrawer) return;
    clearCanvas();
    sendSocket({ type: "clear" });
  };

  const handleVoteKick = (targetId: number) => {
    sendSocket({ type: "kick_request", target_id: targetId });
  };

  const handleKickResponse = (approve: boolean) => {
    if (!kickModal) return;
    sendSocket({ type: "kick_vote", target_id: kickModal.targetId, approve });
    setKickModal(null);
  };

  const handleSendInvite = async (friendId: number) => {
    setInviteSendingId(friendId);
    try {
      const response = await sendRoomInvite(code, friendId);
      showToast(response.detail || "Invite sent.");
      await fetchIncomingInvites();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Unable to send invite.");
    } finally {
      setInviteSendingId(null);
    }
  };

  const handleInviteAction = async (inviteId: number, action: "accept" | "reject") => {
    setInviteRespondingId(inviteId);
    try {
      const response = await respondRoomInvite(inviteId, action);
      setIncomingInvites((prev) => prev.filter((invite) => invite.id !== inviteId));
      if (action === "accept" && response.code) {
        shouldReconnect.current = false;
        if (socketRef.current) {
          socketRef.current.close();
        }
        router.push(`/room/${response.code}`);
        return;
      }
      showToast(response.detail || (action === "accept" ? "Joined room." : "Invite rejected."));
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Unable to handle invite.");
    } finally {
      setInviteRespondingId(null);
    }
  };

  const handleLeaveRoom = async () => {
    shouldReconnect.current = false;
    sendSocket({ type: "leave" });
    try {
      await apiFetch("/api/rooms/leave/", {
        method: "POST",
        body: JSON.stringify({ code }),
      });
    } catch {
      // ignore
    } finally {
      if (socketRef.current) {
        socketRef.current.close();
      }
      router.push("/rooms");
    }
  };

  const leftSlots = members.slice(0, 4);
  const rightSlots = members.slice(4, 8);

  const renderSlot = (slot?: Member) => {
    if (!slot) {
      return (
        <div className="player-slot empty">
          <span>Empty slot</span>
        </div>
      );
    }
    const isDrawing = slot.id === roundInfo.drawerId && gameStatus === "running";
    const canKick = Boolean(me && slot.id !== me.id);
    return (
      <div className="player-slot">
        <div className="player-title">
          <div className="player-id">
            <PlayerAvatar avatar={slot.avatar} size={30} />
            <strong>{slot.name}</strong>
          </div>
          {isDrawing ? <span className="player-tag">Drawing</span> : null}
        </div>
        <span className="score">Score: {scores[slot.id] ?? 0}</span>
        {canKick ? (
          <button className="kick-button" type="button" onClick={() => handleVoteKick(slot.id)}>
            Vote Kick
          </button>
        ) : null}
      </div>
    );
  };

  return (
    <main className="container">
      <section className="room-shell">
        <div className="nav-row">
          <div>
            <span className="kicker">Room {code.toUpperCase()}</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              Live drawing room
            </h1>
          </div>
          <div className="room-actions">
            <button
              className="button button-ghost"
              type="button"
              onClick={() => {
                fetchFriends();
                setInviteModalOpen(true);
              }}
            >
              Send invite
            </button>
            <button className="link link-button" type="button" onClick={handleLeaveRoom}>
              Leave room
            </button>
          </div>
        </div>
        {incomingInvites.length > 0 ? (
          <div className="invite-banner-list">
            {incomingInvites.map((invite) => (
              <div key={invite.id} className="invite-banner">
                <div className="invite-banner-user">
                  <PlayerAvatar avatar={invite.from_user.avatar} size={30} />
                  <span>
                    <strong>{invite.from_user.name}</strong> invited you to room{" "}
                    <strong>{invite.room_code}</strong>
                  </span>
                </div>
                <div className="invite-banner-actions">
                  <button
                    className="button button-ghost"
                    type="button"
                    disabled={inviteRespondingId === invite.id}
                    onClick={() => handleInviteAction(invite.id, "reject")}
                  >
                    Reject
                  </button>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={inviteRespondingId === invite.id}
                    onClick={() => handleInviteAction(invite.id, "accept")}
                  >
                    Join
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <div className="room-status">
          <span className={`status-dot status-${status}`} />
          <span className="helper">{status}</span>
        </div>
        <div className="round-strip">
          <div className="round-meta">
            <span className="badge">Round {roundInfo.round} / {roundInfo.maxRounds}</span>
            <span className="helper">
              {gameStatus === "running"
                ? isDrawer
                  ? "You are drawing"
                  : "Guess the word"
                : "Waiting for players..."}
            </span>
          </div>
          <div className="hint-center">
            <span className="hint-label">{isDrawer ? "Your word" : "Hint"}</span>
            <div className="hint-text">{hintText}</div>
          </div>
          <div className="timer-pill">{roundInfo.timeLeft}s</div>
        </div>
        {roundBreak ? (
          <div className="round-break">
            <strong>Word was: {roundBreak.word}</strong>
            <span>Next round in {roundBreak.seconds}s</span>
          </div>
        ) : null}
        {toast ? <div className="toast">{toast}</div> : null}
        {error ? <p className="error">{error}</p> : null}
        <div className="room-grid">
          <div className="player-column">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={`left-${index}`}>{renderSlot(leftSlots[index])}</div>
            ))}
            <div className="leaderboard-card">
              <div className="leaderboard-header">
                <span className="badge">Leaderboard</span>
              </div>
              {leaderboard.length === 0 ? (
                <p className="helper">No scores yet.</p>
              ) : (
                <div className="leaderboard-list">
                  {leaderboard.map((player, index) => (
                    <div key={player.id} className="leaderboard-row">
                      <span>#{index + 1}</span>
                      <span className="leaderboard-name">{player.name}</span>
                      <span className="leaderboard-score">{scores[player.id] ?? 0}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="canvas-panel">
            <div className="canvas-toolbar">
              <div className="color-row">
                {["#5eead4", "#f59f0b", "#60a5fa", "#f472b6", "#f87171", "#a3e635"].map(
                  (swatch) => (
                    <button
                      key={swatch}
                      className={`color-chip ${color === swatch ? "active" : ""}`}
                      style={{ background: swatch }}
                      onClick={() => setColor(swatch)}
                      aria-label={`Color ${swatch}`}
                    />
                  )
                )}
              </div>
              <div className="size-row">
                <input
                  type="range"
                  min={1}
                  max={8}
                  value={size}
                  onChange={(event) => setSize(Number(event.target.value))}
                />
                <span className="helper">Brush {size}px</span>
              </div>
              <button className="button button-ghost" type="button" onClick={handleClear}>
                Clear canvas
              </button>
            </div>
            <div className="canvas-wrap" ref={canvasWrapRef}>
              <canvas
                ref={canvasRef}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={handlePointerUp}
                onPointerLeave={handlePointerUp}
              />
            </div>
            {!isDrawer && gameStatus === "running" ? (
              <p className="canvas-note">You are guessing. Wait for your turn.</p>
            ) : null}
            <div className="chat-panel">
              <div className="chat-list" ref={chatListRef}>
                {chatMessages.length === 0 ? (
                  <p className="helper">Start chatting with your room.</p>
                ) : (
                  chatMessages.map((message) => (
                    <div
                      key={message.id}
                      className={`chat-message ${message.system ? "system" : ""}`}
                    >
                      {message.system ? (
                        <span>{message.message}</span>
                      ) : (
                        <>
                          <strong>{message.user?.name || "Player"}</strong>
                          <span>{message.message}</span>
                        </>
                      )}
                    </div>
                  ))
                )}
              </div>
              <form onSubmit={handleChatSend} className="chat-input">
                <input
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  placeholder={isDrawer ? "Drawing mode..." : "Type your guess..."}
                  disabled={
                    gameStatus === "finished" ||
                    chatCooldown > 0 ||
                    (isDrawer && gameStatus === "running")
                  }
                />
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={
                    gameStatus === "finished" ||
                    chatCooldown > 0 ||
                    (isDrawer && gameStatus === "running")
                  }
                >
                  Send
                </button>
              </form>
              {chatCooldown > 0 ? (
                <p className="chat-cooldown">Cooldown: {chatCooldown}s</p>
              ) : null}
              {isDrawer && gameStatus === "running" ? (
                <p className="chat-cooldown">Chat disabled while you are drawing.</p>
              ) : null}
            </div>
          </div>
          <div className="player-column">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={`right-${index}`}>{renderSlot(rightSlots[index])}</div>
            ))}
          </div>
        </div>
        {inviteModalOpen ? (
          <div className="modal-backdrop">
            <div className="modal-card modal-card-wide">
              <h3>Invite friends</h3>
              <p className="helper">Send room request to your friend list.</p>
              <div className="modal-scroll-list">
                {friends.length === 0 ? (
                  <p className="helper">No friends found. Add friends from dashboard.</p>
                ) : (
                  friends.map((friend) => (
                    <div key={friend.id} className="social-row">
                      <div className="social-user">
                        <PlayerAvatar avatar={friend.avatar} size={30} />
                        <div>
                          <strong>{friend.name}</strong>
                          <p className="helper">{friend.email}</p>
                        </div>
                      </div>
                      <button
                        className="button button-primary"
                        type="button"
                        disabled={inviteSendingId === friend.id}
                        onClick={() => handleSendInvite(friend.id)}
                      >
                        Invite
                      </button>
                    </div>
                  ))
                )}
              </div>
              <div className="modal-actions">
                <button className="button button-ghost" onClick={() => setInviteModalOpen(false)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        ) : null}
        {kickModal ? (
          <div className="modal-backdrop">
            <div className="modal-card">
              <h3>Kick {kickModal.targetName}?</h3>
              <p>
                Votes: {kickModal.votes}/{kickModal.required}
              </p>
              <div className="modal-actions">
                <button className="button button-ghost" onClick={() => handleKickResponse(false)}>
                  No
                </button>
                <button className="button button-primary" onClick={() => handleKickResponse(true)}>
                  Yes
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
