"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../lib/api";

type RoomSummary = {
  code: string;
  active_count: number;
  max_players: number;
  is_full: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export default function RoomsPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [lobbyStatus, setLobbyStatus] = useState("connecting");
  const [visibility, setVisibility] = useState<"open" | "private">("open");
  const [createPassword, setCreatePassword] = useState("");
  const [joinPassword, setJoinPassword] = useState("");
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const lobbySocket = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ensureAuth = async () => {
      try {
        await apiFetch("/api/auth/me/", { method: "GET" });
      } catch {
        router.push("/login");
      }
    };
    ensureAuth();
  }, [router]);

  useEffect(() => {
    const fetchRooms = async () => {
      try {
        const response = await apiFetch<{ rooms: RoomSummary[] }>("/api/rooms/list/", {
          method: "GET",
        });
        setRooms(response.rooms || []);
      } catch {
        // ignore, websocket will update
      }
    };
    fetchRooms();
  }, []);

  useEffect(() => {
    let shouldReconnect = true;

    const connectLobby = () => {
      if (lobbySocket.current && lobbySocket.current.readyState === WebSocket.OPEN) {
        return;
      }

      const socket = new WebSocket(`${WS_BASE}/ws/lobby/`);
      lobbySocket.current = socket;

      socket.onopen = () => {
        setLobbyStatus("connected");
        reconnectAttempts.current = 0;
      };

      socket.onclose = () => {
        setLobbyStatus("disconnected");
        if (!shouldReconnect) return;
        const nextAttempt = Math.min(reconnectAttempts.current + 1, 6);
        reconnectAttempts.current = nextAttempt;
        const delay = Math.min(10000, 1000 * 2 ** (nextAttempt - 1));
        reconnectTimer.current = setTimeout(connectLobby, delay);
      };

      socket.onerror = () => {
        setLobbyStatus("error");
        socket.close();
      };

      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "rooms_list") {
          setRooms(data.rooms || []);
        }
      };
    };

    connectLobby();

    return () => {
      shouldReconnect = false;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (lobbySocket.current) {
        lobbySocket.current.close();
      }
    };
  }, []);

  const handleCreate = async () => {
    setError("");
    if (visibility === "private" && !createPassword.trim()) {
      setError("Password is required for private rooms.");
      return;
    }
    setLoading(true);
    try {
      const response = await apiFetch<{ code: string }>("/api/rooms/create/", {
        method: "POST",
        body: JSON.stringify({
          visibility,
          password: visibility === "private" ? createPassword : "",
        }),
      });
      router.push(`/room/${response.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create room");
    } finally {
      setLoading(false);
    }
  };

  const handleJoin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await apiFetch<{ code: string }>("/api/rooms/join/", {
        method: "POST",
        body: JSON.stringify({ code, password: joinPassword }),
      });
      router.push(`/room/${response.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to join room");
    } finally {
      setLoading(false);
    }
  };

  const handleQuickJoin = async (roomCode: string) => {
    setError("");
    setLoading(true);
    try {
      const target = rooms.find((room) => room.code === roomCode);
      let password = "";
      if (target?.is_private) {
        password = window.prompt(`Enter password for room ${roomCode}`) || "";
        if (!password) {
          setLoading(false);
          return;
        }
      }
      const response = await apiFetch<{ code: string }>("/api/rooms/join/", {
        method: "POST",
        body: JSON.stringify({ code: roomCode, password }),
      });
      router.push(`/room/${response.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to join room");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="auth-card">
        <div className="nav-row">
          <div>
            <span className="kicker">Live Drawing</span>
            <h1 className="hero-title" style={{ fontSize: "2.3rem" }}>
              Create or join a room
            </h1>
          </div>
          <Link className="link" href="/dashboard">
            Back to dashboard
          </Link>
        </div>
        <p className="helper">
          Rooms are limited to 8 players. Share the room code with friends to
          start drawing together.
        </p>
        <div className="room-actions-grid">
          <div className="room-card-lite">
            <div className="room-card-head">
              <h3>Create room</h3>
              <span className="helper">Choose open or private</span>
            </div>
            <div className="room-card-body">
              <div className="room-visibility">
                <label className="helper">Room type</label>
                <select
                  value={visibility}
                  onChange={(event) =>
                    setVisibility(event.target.value as "open" | "private")
                  }
                >
                  <option value="open">Open</option>
                  <option value="private">Private</option>
                </select>
              </div>
              {visibility === "private" ? (
                <input
                  className="room-password"
                  type="password"
                  value={createPassword}
                  onChange={(event) => setCreatePassword(event.target.value)}
                  placeholder="Set room password"
                  required
                />
              ) : null}
              <button
                className="button button-primary"
                onClick={handleCreate}
                disabled={loading}
              >
                {loading ? "Working..." : "Create room"}
              </button>
            </div>
          </div>
          <div className="room-card-lite">
            <div className="room-card-head">
              <h3>Join room</h3>
              <span className="helper">Enter code and password if needed</span>
            </div>
            <form onSubmit={handleJoin} className="room-join">
              <input
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                placeholder="Enter room code"
                maxLength={8}
              />
              <input
                type="password"
                value={joinPassword}
                onChange={(event) => setJoinPassword(event.target.value)}
                placeholder="Password (if private)"
              />
              <button className="button button-ghost" type="submit" disabled={loading}>
                Join
              </button>
            </form>
          </div>
        </div>
        {error ? <p className="error">{error}</p> : null}
        <div className="room-list-header">
          <span className={`status-dot status-${lobbyStatus}`} />
          <span className="helper">Live rooms</span>
        </div>
        <div className="room-list">
          {rooms.length === 0 ? (
            <p className="helper">No active rooms right now.</p>
          ) : (
            rooms.map((room) => (
              <div key={room.code} className="room-card">
                <div>
                  <span className="kicker">Room</span>
                  <h3>{room.code}</h3>
                  <p className="helper">
                    {room.active_count}/{room.max_players} players
                  </p>
                </div>
                <div className="room-card-actions">
                  <span className={`badge ${room.is_private ? "badge-warn" : ""}`}>
                    {room.is_private ? "Private" : "Open"}
                  </span>
                  {room.is_full ? <span className="badge badge-warn">Full</span> : null}
                  <button
                    className="button button-ghost"
                    onClick={() => handleQuickJoin(room.code)}
                    disabled={loading || room.is_full}
                  >
                    Join
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
