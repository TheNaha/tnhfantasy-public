import { AlertTriangle, RotateCw } from 'lucide-react';

/**
 * The three states every server-backed list has, in one place.
 *
 * ## Why this exists
 *
 * Seven pages rendered a failed fetch as a genuinely empty vault:
 * `/roleplay`, `/characters`, `/lorebooks`, `/locations`, `/scenarios`,
 * `/personas` and `/voices`. Each one destructured `data` and `isLoading` from
 * its query and had no `isError` branch at all, so a 500 or a dropped
 * connection produced "No characters yet — create one to start roleplaying"
 * with a working **Create** button, next to a vault that already held three
 * characters. Clicking that button makes a duplicate.
 *
 * That is worse than a stub. A stub looks unfinished; a false empty state is a
 * confident, specific, wrong statement about data the user already owns.
 *
 * `/worlds` had the right shape already and is the model for the copy — it was
 * the page that replaced a dead route, and the comment at `Worlds.jsx:43`
 * records why the `isError` branch is load-bearing rather than decorative.
 *
 * ## Usage
 *
 * The three-state form, for a page whose body *is* the list:
 *
 *   const q = useCharacters();
 *   if (q.isLoading) return <PageSkeleton />;
 *   if (q.isError) return <QueryErrorState noun="characters" error={q.error} onRetry={q.refetch} />;
 *   if (!q.data?.length) return <EmptyState … />;
 *   return <List … />;
 *
 * or the wrapper, when the empty state is markup rather than a component:
 *
 *   <QueryGate isLoading={q.isLoading} loadingFallback={<Skeleton />}
 *              isError={q.isError} error={q.error} onRetry={q.refetch} noun="characters">
 *     {q.data?.length ? <List … /> : <Empty … />}
 *   </QueryGate>
 *
 * `QueryGate` renders nothing extra when there is no error, so adopting it on
 * a page that already handles loading and emptiness costs one attribute each
 * and retires the failure mode permanently.
 *
 * An empty state is *never* a fallback for an error, and an error is *never*
 * rendered as an empty list. That inversion is the whole defect; this component
 * exists so no page has to make the decision again.
 */

function errorMessage(error) {
    if (!error) return 'The request failed.';
    if (typeof error === 'string') return error;
    // React Query nests the useful part: `error.response.data.detail` for a
    // FastAPI 422 carries the per-field message, which is the one worth showing.
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
        const first = detail[0];
        const field = Array.isArray(first?.loc) ? first.loc.filter((p) => p !== 'body').join('.') : '';
        return field ? `${field}: ${first.msg}` : String(first?.msg || first);
    }
    return error.message || 'The request failed.';
}

/**
 * A failed fetch, stated as a failure. Never confusable with emptiness.
 */
export function QueryErrorState({ error, onRetry, noun, className = '' }) {
    const what = noun ? `your ${noun}` : 'this';
    return (
        <div
            role="alert"
            data-query-error=""
            className={`rounded-xl border border-red-500/30 bg-red-500/10 p-6 flex items-start gap-3 ${className}`.trim()}
        >
            <AlertTriangle className="text-red-400 shrink-0 mt-0.5" size={20} aria-hidden="true" />
            <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-red-300">Could not load {what}</h3>
                <p className="text-sm text-red-200/70 mt-1 break-words">
                    {errorMessage(error)} This is not the same as having none — nothing here is a
                    real list until this succeeds.
                </p>
                {onRetry && (
                    <button
                        type="button"
                        onClick={() => onRetry()}
                        className="mt-3 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/40 text-red-200 text-sm font-medium hover:bg-red-500/30 transition-colors"
                    >
                        <RotateCw size={14} aria-hidden="true" />
                        Try again
                    </button>
                )}
            </div>
        </div>
    );
}

/**
 * Loading, then error, then children. `children` owns the empty state, which
 * is the one thing this deliberately does not decide for the caller.
 */
export function QueryGate({
    isLoading,
    isError,
    error,
    onRetry,
    noun,
    loadingFallback = null,
    children,
}) {
    if (isLoading) return loadingFallback;
    if (isError) return <QueryErrorState error={error} onRetry={onRetry} noun={noun} />;
    return children;
}

export default QueryGate;
