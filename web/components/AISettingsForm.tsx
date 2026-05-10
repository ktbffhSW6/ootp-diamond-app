"use client";

// AISettingsForm — provider/model/use-level picker + per-provider
// API-key input. Saves via POST /api/ai/settings.
//
// The api_key field is write-only — when a key is already set on the
// server we render a "Key set" pill and a "Clear" button (which posts
// `api_key: ""` to delete the keyring entry). To rotate, just type a
// new key — the post overwrites without needing a separate delete.

import { useState } from "react";
import { useRouter } from "next/navigation";

import { updateAiSettings } from "@/lib/api";
import type { AISettingsResponse } from "@/lib/types/api";

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  anthropic: [
    // Rolling aliases — survive snapshot retirements (D33 fix).
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
  ],
  openai: ["gpt-4o-mini", "gpt-4o", "gpt-4.1"],
};

const USE_LEVELS: { value: string; label: string; blurb: string }[] = [
  { value: "off", label: "Off", blurb: "All AI features hidden, no calls." },
  {
    value: "on_demand",
    label: "On-demand",
    blurb: "Click each AI feature; cost preview before every call.",
  },
  {
    value: "smart",
    label: "Smart (default)",
    blurb:
      "Auto-runs cheap inline features (chart annotations, percentile cards). Prompts before deep dossiers.",
  },
  {
    value: "always_on",
    label: "Always-on",
    blurb: "Auto-runs everything, including expensive features.",
  },
];

interface Props {
  initial: AISettingsResponse;
}

const PERSONA_PRESETS: { label: string; text: string }[] = [
  {
    label: "Default",
    text: "",
  },
  {
    label: "Terse analyst",
    text: "Be terse. Lead with the answer. Use bullet points. Skip preamble like \"I'll look up...\". One paragraph max for explanations.",
  },
  {
    label: "Hardboiled scout",
    text: "Talk like a 1970s baseball scout — gruff, direct, anecdotal. Compare players to old-timers when it fits. Don't sugarcoat. Numbers still matter, but lead with feel.",
  },
  {
    label: "Stats nerd",
    text: "Lean heavily on advanced stats. Cite specific numbers (xwOBA, FIP, RE24, leverage index) and explain what they mean. Show the math when it matters.",
  },
  {
    label: "GM coach",
    text: "Frame everything as actionable GM decisions. End every analysis with \"so here's what I'd do.\" Talk roi, opportunity cost, and contract leverage. No fluff.",
  },
];

export function AISettingsForm({ initial }: Props) {
  const router = useRouter();
  const [provider, setProvider] = useState(initial.provider);
  const [model, setModel] = useState(initial.model);
  const [useLevel, setUseLevel] = useState(initial.use_level);
  const [persona, setPersona] = useState(initial.persona ?? "");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [providers, setProviders] = useState(initial.providers);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const currentHasKey =
    providers.find((p) => p.name === provider)?.has_key ?? false;

  async function save(payload: Record<string, string | undefined>) {
    setSaving(true);
    setMessage(null);
    try {
      const next = await updateAiSettings(payload);
      setProviders(next.providers);
      setProvider(next.provider);
      setModel(next.model);
      setUseLevel(next.use_level);
      setPersona(next.persona ?? "");
      setMessage({ kind: "ok", text: "Saved." });
    } catch (e) {
      setMessage({
        kind: "err",
        text: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setSaving(false);
      router.refresh();
    }
  }

  function onSavePrefs() {
    save({ provider, model, use_level: useLevel });
  }
  function onSavePersona() {
    save({ persona });
  }
  function onSaveKey() {
    if (!apiKey) return;
    save({ provider, api_key: apiKey });
    setApiKey("");
  }
  function onClearKey() {
    save({ provider, api_key: "" });
  }

  return (
    <div className="space-y-6">
      {/* Provider + model + use level */}
      <section className="space-y-4 rounded-lg border border-border bg-surface-card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          Provider
        </h2>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                // When switching, default the model to that provider's first option.
                const list = MODELS_BY_PROVIDER[e.target.value];
                if (list && !list.includes(model)) setModel(list[0]);
              }}
              className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
            >
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
            >
              {(MODELS_BY_PROVIDER[provider] ?? [model]).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              Use level
            </label>
            <select
              value={useLevel}
              onChange={(e) =>
                setUseLevel(
                  e.target.value as
                    | "off"
                    | "on_demand"
                    | "smart"
                    | "always_on",
                )
              }
              className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
            >
              {USE_LEVELS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={onSavePrefs}
            disabled={saving}
            className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            Save
          </button>
        </div>
        <p className="text-xs text-content-muted">
          {USE_LEVELS.find((u) => u.value === useLevel)?.blurb}
        </p>
      </section>

      {/* Persona / personality */}
      <section className="space-y-4 rounded-lg border border-border bg-surface-card p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
          Personality
        </h2>
        <p className="text-xs text-content-muted">
          Free-form instructions appended to the AI sidebar&apos;s
          system prompt on every chat. Use it to set tone, format
          preferences, or domain quirks. Empty = default analyst
          voice.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {PERSONA_PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => setPersona(p.text)}
              className="rounded border border-border bg-surface-page px-2 py-1 text-xs text-content-secondary transition hover:border-accent hover:text-content-primary"
            >
              {p.label}
            </button>
          ))}
        </div>
        <textarea
          value={persona}
          onChange={(e) => setPersona(e.target.value)}
          rows={6}
          placeholder="e.g. Be terse. Lead with the answer. Use bullet points. Cite specific numbers."
          className="w-full resize-y rounded border border-border bg-surface-page px-3 py-2 font-mono text-xs text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSavePersona}
            disabled={saving}
            className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            Save personality
          </button>
          {persona && (
            <button
              type="button"
              onClick={() => {
                setPersona("");
                save({ persona: "" });
              }}
              disabled={saving}
              className="rounded border border-rose-500/50 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-500/10 dark:text-rose-400"
            >
              Clear
            </button>
          )}
          <span className="text-xs text-content-muted">
            {persona.length} chars
          </span>
        </div>
      </section>

      {/* API key */}
      <section className="space-y-4 rounded-lg border border-border bg-surface-card p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-content-secondary">
            API key — {provider}
          </h2>
          {currentHasKey ? (
            <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-500/25 dark:text-emerald-300">
              Key set
            </span>
          ) : (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/25 dark:text-amber-300">
              Key missing
            </span>
          )}
        </div>
        <p className="text-xs text-content-muted">
          Stored in the OS keyring (Windows Credential Manager / macOS Keychain
          / Linux Secret Service). The API never returns the key once
          saved.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[280px]">
            <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
              {currentHasKey ? "Replace key" : "Paste key"}
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={currentHasKey ? "•••••••• (leave empty to keep)" : `${provider}-...`}
              className="w-full rounded border border-border bg-surface-page px-3 py-1.5 font-mono text-sm text-content-primary"
            />
          </div>
          <button
            onClick={onSaveKey}
            disabled={saving || !apiKey}
            className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            Save key
          </button>
          {currentHasKey && (
            <button
              onClick={onClearKey}
              disabled={saving}
              className="rounded border border-rose-500/50 px-4 py-1.5 text-sm font-semibold text-rose-600 hover:bg-rose-500/10 dark:text-rose-400"
            >
              Clear
            </button>
          )}
        </div>
      </section>

      {message && (
        <div
          className={`rounded border px-3 py-2 text-sm ${
            message.kind === "ok"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300"
          }`}
        >
          {message.text}
        </div>
      )}
    </div>
  );
}
