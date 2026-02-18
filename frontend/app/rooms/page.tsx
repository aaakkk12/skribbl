"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  addFriend,
  apiFetch,
  getFriends,
  listRoomInvites,
  respondRoomInvite,
  searchUsers,
  unfriend,
  type FriendUser,
  type IncomingInvite,
} from "../../lib/api";
import PlayerAvatar from "../../components/PlayerAvatar";

type RoomSummary = {
  code: string;
  active_count: number;
  max_players: number;
  is_full: boolean;
  is_private: boolean;
};

type MeResponse = {
  profile_completed: boolean;
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
  const [incomingInvites, setIncomingInvites] = useState<IncomingInvite[]>([]);
  const [inviteLoadingId, setInviteLoadingId] = useState<number | null>(null);
  const [friendQuery, setFriendQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FriendUser[]>([]);
  const [friends, setFriends] = useState<FriendUser[]>([]);
  const [friendLoadingId, setFriendLoadingId] = useState<number | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttempts = useRef(0);
  const lobbySocket = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ensureAuth = async () => {
      try {
        const me = await apiFetch<MeResponse>("/api/auth/me/", { method: "GET" });
        if (!me.profile_completed) {
          router.push("/profile/setup");
          return;
        }
        const friendResponse = await getFriends();
        setFriends(friendResponse.friends || []);
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
    let active = true;
    const runSearch = async () => {
      const term = friendQuery.trim();
      if (term.length < 2) {
        setSearchResults([]);
        return;
      }
      try {
        const response = await searchUsers(term);
        if (!active) return;
        setSearchResults(response.results || []);
      } catch {
        if (!active) return;
        setSearchResults([]);
      }
    };
    const timer = setTimeout(runSearch, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [friendQuery]);

  useEffect(() => {
    let mounted = true;
    const loadInvites = async () => {
      try {
        const response = await listRoomInvites();
        if (!mounted) return;
        setIncomingInvites(response.received || []);
      } catch {
        // ignore silently
      }
    };
    loadInvites();
    const interval = setInterval(loadInvites, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
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

  const handleInviteAction = async (inviteId: number, action: "accept" | "reject") => {
    setInviteLoadingId(inviteId);
    setError("");
    try {
      const response = await respondRoomInvite(inviteId, action);
      setIncomingInvites((prev) => prev.filter((invite) => invite.id !== inviteId));
      if (action === "accept" && response.code) {
        router.push(`/room/${response.code}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to handle invite.");
    } finally {
      setInviteLoadingId(null);
    }
  };

  const refreshFriends = async () => {
    const response = await getFriends();
    setFriends(response.friends || []);
  };

  const handleAddFriend = async (userId: number) => {
    setError("");
    setFriendLoadingId(userId);
    try {
      await addFriend(userId);
      await refreshFriends();
      setSearchResults((prev) =>
        prev.map((item) => (item.id === userId ? { ...item, is_friend: true } : item))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add friend.");
    } finally {
      setFriendLoadingId(null);
    }
  };

  const handleUnfriend = async (userId: number) => {
    setError("");
    setFriendLoadingId(userId);
    try {
      await unfriend(userId);
      await refreshFriends();
      setSearchResults((prev) =>
        prev.map((item) => (item.id === userId ? { ...item, is_friend: false } : item))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to unfriend.");
    } finally {
      setFriendLoadingId(null);
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
        <div className="social-grid">
          <div className="social-card">
            <h3>Search players</h3>
            <input
              className="social-input"
              value={friendQuery}
              onChange={(event) => setFriendQuery(event.target.value)}
              placeholder="Search by name or email"
            />
            <div className="social-list">
              {searchResults.length === 0 ? (
                <p className="helper">Type at least 2 characters to search.</p>
              ) : (
                searchResults.map((user) => (
                  <div key={user.id} className="social-row">
                    <div className="social-user">
                      <PlayerAvatar avatar={user.avatar} size={30} />
                      <div>
                        <strong>{user.name}</strong>
                        <p className="helper">{user.email}</p>
                      </div>
                    </div>
                    {user.is_friend ? (
                      <button
                        className="button button-ghost"
                        type="button"
                        disabled={friendLoadingId === user.id}
                        onClick={() => handleUnfriend(user.id)}
                      >
                        Unfriend
                      </button>
                    ) : (
                      <button
                        className="button button-primary"
                        type="button"
                        disabled={friendLoadingId === user.id}
                        onClick={() => handleAddFriend(user.id)}
                      >
                        Add friend
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
          <div className="social-card">
            <h3>My friends</h3>
            <div className="social-list">
              {friends.length === 0 ? (
                <p className="helper">No friends yet.</p>
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
                      className="button button-ghost"
                      type="button"
                      disabled={friendLoadingId === friend.id}
                      onClick={() => handleUnfriend(friend.id)}
                    >
                      Unfriend
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
        {error ? <p className="error">{error}</p> : null}
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
                    disabled={inviteLoadingId === invite.id}
                    onClick={() => handleInviteAction(invite.id, "reject")}
                  >
                    Reject
                  </button>
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={inviteLoadingId === invite.id}
                    onClick={() => handleInviteAction(invite.id, "accept")}
                  >
                    Join
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
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
