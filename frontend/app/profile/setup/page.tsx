"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "../../../lib/api";
import PlayerAvatar, { type AvatarConfig } from "../../../components/PlayerAvatar";

type MeResponse = {
  id: number;
  email: string;
  display_name: string;
  profile_completed: boolean;
  avatar: AvatarConfig;
};

type ProfileResponse = {
  display_name: string;
  avatar_color: string;
  avatar_eyes: AvatarConfig["eyes"];
  avatar_mouth: AvatarConfig["mouth"];
  avatar_accessory: AvatarConfig["accessory"];
};

const DEFAULT_PROFILE: ProfileResponse = {
  display_name: "",
  avatar_color: "#5eead4",
  avatar_eyes: "dot",
  avatar_mouth: "smile",
  avatar_accessory: "none",
};

export default function ProfileSetupPage() {
  const router = useRouter();
  const [profile, setProfile] = useState<ProfileResponse>(DEFAULT_PROFILE);
  const [loading, setLoading] = useState(false);
  const [bootLoading, setBootLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const boot = async () => {
      try {
        await apiFetch<MeResponse>("/api/auth/me/", { method: "GET" });
        const data = await apiFetch<ProfileResponse>("/api/auth/profile/", { method: "GET" });
        setProfile({
          ...DEFAULT_PROFILE,
          ...data,
        });
      } catch {
        router.push("/login");
        return;
      } finally {
        setBootLoading(false);
      }
    };
    boot();
  }, [router]);

  const avatarPreview = useMemo(
    () => ({
      color: profile.avatar_color,
      eyes: profile.avatar_eyes,
      mouth: profile.avatar_mouth,
      accessory: profile.avatar_accessory,
    }),
    [profile]
  );

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await apiFetch("/api/auth/profile/", {
        method: "PUT",
        body: JSON.stringify(profile),
      });
      router.push("/rooms");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setLoading(false);
    }
  };

  if (bootLoading) {
    return (
      <main className="container auth-shell">
        <section className="auth-card auth-card-form">
          <p className="helper">Loading profile...</p>
        </section>
      </main>
    );
  }

  return (
    <main className="container auth-shell">
      <section className="auth-card auth-card-form">
        <div>
          <span className="kicker">Player Setup</span>
          <h1 className="hero-title" style={{ fontSize: "2.1rem" }}>
            Create your player
          </h1>
          <p className="helper">
            This name and avatar will be shown in room and leaderboard.
          </p>
        </div>

        <form onSubmit={onSubmit} className="profile-builder">
          <div className="profile-preview">
            <PlayerAvatar avatar={avatarPreview} size={92} />
            <strong>{profile.display_name || "Player"}</strong>
          </div>

          <div className="field">
            <label htmlFor="display-name">Player name</label>
            <input
              id="display-name"
              value={profile.display_name}
              onChange={(event) =>
                setProfile((prev) => ({ ...prev, display_name: event.target.value }))
              }
              placeholder="Enter your player name"
              maxLength={32}
              required
            />
          </div>

          <div className="profile-grid">
            <div className="field">
              <label htmlFor="avatar-color">Color</label>
              <input
                id="avatar-color"
                type="color"
                value={profile.avatar_color}
                onChange={(event) =>
                  setProfile((prev) => ({ ...prev, avatar_color: event.target.value }))
                }
              />
            </div>
            <div className="field">
              <label htmlFor="avatar-eyes">Eyes</label>
              <select
                id="avatar-eyes"
                value={profile.avatar_eyes}
                onChange={(event) =>
                  setProfile((prev) => ({
                    ...prev,
                    avatar_eyes: event.target.value as AvatarConfig["eyes"],
                  }))
                }
              >
                <option value="dot">Dot</option>
                <option value="happy">Happy</option>
                <option value="sleepy">Sleepy</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="avatar-mouth">Mouth</label>
              <select
                id="avatar-mouth"
                value={profile.avatar_mouth}
                onChange={(event) =>
                  setProfile((prev) => ({
                    ...prev,
                    avatar_mouth: event.target.value as AvatarConfig["mouth"],
                  }))
                }
              >
                <option value="smile">Smile</option>
                <option value="flat">Flat</option>
                <option value="open">Open</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="avatar-accessory">Accessory</label>
              <select
                id="avatar-accessory"
                value={profile.avatar_accessory}
                onChange={(event) =>
                  setProfile((prev) => ({
                    ...prev,
                    avatar_accessory: event.target.value as AvatarConfig["accessory"],
                  }))
                }
              >
                <option value="none">None</option>
                <option value="cap">Cap</option>
                <option value="crown">Crown</option>
                <option value="glasses">Glasses</option>
              </select>
            </div>
          </div>

          {error ? <p className="error">{error}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={loading}>
              {loading ? "Saving..." : "Save and Continue"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
