"use client";

import type { CSSProperties } from "react";

export type AvatarConfig = {
  color: string;
  eyes: "dot" | "happy" | "sleepy";
  mouth: "smile" | "flat" | "open";
  accessory: "none" | "cap" | "crown" | "glasses";
};

const DEFAULT_AVATAR: AvatarConfig = {
  color: "#5eead4",
  eyes: "dot",
  mouth: "smile",
  accessory: "none",
};

export default function PlayerAvatar({
  avatar,
  size = 40,
  className = "",
}: {
  avatar?: Partial<AvatarConfig>;
  size?: number;
  className?: string;
}) {
  const merged: AvatarConfig = {
    ...DEFAULT_AVATAR,
    ...(avatar || {}),
  };

  return (
    <div
      className={`player-avatar ${className}`.trim()}
      style={
        {
          width: size,
          height: size,
          "--avatar-color": merged.color,
        } as CSSProperties
      }
    >
      <div className="avatar-head">
        <span className={`avatar-eye avatar-eye-left avatar-eye-${merged.eyes}`} />
        <span className={`avatar-eye avatar-eye-right avatar-eye-${merged.eyes}`} />
        <span className={`avatar-mouth avatar-mouth-${merged.mouth}`} />
        {merged.accessory === "glasses" ? <span className="avatar-glasses" /> : null}
      </div>
      {merged.accessory === "cap" ? <span className="avatar-cap" /> : null}
      {merged.accessory === "crown" ? <span className="avatar-crown" /> : null}
    </div>
  );
}
