"use client";

// SaveSwitcher — list of available saves with per-save Configure +
// Make-active flow.
//
// Each card surfaces three orthogonal pieces of state:
//   - **Active** badge — green pill, only one save at a time
//   - **Needs ingest** badge — amber pill if no diamond.duckdb yet
//   - **Configured / Not configured** badge — sky pill if the user
//     has run the configure wizard (audit_team_id + scope persisted)
//
// Action buttons:
//   - **Configure** — opens the inline ConfigureForm; required before
//     Make-active is enabled. Form fetches the 30-team picker catalog
//     + existing config from /api/saves/{name}/config and POSTs the
//     user's pick back. When the active save is reconfigured, the
//     server refreshes its in-memory SaveConfig so org-scoped pages
//     pick up the new audit_team_id immediately.
//   - **Make active** — disabled when not configured; POSTs to
//     /api/saves/active. Refused server-side with 409 if config is
//     missing (defense in depth).

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getSaveConfig, setActiveSave, setSaveConfig } from "@/lib/api";
import type {
  MlbTeamOption,
  SaveConfigResponse,
  SavesListResponse,
  SaveSummaryDto,
} from "@/lib/types/api";

interface Props {
  initial: SavesListResponse;
}

export function SaveSwitcher({ initial }: Props) {
  const router = useRouter();
  const [data, setData] = useState(initial);
  const [pending, setPending] = useState<string | null>(null);
  const [configuringName, setConfiguringName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pick(name: string) {
    setPending(name);
    setError(null);
    try {
      const next = await setActiveSave(name);
      setData(next);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  async function refreshSavesList() {
    // After a configure write the saves list needs a refresh — the
    // is_configured flag flips for the just-configured save. We refetch
    // via the /api/saves endpoint indirectly (router.refresh re-renders
    // the server-component shell, which re-calls getSaves).
    router.refresh();
  }

  if (data.saves.length === 0) {
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-5 text-sm text-amber-700 dark:text-amber-300">
        No saves found under{" "}
        <code className="font-mono text-xs">{data.saves_root}</code>.
        Make sure OOTP is installed and you have at least one save
        (look for a <code>*.lg</code> folder).
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {data.saves.map((s) => (
        <SaveCard
          key={s.name}
          save={s}
          pending={pending === s.name}
          configuring={configuringName === s.name}
          onPick={pick}
          onConfigureOpen={() => setConfiguringName(s.name)}
          onConfigureClose={() => setConfiguringName(null)}
          onConfigureSaved={refreshSavesList}
        />
      ))}
      {error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}
    </div>
  );
}

function SaveCard({
  save,
  pending,
  configuring,
  onPick,
  onConfigureOpen,
  onConfigureClose,
  onConfigureSaved,
}: {
  save: SaveSummaryDto;
  pending: boolean;
  configuring: boolean;
  onPick: (name: string) => void;
  onConfigureOpen: () => void;
  onConfigureClose: () => void;
  onConfigureSaved: () => void;
}) {
  const lastModified = save.last_modified
    ? new Date(save.last_modified * 1000).toLocaleString()
    : "—";

  const canActivate = !save.is_active && save.is_configured;

  return (
    <div
      className={`rounded-lg border p-4 ${
        save.is_active
          ? "border-accent bg-accent/5"
          : "border-border bg-surface-card"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-content-primary">
              {save.name}
            </span>
            {save.is_active && (
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-500/25 dark:text-emerald-300">
                Active
              </span>
            )}
            {save.is_configured ? (
              <span
                className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs font-medium text-sky-700 dark:bg-sky-500/25 dark:text-sky-300"
                title="audit_team_id + scope persisted"
              >
                Configured
              </span>
            ) : (
              <span
                className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/25 dark:text-amber-300"
                title="Pick your team before activating"
              >
                Not configured
              </span>
            )}
            {!save.has_warehouse && (
              <span
                className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-500/25 dark:text-amber-300"
                title="Run `diamond ingest --save <name>` in your terminal to build the warehouse for this save."
              >
                Needs ingest
              </span>
            )}
          </div>
          <div className="mt-1 truncate text-xs text-content-muted">
            {save.path}
          </div>
          <div className="text-xs text-content-muted">
            Last modified: {lastModified}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={configuring ? onConfigureClose : onConfigureOpen}
            className="rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-secondary hover:border-border-strong"
          >
            {configuring ? "Cancel" : save.is_configured ? "Edit" : "Configure"}
          </button>
          {!save.is_active && (
            <button
              onClick={() => onPick(save.name)}
              disabled={pending || !canActivate}
              className="rounded bg-accent px-3 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
              title={
                save.is_configured
                  ? undefined
                  : "Run Configure first to pick your team"
              }
            >
              {pending ? "Switching…" : "Make active"}
            </button>
          )}
        </div>
      </div>

      {configuring && (
        <ConfigureForm
          saveName={save.name}
          onSaved={() => {
            onConfigureClose();
            onConfigureSaved();
          }}
        />
      )}
    </div>
  );
}

function ConfigureForm({
  saveName,
  onSaved,
}: {
  saveName: string;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<SaveConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pickedTeamId, setPickedTeamId] = useState<number | null>(null);
  const [refScope, setRefScope] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load current config + picker catalog on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const c = await getSaveConfig(saveName);
        if (cancelled) return;
        setConfig(c);
        setPickedTeamId(
          c.audit_team_id ?? c.suggested_team?.team_id ?? null,
        );
        setRefScope(c.reference_scope_enabled);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [saveName]);

  async function save() {
    if (pickedTeamId === null) {
      setError("Pick a team first.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await setSaveConfig(saveName, {
        audit_team_id: pickedTeamId,
        reference_scope_enabled: refScope,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading || !config) {
    return (
      <div className="mt-4 rounded border border-border bg-surface-elevated p-3 text-xs text-content-muted">
        Loading picker…
      </div>
    );
  }

  // Group teams by division for the dropdown so the user finds their
  // team faster than scanning a flat alphabetical list of 30.
  const grouped = config.mlb_team_options.reduce<
    Record<string, MlbTeamOption[]>
  >((acc, t) => {
    if (!acc[t.division]) acc[t.division] = [];
    acc[t.division].push(t);
    return acc;
  }, {});
  const divisionOrder = [
    "AL East",
    "AL Central",
    "AL West",
    "NL East",
    "NL Central",
    "NL West",
  ];

  return (
    <div className="mt-4 space-y-4 rounded border border-border bg-surface-elevated p-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">
        Configure save
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-[260px] flex-1">
          <label className="mb-1 block text-xs uppercase tracking-wide text-content-muted">
            Your team (audit_team_id)
          </label>
          <select
            value={pickedTeamId ?? ""}
            onChange={(e) =>
              setPickedTeamId(e.target.value ? Number(e.target.value) : null)
            }
            className="w-full rounded border border-border bg-surface-page px-3 py-1.5 text-sm text-content-primary"
          >
            <option value="">— pick your team —</option>
            {divisionOrder.map(
              (div) =>
                grouped[div] && (
                  <optgroup key={div} label={div}>
                    {grouped[div].map((t) => (
                      <option key={t.team_id} value={t.team_id}>
                        {t.abbr} · {t.city} {t.name}
                      </option>
                    ))}
                  </optgroup>
                ),
            )}
          </select>
          <p className="mt-1 text-xs text-content-muted">
            Drives the org-scoped pages: cockpit dashboard, roster,
            movements, pressure board.
            {config.suggested_team && pickedTeamId === null && (
              <>
                {" "}
                Suggested:{" "}
                <button
                  onClick={() =>
                    setPickedTeamId(config.suggested_team!.team_id)
                  }
                  className="text-link hover:text-link-hover underline"
                >
                  {config.suggested_team.abbr} ·{" "}
                  {config.suggested_team.city} {config.suggested_team.name}
                </button>
                .
              </>
            )}
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-content-secondary">
          <input
            type="checkbox"
            checked={refScope}
            onChange={(e) => setRefScope(e.target.checked)}
          />
          <span>
            Reference scope
            <span
              className="ml-1 cursor-help text-content-muted"
              title="D13: expand _scoped_players to include any player with ≥1 MLB appearance (HoFers, current-era stars on other orgs, historical legends). Adds ~5-15K reference-scope players."
            >
              ⓘ
            </span>
          </span>
        </label>
        <div>
          <button
            onClick={save}
            disabled={saving || pickedTeamId === null}
            className="rounded bg-accent px-4 py-1.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save config"}
          </button>
        </div>
      </div>
      <p className="text-xs text-content-muted">
        League scope (the {config.league_ids.length}-league tuple) keeps
        the standard MLB org tree default. Per-save scope customization
        lands in v2.2.
      </p>
      {error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
          {error}
        </div>
      )}
    </div>
  );
}
