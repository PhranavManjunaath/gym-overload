"use client";

import { useCallback, useEffect, useEffectEvent, useState } from "react";

type State<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Load data when the page becomes visible. With cacheComponents, pages are hidden
 * (not unmounted) on navigation and their effects re-run when shown again, so
 * coming back to a page always refreshes it. `deps` re-loads when they change.
 */
export function useApi<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);
  const depsKey = JSON.stringify(deps);
  const runLoad = useEffectEvent(() => load());

  useEffect(() => {
    let active = true;
    runLoad()
      .then((data) => active && setState({ data, error: null, loading: false }))
      .catch((e: unknown) => active && setState({ data: null, error: e instanceof Error ? e.message : String(e), loading: false }));
    return () => {
      active = false;
    };
  }, [depsKey, nonce]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    setNonce((n) => n + 1);
  }, []);

  return { ...state, reload };
}
