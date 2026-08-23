import { useCallback, useEffect, useRef, useState } from "react";

import { loadOverviewRoute, type OverviewRouteData } from "../api";
import { OverviewView } from "../components";

interface OverviewRouteProps {
  reloadVersion: number;
  onShowAccounts: () => void;
  onShowActivity: () => void;
  onShowIncome: () => void;
  onShowWealth: () => void;
  onAddAccount: () => void;
}

export default function OverviewRoute({
  reloadVersion,
  onShowAccounts,
  onShowActivity,
  onShowIncome,
  onShowWealth,
  onAddAccount,
}: OverviewRouteProps) {
  const [data, setData] = useState<OverviewRouteData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState(false);
  const requestGeneration = useRef(0);
  const activeController = useRef<AbortController | null>(null);

  const load = useCallback(async (period?: { startDate: string; endDate: string }) => {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    setLoading(true);
    setFailure(false);
    try {
      const result = await loadOverviewRoute(period, controller.signal);
      if (requestGeneration.current === generation && !controller.signal.aborted) setData(result);
    } catch {
      if (requestGeneration.current === generation && !controller.signal.aborted) setFailure(true);
    } finally {
      if (requestGeneration.current === generation && !controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestGeneration.current += 1;
      activeController.current?.abort();
    };
  }, [load, reloadVersion]);

  if (loading && !data) {
    return (
      <section className="loading-state" role="status" aria-live="polite" aria-label="Loading Overview">
        <div className="loading-mark" aria-hidden="true">M</div>
        <p>Loading Overview…</p>
      </section>
    );
  }

  if (failure && !data) {
    return (
      <section className="fatal-state" role="alert">
        <span>Overview unavailable</span>
        <h1>Overview could not load.</h1>
        <p>The local read was interrupted. No financial data was changed.</p>
        <button className="primary-button" type="button" onClick={() => void load()}>Try again</button>
      </section>
    );
  }

  if (!data) return null;

  const hasAccountValueEvidence = data.accounts.accounts.length > 0 && data.accounts.as_of !== null;
  if (!hasAccountValueEvidence) {
    return (
      <div className="view-stack account-first-view">
        <section className="panel empty-state" role="status" aria-labelledby="overview-empty-title">
          <span>Money Map</span>
          <h1 id="overview-empty-title">Overview</h1>
          <h2>Overview unavailable</h2>
          <p>No account-value evidence is available yet. No financial result is shown.</p>
          <button className="primary-button" type="button" onClick={onAddAccount}>Use Add account</button>
          <p>Manual import remains available from Add account.</p>
        </section>
      </div>
    );
  }

  return (
    <>
      {failure && (
        <div className="error-banner" role="alert">
          Overview could not refresh. The last accepted result remains visible.
          <button type="button" onClick={() => void load()}>Try again</button>
        </div>
      )}
      <OverviewView
        overview={data.overview}
        accounts={data.accounts}
        timeline={data.timeline}
        busy={loading}
        onPeriodChange={(startDate, endDate) => {
          if (startDate <= endDate) void load({ startDate, endDate });
        }}
        onShowAccounts={onShowAccounts}
        onShowActivity={onShowActivity}
        onShowIncome={onShowIncome}
        onShowWealth={onShowWealth}
      />
    </>
  );
}
