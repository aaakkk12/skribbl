"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../../lib/api";

type AdminRoom = {
  code: string;
  is_private: boolean;
  active_count: number;
  max_players: number;
};

type AdminUser = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  last_login: string | null;
  is_active: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  is_banned: boolean;
  is_deleted: boolean;
};

export default function AdminPage() {
  const [isAuthed, setIsAuthed] = useState(false);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [rooms, setRooms] = useState<AdminRoom[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [resetEmail, setResetEmail] = useState("");
  const [roomPasswords, setRoomPasswords] = useState<Record<string, string>>({});
  const [userFilter, setUserFilter] = useState<"active" | "archived">("active");

  const loadRooms = async () => {
    const response = await apiFetch<{ rooms: AdminRoom[] }>("/api/admin/rooms/", {
      method: "GET",
    });
    setRooms(response.rooms || []);
  };

  const loadUsers = async () => {
    const response = await apiFetch<{ users: AdminUser[] }>("/api/admin/users/", {
      method: "GET",
    });
    setUsers(response.users || []);
  };

  useEffect(() => {
    const bootstrap = async () => {
      try {
        await apiFetch("/api/admin/me/", { method: "GET" });
        setIsAuthed(true);
        await loadRooms();
        await loadUsers();
      } catch {
        setIsAuthed(false);
      }
    };
    bootstrap();
  }, []);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await apiFetch("/api/admin/login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setIsAuthed(true);
      setPassword("");
      await loadRooms();
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Admin login failed");
    }
  };

  const handleLogout = async () => {
    await apiFetch("/api/admin/logout/", { method: "POST" });
    setIsAuthed(false);
  };

  const handleRoomToggle = async (code: string, nextPrivate: boolean) => {
    setError("");
    try {
      let password = roomPasswords[code] || "";
      if (nextPrivate && !password) {
        password = window.prompt("Set password for private room") || "";
        if (!password) {
          setError("Password is required to make room private.");
          return;
        }
      }
      await apiFetch(`/api/admin/rooms/${code}/`, {
        method: "PATCH",
        body: JSON.stringify({
          is_private: nextPrivate,
          password,
        }),
      });
      await loadRooms();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update room");
    }
  };

  const handleDeleteRoom = async (code: string) => {
    setError("");
    try {
      await apiFetch(`/api/admin/rooms/${code}/`, { method: "DELETE" });
      await loadRooms();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete room");
    }
  };

  const handleReset = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    try {
      await apiFetch("/api/admin/users/reset-password/", {
        method: "POST",
        body: JSON.stringify({ email: resetEmail }),
      });
      setSuccess("Reset link sent.");
      setResetEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send reset link");
    }
  };

  const handleResetFor = async (email: string) => {
    setError("");
    setSuccess("");
    try {
      await apiFetch("/api/admin/users/reset-password/", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSuccess(`Reset link sent to ${email}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send reset link");
    }
  };

  const handleUserAction = async (userId: number, action: string) => {
    setError("");
    setSuccess("");
    try {
      await apiFetch(`/api/admin/users/${userId}/action/`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      await loadUsers();
      setSuccess("User updated.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update user");
    }
  };

  if (!isAuthed) {
    return (
      <main className="container">
        <section className="auth-card">
          <div className="nav-row">
            <div>
              <span className="kicker">Admin</span>
              <h1 className="hero-title" style={{ fontSize: "2.4rem" }}>
                Admin control panel
              </h1>
            </div>
          </div>
          <form onSubmit={handleLogin} className="field" style={{ gap: "1rem" }}>
            <div className="field">
              <label>Username</label>
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
            <div className="field">
              <label>Password</label>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            {error ? <p className="error">{error}</p> : null}
            <button className="button button-primary" type="submit">
              Sign in
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="container">
      <section className="auth-card dashboard">
        <div className="nav-row">
          <div>
            <span className="kicker">Admin</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              Room control center
            </h1>
          </div>
          <button className="button button-ghost" type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
        {success ? <p className="success">{success}</p> : null}

        <div className="admin-section">
          <h3>Send password reset</h3>
          <form onSubmit={handleReset} className="room-join">
            <input
              value={resetEmail}
              onChange={(event) => setResetEmail(event.target.value)}
              placeholder="user@email.com"
              type="email"
              required
            />
            <button className="button button-primary" type="submit">
              Send link
            </button>
          </form>
        </div>

        <div className="admin-section">
          <h3>Rooms</h3>
          <div className="room-list">
            {rooms.length === 0 ? (
              <p className="helper">No rooms found.</p>
            ) : (
              rooms.map((room) => (
                <div key={room.code} className="room-card admin-room-card">
                  <div>
                    <span className="kicker">Room {room.code}</span>
                    <p className="helper">
                      {room.active_count}/{room.max_players} players
                    </p>
                  </div>
                  <div className="admin-room-actions">
                    <span className={`badge ${room.is_private ? "badge-warn" : ""}`}>
                      {room.is_private ? "Private" : "Open"}
                    </span>
                    {room.is_private ? (
                      <input
                        className="room-password"
                        type="password"
                        placeholder="New password"
                        value={roomPasswords[room.code] || ""}
                        onChange={(event) =>
                          setRoomPasswords((prev) => ({
                            ...prev,
                            [room.code]: event.target.value,
                          }))
                        }
                      />
                    ) : null}
                    <button
                      className="button button-ghost"
                      onClick={() => handleRoomToggle(room.code, !room.is_private)}
                    >
                      {room.is_private ? "Make open" : "Make private"}
                    </button>
                    <button
                      className="button button-primary"
                      onClick={() => handleDeleteRoom(room.code)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="admin-section">
          <h3>Users</h3>
          <div className="admin-toolbar">
            <button
              className={`button button-ghost ${userFilter === "active" ? "button-active" : ""}`}
              onClick={() => setUserFilter("active")}
            >
              Active
            </button>
            <button
              className={`button button-ghost ${userFilter === "archived" ? "button-active" : ""}`}
              onClick={() => setUserFilter("archived")}
            >
              Archived
            </button>
          </div>
          <div className="room-list">
            {users.length === 0 ? (
              <p className="helper">No users found.</p>
            ) : (
              users
                .filter((user) =>
                  userFilter === "archived" ? user.is_deleted : !user.is_deleted
                )
                .map((user) => (
                  <div key={user.id} className="room-card admin-room-card">
                    <div>
                      <span className="kicker">User #{user.id}</span>
                      <h3>{user.email}</h3>
                      <p className="helper">
                        {user.first_name || user.last_name
                          ? `${user.first_name} ${user.last_name}`.trim()
                          : "No name"}
                      </p>
                    </div>
                    <div className="admin-room-actions">
                      <span className={`badge ${user.is_banned ? "badge-warn" : ""}`}>
                        {user.is_banned ? "Banned" : "Active"}
                      </span>
                      {user.is_superuser ? (
                        <span className="badge">Superuser</span>
                      ) : user.is_staff ? (
                        <span className="badge">Staff</span>
                      ) : null}
                      {!user.is_deleted ? (
                        <>
                          <button
                            className="button button-ghost"
                            onClick={() => handleResetFor(user.email)}
                          >
                            Reset link
                          </button>
                          <button
                            className="button button-ghost"
                            onClick={() =>
                              handleUserAction(user.id, user.is_banned ? "unban" : "ban")
                            }
                          >
                            {user.is_banned ? "Unban" : "Ban"}
                          </button>
                          <button
                            className="button button-primary"
                            onClick={() => handleUserAction(user.id, "delete")}
                          >
                            Archive
                          </button>
                        </>
                      ) : (
                        <button
                          className="button button-ghost"
                          onClick={() => handleUserAction(user.id, "restore")}
                        >
                          Restore
                        </button>
                      )}
                    </div>
                  </div>
                ))
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
