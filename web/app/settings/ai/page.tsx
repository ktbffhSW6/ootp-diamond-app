// AI settings page (D14).
//
// URL: /settings/ai
//
// Server component fetches current settings; client form posts updates.
// The form's API-key field is write-only — when a key is set, the GET
// reports `has_key: true` and we render a "Key set" pill instead of
// echoing the secret.

import { AISettingsForm } from "@/components/AISettingsForm";
import { getAiSettings } from "@/lib/api";

export const metadata = { title: "AI Settings — Diamond" };
export const dynamic = "force-dynamic";

export default async function AiSettingsPage() {
  const settings = await getAiSettings();
  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">AI Settings</h1>
        <p className="mt-1 text-sm text-content-secondary">
          Diamond&apos;s AI features (summaries, anomaly flags, monthly
          reviews) call your chosen provider directly with the key
          stored in the OS keyring. Keys never leave your machine
          unencrypted; the API never echoes them back.
        </p>
      </header>
      <AISettingsForm initial={settings} />
    </div>
  );
}
