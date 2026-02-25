"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, resolveWsBaseUrl } from "../../lib/api";

type RoomSummary = {
  code: string;
  active_count: number;
  max_players: number;
  is_full: boolean;
  is_private: boolean;
};

type MeResponse = {
  display_name: string;
  first_name: string;
};

export default function RoomsPage() {
  const router = useRouter();
  const [name, setName] = useState("Player");
  const [sessionReady, setSessionReady] = useState(false);
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
    const ensureSession = async () => {
      try {
        const me = await apiFetch<MeResponse>("/api/auth/me/", { method: "GET" });
        setName(me.display_name || me.first_name || "Player");
        setSessionReady(true);
      } catch {
        router.push("/");
      }
    };
    ensureSession();
  }, [router]);

  useEffect(() => {
    if (!sessionReady) {
      return;
    }
    const fetchRooms = async () => {
      try {
        const response = await apiFetch<{ rooms: RoomSummary[] }>("/api/rooms/list/", {
          method: "GET",
        });
        setRooms(response.rooms || []);
      } catch {
        // websocket will retry updates
      }
    };
    fetchRooms();
  }, [sessionReady]);

  useEffect(() => {
    if (!sessionReady) {
      return;
    }
    let shouldReconnect = true;

    const connectLobby = () => {
      if (lobbySocket.current && lobbySocket.current.readyState === WebSocket.OPEN) {
        return;
      }

      const socket = new WebSocket(`${resolveWsBaseUrl()}/ws/lobby/`);
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
  }, [sessionReady]);

  const handleCreate = async () => {
    setError("");
    if (visibility === "private" && !createPassword.trim()) {
      setError("Private room ke liye password required hai.");
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
      setError(err instanceof Error ? err.message : "Unable to create room.");
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
      setError(err instanceof Error ? err.message : "Unable to join room.");
    } finally {
      setLoading(false);
    }
  };

  const handleRandomJoin = async () => {
    setError("");
    setLoading(true);
    try {
      const response = await apiFetch<{ code: string }>("/api/rooms/join-random/", {
        method: "POST",
      });
      router.push(`/room/${response.code}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No random room available right now.");
    } finally {
      setLoading(false);
    }
  };

  const handleQuickJoin = async (roomCode: string, isPrivate: boolean) => {
    setError("");
    setLoading(true);
    try {
      let password = "";
      if (isPrivate) {
        password = window.prompt(`Room ${roomCode} password enter karo`) || "";
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
      setError(err instanceof Error ? err.message : "Unable to join room.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="auth-card">
        <div className="nav-row">
          <div>
            <span className="kicker">Welcome {name}</span>
            <h1 className="hero-title" style={{ fontSize: "2.3rem" }}>
              Room Lobby
            </h1>
          </div>
        </div>

        <div className="room-actions-grid">
          <div className="room-card-lite">
            <div className="room-card-head">
              <h3>Create room</h3>
              <span className="helper">Open ya private choose karo</span>
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
              <button className="button button-primary" onClick={handleCreate} disabled={loading}>
                {loading ? "Working..." : "Create room"}
              </button>
            </div>
          </div>

          <div className="room-card-lite">
            <div className="room-card-head">
              <h3>Join room</h3>
              <span className="helper">Code paste karo aur join karo</span>
            </div>
            <form onSubmit={handleJoin} className="room-join">
              <input
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                placeholder="Enter room code"
                maxLength={8}
                required
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

        <div className="random-room-row">
          <button className="button button-primary" type="button" onClick={handleRandomJoin} disabled={loading}>
            Join Random Room
          </button>
          <span className="helper">Sirf joinable public rooms me random pick hota hai.</span>
        </div>

        {error ? <p className="error">{error}</p> : null}

        <div className="room-list-header">
          <span className={`status-dot status-${lobbyStatus}`} />
          <span className="helper">Live rooms</span>
        </div>
        <div className="room-list">
          {rooms.length === 0 ? (
            <p className="helper">No Rooms active.</p>
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
                    onClick={() => handleQuickJoin(room.code, room.is_private)}
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
