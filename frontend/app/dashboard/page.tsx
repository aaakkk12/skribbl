"use client";

import { useEffect, useState } from "react";
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

type User = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string;
  profile_completed: boolean;
};

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [friends, setFriends] = useState<FriendUser[]>([]);
  const [friendQuery, setFriendQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FriendUser[]>([]);
  const [friendError, setFriendError] = useState("");
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [invites, setInvites] = useState<IncomingInvite[]>([]);
  const [inviteLoadingId, setInviteLoadingId] = useState<number | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await apiFetch<User>("/api/auth/me/", { method: "GET" });
        if (!data.profile_completed) {
          router.push("/profile/setup");
          return;
        }
        setUser(data);
        const friendsData = await getFriends();
        setFriends(friendsData.friends || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Not authorized");
        router.push("/login");
      }
    };
    load();
  }, [router]);

  useEffect(() => {
    let active = true;
    const runSearch = async () => {
      const trimmed = friendQuery.trim();
      if (trimmed.length < 2) {
        setSearchResults([]);
        return;
      }
      try {
        const response = await searchUsers(trimmed);
        if (!active) return;
        setSearchResults(response.results || []);
      } catch (err) {
        if (!active) return;
        setFriendError(err instanceof Error ? err.message : "Search failed.");
      }
    };
    const timer = setTimeout(runSearch, 300);
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
        setInvites(response.received || []);
      } catch {
        // silent in dashboard
      }
    };
    loadInvites();
    const interval = setInterval(loadInvites, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleLogout = async () => {
    await apiFetch("/api/auth/logout/", { method: "POST" });
    router.push("/login");
  };

  const refreshFriends = async () => {
    const response = await getFriends();
    setFriends(response.friends || []);
  };

  const handleAddFriend = async (id: number) => {
    setFriendError("");
    setPendingUserId(id);
    try {
      await addFriend(id);
      await refreshFriends();
      setSearchResults((prev) =>
        prev.map((item) => (item.id === id ? { ...item, is_friend: true } : item))
      );
    } catch (err) {
      setFriendError(err instanceof Error ? err.message : "Unable to add friend.");
    } finally {
      setPendingUserId(null);
    }
  };

  const handleUnfriend = async (id: number) => {
    setFriendError("");
    setPendingUserId(id);
    try {
      await unfriend(id);
      await refreshFriends();
      setSearchResults((prev) =>
        prev.map((item) => (item.id === id ? { ...item, is_friend: false } : item))
      );
    } catch (err) {
      setFriendError(err instanceof Error ? err.message : "Unable to unfriend.");
    } finally {
      setPendingUserId(null);
    }
  };

  const handleInviteResponse = async (
    inviteId: number,
    action: "accept" | "reject"
  ) => {
    setInviteLoadingId(inviteId);
    try {
      const response = await respondRoomInvite(inviteId, action);
      setInvites((prev) => prev.filter((invite) => invite.id !== inviteId));
      if (action === "accept" && response.code) {
        router.push(`/room/${response.code}`);
      }
    } catch (err) {
      setFriendError(err instanceof Error ? err.message : "Unable to handle invite.");
    } finally {
      setInviteLoadingId(null);
    }
  };

  return (
    <main className="container">
      <section className="auth-card dashboard">
        <div className="nav-row">
          <div>
            <span className="kicker">Dashboard</span>
            <h1 className="hero-title" style={{ fontSize: "2.2rem" }}>
              {user ? `Welcome, ${user.display_name || user.first_name || user.email}` : "Welcome"}
            </h1>
          </div>
          <Link className="link" href="/">
            Home
          </Link>
        </div>
        {error ? (
          <p className="error">{error}</p>
        ) : (
          <p className="helper">
            You are signed in with a secure JWT cookie. This page is protected by
            the Django API.
          </p>
        )}
        <div className="form-actions">
          <Link className="button button-ghost" href="/rooms">
            Go to rooms
          </Link>
          <Link className="button button-ghost" href="/profile/setup">
            Edit profile
          </Link>
          <button className="button button-primary" type="button" onClick={handleLogout}>
            Log out
          </button>
        </div>
        <div className="social-grid">
          <div className="social-card">
            <h3>Find players</h3>
            <input
              value={friendQuery}
              onChange={(event) => setFriendQuery(event.target.value)}
              placeholder="Search by name or email"
              className="social-input"
            />
            <div className="social-list">
              {searchResults.length === 0 ? (
                <p className="helper">Type at least 2 characters to search.</p>
              ) : (
                searchResults.map((result) => (
                  <div key={result.id} className="social-row">
                    <div className="social-user">
                      <PlayerAvatar avatar={result.avatar} size={30} />
                      <div>
                        <strong>{result.name}</strong>
                        <p className="helper">{result.email}</p>
                      </div>
                    </div>
                    {result.is_friend ? (
                      <button
                        className="button button-ghost"
                        type="button"
                        disabled={pendingUserId === result.id}
                        onClick={() => handleUnfriend(result.id)}
                      >
                        Unfriend
                      </button>
                    ) : (
                      <button
                        className="button button-primary"
                        type="button"
                        disabled={pendingUserId === result.id}
                        onClick={() => handleAddFriend(result.id)}
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
            <h3>Friends</h3>
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
                      disabled={pendingUserId === friend.id}
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
        <div className="social-card">
          <h3>Room invites</h3>
          <div className="social-list">
            {invites.length === 0 ? (
              <p className="helper">No pending invites.</p>
            ) : (
              invites.map((invite) => (
                <div key={invite.id} className="social-row">
                  <div className="social-user">
                    <PlayerAvatar avatar={invite.from_user.avatar} size={30} />
                    <div>
                      <strong>{invite.from_user.name}</strong>
                      <p className="helper">invited you to room {invite.room_code}</p>
                    </div>
                  </div>
                  <div className="social-actions">
                    <button
                      className="button button-ghost"
                      type="button"
                      disabled={inviteLoadingId === invite.id}
                      onClick={() => handleInviteResponse(invite.id, "reject")}
                    >
                      Reject
                    </button>
                    <button
                      className="button button-primary"
                      type="button"
                      disabled={inviteLoadingId === invite.id}
                      onClick={() => handleInviteResponse(invite.id, "accept")}
                    >
                      Join
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        {friendError ? <p className="error">{friendError}</p> : null}
      </section>
    </main>
  );
}



