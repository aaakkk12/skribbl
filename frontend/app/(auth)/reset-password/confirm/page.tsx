import { Suspense } from "react";
import ResetPasswordConfirmClient from "./ResetPasswordConfirmClient";

export default function ResetPasswordConfirmPage() {
  return (
    <Suspense fallback={<div className="auth-card">Loading...</div>}>
      <ResetPasswordConfirmClient />
    </Suspense>
  );
}