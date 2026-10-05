import { useEffect, useRef, useMemo } from 'react';
import { Terminal, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { providersApi } from '../../../api';
import { QueryErrorState } from '../../common/QueryState';

export default function LiveConsoleTab({ providerId }) {
    const logsEndRef = useRef(null);

    // `isError` used to be absent. On a 500 from `/providers/{id}/logs` React
    // Query settles with `data === undefined` and `isLoading === false`, so the
    // panel said "No logs available..." and lit a GREEN pulsing dot reading
    // "Polling (5s)" - the strongest possible signal that the log stream is
    // healthy, while it was in fact the only state in which it is not. The 5s
    // `refetchInterval` then retried forever with nothing on screen to say so.
    const { data, isLoading, isError, error, refetch } = useQuery({
        queryKey: ['provider-logs', providerId],
        queryFn: () => providersApi.getLogs(providerId),
        refetchInterval: 5000, // Poll every 5s while tab is open
        enabled: !!providerId,
    });

    const logs = useMemo(() => data?.logs || [], [data?.logs]);

    useEffect(() => {
        // Auto-scroll to bottom
        if (logsEndRef.current) {
            logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [logs]);

    return (
        <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 p-4 h-[400px] flex flex-col mb-4">
            <div className="mb-2 flex items-center justify-between gap-3 shrink-0">
                <span className="font-medium text-sm text-white flex items-center gap-2">
                    <Terminal size={14} className="text-blue-400" />
                    Console Logs
                </span>
                <span
                    className="text-xs text-gray-400 flex items-center gap-1.5"
                    role="status"
                    aria-live="polite"
                >
                    {isLoading ? (
                        <><Loader2 size={12} className="animate-spin" /> Fetching...</>
                    ) : isError ? (
                        <>
                            <span className="w-2 h-2 rounded-full bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]"></span>
                            Log stream unreachable
                        </>
                    ) : (
                        <><span className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]"></span> Polling (5s)</>
                    )}
                </span>
            </div>
            <div className="flex-1 overflow-y-auto font-mono text-2xs leading-relaxed text-gray-300 whitespace-pre-wrap break-words rounded-lg bg-black/60 p-3 ring-1 ring-inset ring-white/[0.05] shadow-inner scrollbar-thin">
                {isError ? (
                    <QueryErrorState
                        noun="provider logs"
                        error={error}
                        onRetry={refetch}
                        className="text-left"
                    />
                ) : logs.length === 0 ? (
                    <span className="text-gray-500 italic">No logs available...</span>
                ) : (
                    logs.map((log, i) => <div key={i}>{log}</div>)
                )}
                <div ref={logsEndRef} />
            </div>
        </div>
    );
}
