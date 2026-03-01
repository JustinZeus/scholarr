import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { ApiRequestError } from "@/lib/api/errors";
import { createDefaultSafetyState } from "@/features/safety";

vi.mock("@/features/runs", () => ({
  listRuns: vi.fn(),
  triggerManualRun: vi.fn(),
  cancelRun: vi.fn(),
}));

import { cancelRun, listRuns, triggerManualRun } from "@/features/runs";
import {
  RUN_STATUS_POLL_INTERVAL_MS,
  RUN_STATUS_STARTING_PHASE_MS,
  useRunStatusStore,
} from "@/stores/run_status";

function buildRun(overrides: Partial<{
  id: number;
  trigger_type: string;
  status: string;
  start_dt: string;
  end_dt: string | null;
  scholar_count: number;
  new_publication_count: number;
  failed_count: number;
  partial_count: number;
}> = {}) {
  return {
    id: 1,
    trigger_type: "manual",
    status: "success",
    start_dt: "2026-02-19T12:00:00Z",
    end_dt: "2026-02-19T12:01:00Z",
    scholar_count: 3,
    new_publication_count: 2,
    failed_count: 0,
    partial_count: 0,
    ...overrides,
  };
}

function buildRunsPayload(runs: ReturnType<typeof buildRun>[]) {
  return {
    runs,
    safety_state: createDefaultSafetyState(),
  };
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  public readonly url: string;
  public closed = false;
  private listeners = new Map<string, Array<(event: { data: string }) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(eventType: string, callback: (event: { data: string }) => void): void {
    const existing = this.listeners.get(eventType) ?? [];
    this.listeners.set(eventType, [...existing, callback]);
  }

  emit(eventType: string, payload: unknown): void {
    const callbacks = this.listeners.get(eventType) ?? [];
    for (const callback of callbacks) {
      callback({ data: JSON.stringify(payload) });
    }
  }

  close(): void {
    this.closed = true;
  }
}

describe("run status store", () => {
  const mockedListRuns = vi.mocked(listRuns);
  const mockedTriggerManualRun = vi.mocked(triggerManualRun);
  const mockedCancelRun = vi.mocked(cancelRun);

  beforeEach(() => {
    setActivePinia(createPinia());
    mockedListRuns.mockReset();
    mockedTriggerManualRun.mockReset();
    mockedCancelRun.mockReset();
    vi.useRealTimers();
  });

  afterEach(() => {
    useRunStatusStore().reset();
    vi.useRealTimers();
  });

  it("bootstraps from latest run and exposes idle start state", async () => {
    mockedListRuns.mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 11, status: "success" })]));

    const store = useRunStatusStore();
    await store.bootstrap();

    expect(mockedListRuns).toHaveBeenCalledWith({ limit: 1 });
    expect(store.latestRun?.id).toBe(11);
    expect(store.canStart).toBe(true);
    expect(store.isRunActive).toBe(false);
    expect(store.isPolling).toBe(false);
  });

  it("starts manual checks and marks active state", async () => {
    mockedTriggerManualRun.mockResolvedValueOnce({
      run_id: 25,
      status: "running",
      scholar_count: 0,
      succeeded_count: 0,
      failed_count: 0,
      partial_count: 0,
      new_publication_count: 0,
      reused_existing_run: false,
      idempotency_key: "abc",
      safety_state: createDefaultSafetyState(),
    });
    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 25, status: "running", end_dt: null })]),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result).toEqual({
      kind: "started",
      runId: 25,
      reusedExistingRun: false,
    });
    expect(store.latestRun?.id).toBe(25);
    expect(store.isRunActive).toBe(true);
    expect(store.isPolling).toBe(true);
  });

  it("normalizes run_in_progress responses into already_running state", async () => {
    mockedTriggerManualRun.mockRejectedValueOnce(
      new ApiRequestError({
        status: 409,
        code: "run_in_progress",
        message: "A run is already in progress for this account.",
        details: { run_id: 42 },
        requestId: "req_123",
      }),
    );
    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 42, status: "running", end_dt: null })]),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result).toEqual({
      kind: "already_running",
      runId: 42,
      requestId: "req_123",
    });
    expect(store.latestRun?.id).toBe(42);
    expect(store.isRunActive).toBe(true);
    expect(store.lastErrorMessage).toBeNull();
  });

  it("polls while a run is active and stops when it completes", async () => {
    vi.useFakeTimers();
    mockedListRuns
      .mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 90, status: "running", end_dt: null })]))
      .mockResolvedValueOnce(buildRunsPayload([buildRun({ id: 90, status: "success" })]));

    const store = useRunStatusStore();
    await store.syncLatest();
    expect(store.isPolling).toBe(true);

    await vi.advanceTimersByTimeAsync(RUN_STATUS_POLL_INTERVAL_MS + 10);

    expect(mockedListRuns).toHaveBeenCalledTimes(2);
    expect(store.latestRun?.status).toBe("success");
    expect(store.isPolling).toBe(false);
    expect(store.isRunActive).toBe(false);
  });

  it("stores cooldown safety state when manual start is blocked by policy cooldown", async () => {
    mockedTriggerManualRun.mockRejectedValueOnce(
      new ApiRequestError({
        status: 429,
        code: "scrape_cooldown_active",
        message: "Scrape safety cooldown is active; run start is temporarily blocked.",
        details: {
          safety_state: {
            cooldown_active: true,
            cooldown_reason: "blocked_failure_threshold_exceeded",
            cooldown_reason_label: "Blocked responses exceeded safety threshold",
            cooldown_until: "2026-02-19T12:30:00Z",
            cooldown_remaining_seconds: 600,
            recommended_action: "Wait for cooldown to expire.",
            counters: {
              consecutive_blocked_runs: 1,
              consecutive_network_runs: 0,
              cooldown_entry_count: 1,
              blocked_start_count: 2,
              last_blocked_failure_count: 1,
              last_network_failure_count: 0,
              last_evaluated_run_id: 10,
            },
          },
        },
      }),
    );

    const store = useRunStatusStore();
    const result = await store.startManualCheck();

    expect(result.kind).toBe("error");
    expect(store.safetyState.cooldown_active).toBe(true);
    expect(store.canStart).toBe(false);
  });

  it("switches from starting to in-progress when trigger request remains open", async () => {
    vi.useFakeTimers();
    mockedTriggerManualRun.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              run_id: 77,
              status: "running",
              scholar_count: 0,
              succeeded_count: 0,
              failed_count: 0,
              partial_count: 0,
              new_publication_count: 0,
              reused_existing_run: false,
              idempotency_key: "x",
              safety_state: createDefaultSafetyState(),
            });
          }, RUN_STATUS_STARTING_PHASE_MS + 500);
        }),
    );
    mockedListRuns.mockResolvedValueOnce(buildRunsPayload([]));

    const store = useRunStatusStore();
    const startPromise = store.startManualCheck();

    expect(store.isSubmitting).toBe(true);
    expect(store.isLikelyRunning).toBe(false);

    await vi.advanceTimersByTimeAsync(RUN_STATUS_STARTING_PHASE_MS + 20);
    expect(store.isLikelyRunning).toBe(true);
    await vi.advanceTimersByTimeAsync(520);
    await startPromise;
    expect(store.isRunActive).toBe(true);
  });

  it("cancels an active check and transitions to canceled state", async () => {
    mockedCancelRun.mockResolvedValueOnce({
      run: buildRun({ id: 50, status: "canceled" }),
      summary: {
        succeeded_count: 0,
        failed_count: 0,
        partial_count: 0,
        failed_state_counts: {},
        failed_reason_counts: {},
        scrape_failure_counts: {},
        retry_counts: {
          retries_scheduled_count: 0,
          scholars_with_retries_count: 0,
          retry_exhausted_count: 0,
        },
        alert_thresholds: {},
        alert_flags: {},
      },
      scholar_results: [],
      safety_state: createDefaultSafetyState(),
    } as any);

    const store = useRunStatusStore();
    store.setLatestRun(buildRun({ id: 50, status: "running", end_dt: null }));
    expect(store.isRunActive).toBe(true);

    const result = await store.cancelActiveCheck();

    expect(result.kind).toBe("success");
    expect(store.latestRun?.status).toBe("canceled");
    expect(store.isRunActive).toBe(false);
    expect(store.isPolling).toBe(false);
  });

  it("cancels a resolving run using server status as source of truth", async () => {
    mockedCancelRun.mockResolvedValueOnce({
      run: buildRun({ id: 72, status: "failed" }),
      summary: {
        succeeded_count: 0,
        failed_count: 1,
        partial_count: 0,
        failed_state_counts: {},
        failed_reason_counts: {},
        scrape_failure_counts: {},
        retry_counts: {
          retries_scheduled_count: 0,
          scholars_with_retries_count: 0,
          retry_exhausted_count: 0,
        },
        alert_thresholds: {},
        alert_flags: {},
      },
      scholar_results: [],
      safety_state: createDefaultSafetyState(),
    } as any);

    const store = useRunStatusStore();
    store.setLatestRun(buildRun({ id: 72, status: "resolving", end_dt: null }));

    const result = await store.cancelActiveCheck();

    expect(result.kind).toBe("success");
    expect(store.latestRun?.status).toBe("failed");
    expect(store.isRunActive).toBe(false);
  });

  it("reconciles poll responses without regressing publication counters", async () => {
    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 99, status: "running", new_publication_count: 1, end_dt: null })]),
    );

    const store = useRunStatusStore();
    await store.syncLatest();
    store.latestRun = buildRun({ id: 99, status: "running", new_publication_count: 5, end_dt: null });

    mockedListRuns.mockResolvedValueOnce(
      buildRunsPayload([buildRun({ id: 99, status: "running", new_publication_count: 3, end_dt: null })]),
    );
    await store.syncLatest();

    expect(store.latestRun?.new_publication_count).toBe(5);
  });

  it("applies identifier_updated SSE events to live publications", () => {
    const previousEventSource = (globalThis as any).EventSource;
    FakeEventSource.instances = [];
    (globalThis as any).EventSource = FakeEventSource as any;
    try {
      const store = useRunStatusStore();
      store.setLatestRun(buildRun({ id: 314, status: "running", end_dt: null }));

      const stream = FakeEventSource.instances[0];
      expect(stream).toBeDefined();
      stream.emit("publication_discovered", {
        publication_id: 22,
        scholar_profile_id: 7,
        scholar_label: "Ada Lovelace",
        title: "Optimization Notes",
        pub_url: null,
        first_seen_at: "2026-02-26T10:00:00Z",
      });
      expect(store.livePublications).toHaveLength(1);
      expect(store.livePublications[0].display_identifier).toBeNull();

      stream.emit("identifier_updated", {
        publication_id: 22,
        display_identifier: {
          kind: "doi",
          value: "10.1000/xyz",
          label: "DOI: 10.1000/xyz",
          url: "https://doi.org/10.1000/xyz",
          confidence_score: 0.95,
        },
      });
      expect(store.livePublications[0].display_identifier?.kind).toBe("doi");
      expect(store.livePublications[0].display_identifier?.value).toBe("10.1000/xyz");
    } finally {
      (globalThis as any).EventSource = previousEventSource;
    }
  });
});
