import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AlertTriangle, Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  deleteEndpoint,
  fetchEndpoints,
  fetchRouting,
  resetStageRoute,
  saveEndpoint,
  setStageRoute,
  STAGES,
  STAGE_LABELS,
  type EndpointKind,
  type LlmEndpoint,
} from "@/lib/settings";

// Chat is the only stage this app calls live -- rerank/extract/synthesis
// only run from offline scripts/, so routing for them isn't shown here.
// The backend still accepts overrides for all four; this is UI-only.
const VISIBLE_STAGES = ["chat"] as const satisfies readonly (typeof STAGES)[number][];

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Clio" },
      {
        name: "description",
        content: "Manage LLM endpoints and which model each pipeline stage uses.",
      },
    ],
  }),
  component: SettingsPage,
});

const KIND_LABELS: Record<EndpointKind, string> = {
  auto: "Auto-detect",
  local: "Local",
  api: "API (remote)",
};

type EndpointForm = {
  name: string;
  base_url: string;
  api_key: string;
  kind: EndpointKind;
  default_model: string;
};

const EMPTY_FORM: EndpointForm = {
  name: "",
  base_url: "",
  api_key: "",
  kind: "auto",
  default_model: "",
};

function keyStatus(endpoint: LlmEndpoint): string {
  if (!endpoint.has_key) return "No key";
  if (endpoint.key_source === "env") return `Key from env:${endpoint.key_env_var}`;
  return "Key stored (encrypted)";
}

function SettingsPage() {
  const queryClient = useQueryClient();
  const endpointsQuery = useQuery({
    queryKey: ["settings", "endpoints"],
    queryFn: fetchEndpoints,
  });
  const routingQuery = useQuery({
    queryKey: ["settings", "routing"],
    queryFn: fetchRouting,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [form, setForm] = useState<EndpointForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const endpoints = endpointsQuery.data?.endpoints ?? [];
  const routing = routingQuery.data?.routing ?? [];

  const invalidateEndpoints = () =>
    queryClient.invalidateQueries({ queryKey: ["settings", "endpoints"] });
  const invalidateRouting = () =>
    queryClient.invalidateQueries({ queryKey: ["settings", "routing"] });

  const saveMutation = useMutation({
    mutationFn: (body: EndpointForm) =>
      saveEndpoint({
        name: body.name.trim(),
        base_url: body.base_url.trim(),
        api_key: body.api_key.trim() || undefined,
        kind: body.kind,
        default_model: body.default_model.trim() || undefined,
      }),
    onSuccess: () => {
      invalidateEndpoints();
      invalidateRouting(); // endpoint names shown in the routing selects may change
      setFormOpen(false);
      setEditingName(null);
      setForm(EMPTY_FORM);
      setFormError(null);
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : "Could not save endpoint."),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteEndpoint,
    onSuccess: () => {
      invalidateEndpoints();
      invalidateRouting();
    },
  });

  const routeMutation = useMutation({
    mutationFn: ({ stage, endpointName }: { stage: (typeof STAGES)[number]; endpointName: string }) =>
      setStageRoute(stage, endpointName),
    onSuccess: invalidateRouting,
  });

  const resetMutation = useMutation({
    mutationFn: resetStageRoute,
    onSuccess: invalidateRouting,
  });

  const startAdd = () => {
    setEditingName(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const startEdit = (endpoint: LlmEndpoint) => {
    setEditingName(endpoint.name);
    setForm({
      name: endpoint.name,
      base_url: endpoint.base_url,
      api_key: "",
      kind: endpoint.kind,
      default_model: endpoint.default_model ?? "",
    });
    setFormError(null);
    setFormOpen(true);
  };

  const cancelForm = () => {
    setFormOpen(false);
    setEditingName(null);
    setForm(EMPTY_FORM);
    setFormError(null);
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <header className="border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">Settings</h1>
      </header>

      <div className="mx-auto max-w-2xl space-y-8 px-5 py-8">
        {/* Endpoints */}
        <section>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-medium text-foreground">Endpoints</h2>
            {!formOpen && (
              <button
                onClick={startAdd}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
              >
                <Plus className="h-3.5 w-3.5" />
                Add endpoint
              </button>
            )}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            A local endpoint is a downloaded model served on your machine (e.g. Ollama). An
            API endpoint is a remote provider, keyed by an API key.
          </p>

          {endpointsQuery.isPending && (
            <p className="mt-4 text-sm text-muted-foreground">Loading endpoints…</p>
          )}
          {endpointsQuery.isError && (
            <div className="mt-4 flex items-start gap-3 rounded-xl border border-border bg-surface p-4">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <p className="text-sm text-foreground">
                {(endpointsQuery.error as Error).message}
              </p>
            </div>
          )}

          {formOpen && (
            <div className="mt-4 rounded-xl border border-primary/50 bg-surface p-4">
              <h3 className="text-sm font-medium text-foreground">
                {editingName ? `Edit ${editingName}` : "New endpoint"}
              </h3>
              <div className="mt-3 space-y-3">
                <Field label="Name">
                  <input
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                    disabled={editingName !== null}
                    placeholder="e.g. deepseek"
                    className="w-full rounded-lg border border-border bg-elevated px-3 py-2 text-sm outline-none focus:border-primary disabled:opacity-60"
                  />
                </Field>
                <Field label="Base URL">
                  <input
                    value={form.base_url}
                    onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                    placeholder="https://api.example.com or http://localhost:11434"
                    className="w-full rounded-lg border border-border bg-elevated px-3 py-2 text-sm outline-none focus:border-primary"
                  />
                </Field>
                <Field label="Kind">
                  <Select
                    value={form.kind}
                    onValueChange={(v) => setForm((f) => ({ ...f, kind: v as EndpointKind }))}
                  >
                    <SelectTrigger className="w-full rounded-lg border-border bg-elevated text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(KIND_LABELS) as EndpointKind[]).map((k) => (
                        <SelectItem key={k} value={k}>
                          {KIND_LABELS[k]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Default model">
                  <input
                    value={form.default_model}
                    onChange={(e) => setForm((f) => ({ ...f, default_model: e.target.value }))}
                    placeholder="e.g. deepseek-v4-flash or qwen3:4b"
                    className="w-full rounded-lg border border-border bg-elevated px-3 py-2 text-sm outline-none focus:border-primary"
                  />
                </Field>
                <Field label="API key">
                  <input
                    value={form.api_key}
                    onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                    type="password"
                    autoComplete="off"
                    placeholder={
                      editingName
                        ? "Leave blank to keep the existing key"
                        : "Paste a key, or type env:VARNAME to read it from .env"
                    }
                    className="w-full rounded-lg border border-border bg-elevated px-3 py-2 text-sm outline-none focus:border-primary"
                  />
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Stored encrypted on the backend -- never shown again after saving. Type
                    env:VARNAME instead to read it from your .env at request time.
                  </p>
                </Field>
              </div>

              {formError && (
                <p className="mt-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {formError}
                </p>
              )}

              <div className="mt-4 flex items-center gap-2">
                <button
                  onClick={() => saveMutation.mutate(form)}
                  disabled={saveMutation.isPending || !form.name.trim() || !form.base_url.trim()}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  <Check className="h-3.5 w-3.5" />
                  {saveMutation.isPending ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={cancelForm}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div className="mt-4 space-y-2">
            {endpoints.map((endpoint) => (
              <div
                key={endpoint.name}
                className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-4"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-medium text-foreground">{endpoint.name}</h3>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[11px]",
                        endpoint.is_local
                          ? "bg-secondary/50 text-secondary-foreground"
                          : "bg-primary/20 text-primary",
                      )}
                    >
                      {endpoint.is_local ? "Local" : "API"}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {endpoint.base_url}
                    {endpoint.default_model ? ` · ${endpoint.default_model}` : ""}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground/70">
                    {keyStatus(endpoint)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    onClick={() => startEdit(endpoint)}
                    aria-label={`Edit ${endpoint.name}`}
                    className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`Remove endpoint "${endpoint.name}"?`)) {
                        deleteMutation.mutate(endpoint.name);
                      }
                    }}
                    aria-label={`Remove ${endpoint.name}`}
                    className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-elevated hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Stage routing */}
        <section>
          <h2 className="text-sm font-medium text-foreground">Which model does what</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Pick which endpoint answers chat.
          </p>

          {routingQuery.isPending && (
            <p className="mt-4 text-sm text-muted-foreground">Loading routing…</p>
          )}

          <div className="mt-4 space-y-2">
            {VISIBLE_STAGES.map((stage) => {
              const row = routing.find((r) => r.stage === stage);
              return (
                <div
                  key={stage}
                  className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface p-3"
                >
                  <span className="text-sm text-foreground">{STAGE_LABELS[stage]}</span>
                  <div className="flex items-center gap-2">
                    {row?.is_override && (
                      <button
                        onClick={() => resetMutation.mutate(stage)}
                        className="text-[11px] text-muted-foreground underline decoration-dotted transition-colors hover:text-foreground"
                      >
                        Reset to default
                      </button>
                    )}
                    <Select
                      {...(row ? { value: row.endpoint_name } : {})}
                      onValueChange={(v) => routeMutation.mutate({ stage, endpointName: v })}
                      disabled={endpoints.length === 0}
                    >
                      <SelectTrigger
                        aria-label={`${STAGE_LABELS[stage]} endpoint`}
                        className="h-auto w-auto gap-1.5 rounded-lg border-border bg-elevated px-2.5 py-1.5 text-xs"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {endpoints.map((endpoint) => (
                          <SelectItem key={endpoint.name} value={endpoint.name}>
                            {endpoint.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
