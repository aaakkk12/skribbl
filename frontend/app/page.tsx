"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import PlayerAvatar, { type AvatarConfig } from "../components/PlayerAvatar";
import {
  createGuestSession,
  type GuestCharacter,
} from "../lib/api";

type CharacterOption = {
  id: GuestCharacter;
  label: string;
  tagline: string;
  avatar: AvatarConfig;
};

type StoredProfile = {
  username: string;
  character: GuestCharacter;
};

const STORAGE_KEY = "drawing_guest_profile_v1";

const CHARACTER_OPTIONS: CharacterOption[] = [
  {
    id: "sprinter",
    label: "Sprinter",
    tagline: "Fast starter",
    avatar: { color: "#5eead4", eyes: "dot", mouth: "smile", accessory: "none" },
  },
  {
    id: "captain",
    label: "Captain",
    tagline: "Team caller",
    avatar: { color: "#1d4ed8", eyes: "happy", mouth: "smile", accessory: "cap" },
  },
  {
    id: "vision",
    label: "Vision",
    tagline: "Sharp guesser",
    avatar: { color: "#8b5cf6", eyes: "happy", mouth: "open", accessory: "glasses" },
  },
  {
    id: "joker",
    label: "Joker",
    tagline: "Fun rounds",
    avatar: { color: "#f97316", eyes: "happy", mouth: "open", accessory: "none" },
  },
  {
    id: "royal",
    label: "Royal",
    tagline: "Big winner",
    avatar: { color: "#f59e0b", eyes: "dot", mouth: "smile", accessory: "crown" },
  },
  {
    id: "ninja",
    label: "Ninja",
    tagline: "Silent sniper",
    avatar: { color: "#334155", eyes: "sleepy", mouth: "flat", accessory: "none" },
  },
];

export default function Home() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [character, setCharacter] = useState<GuestCharacter>("sprinter");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedCharacter = useMemo(
    () => CHARACTER_OPTIONS.find((item) => item.id === character) || CHARACTER_OPTIONS[0],
    [character]
  );

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<StoredProfile>;
      if (typeof parsed.username === "string") {
        setUsername(parsed.username);
      }
      if (typeof parsed.character === "string") {
        const found = CHARACTER_OPTIONS.some((item) => item.id === parsed.character);
        if (found) {
          setCharacter(parsed.character as GuestCharacter);
        }
      }
    } catch {
      // ignore local storage parsing errors
    }
  }, []);

  const handleContinue = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    const trimmed = username.trim();
    if (trimmed.length < 2) {
      setError("Username must be at least 2 characters.");
      return;
    }

    setLoading(true);
    try {
      await createGuestSession({
        username: trimmed,
        character,
      });
      const payload: StoredProfile = {
        username: trimmed,
        character,
      };
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      }
      router.push("/rooms");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to continue.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <section className="auth-card onboarding-shell">
        <div className="onboarding-header">
          <span className="badge">Online Drawing Game</span>
          <h1 className="hero-title" style={{ fontSize: "2.4rem" }}>
            Choose your character
          </h1>
          <p className="helper">
            Set your username, pick a character, and enter the room lobby directly.
          </p>
        </div>

        <form className="onboarding-form" onSubmit={handleContinue}>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="Enter your username"
              maxLength={24}
              autoComplete="off"
              required
            />
          </div>

          <div className="field">
            <label>Character</label>
            <div className="character-grid">
              {CHARACTER_OPTIONS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`character-card ${character === item.id ? "active" : ""}`}
                  onClick={() => setCharacter(item.id)}
                >
                  <PlayerAvatar avatar={item.avatar} size={54} />
                  <div>
                    <strong>{item.label}</strong>
                    <p>{item.tagline}</p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="onboarding-footer">
            <div className="selected-preview">
              <PlayerAvatar avatar={selectedCharacter.avatar} size={44} />
              <span>
                Ready as <strong>{selectedCharacter.label}</strong>
              </span>
            </div>
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Joining..." : "Next"}
            </button>
          </div>
          {error ? <p className="error">{error}</p> : null}
        </form>
      </section>
    </main>
  );
}
