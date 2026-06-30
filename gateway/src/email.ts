import { Resend } from "resend";
import { requireEnv } from "./env.js";

const resend = new Resend(requireEnv("RESEND_API_KEY"));
const FROM_ADDRESS = process.env.RESEND_FROM_ADDRESS ?? "onboarding@levelupseon.com";

export async function sendVerificationEmail(email: string, code: string): Promise<void> {
  await resend.emails.send({
    from: `SentiTrack <${FROM_ADDRESS}>`,
    to: email,
    subject: "SentiTrack 이메일 인증 코드",
    html: `
      <div style="font-family: sans-serif; padding: 24px;">
        <h2 style="margin: 0 0 16px;">SentiTrack 이메일 인증</h2>
        <p>아래 인증 코드를 입력해주세요. 코드는 10분간 유효합니다.</p>
        <p style="font-size: 28px; font-weight: 700; letter-spacing: 4px; margin: 24px 0;">
          ${code}
        </p>
      </div>
    `,
  });
}
