import { useState, useMemo, memo, useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { jobsApi } from '../api';
import { Clock, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';

const QUEUE_REFETCH_INTERVAL_MS = 10000;

/**
 * QueueVisualization - Shows pending and running jobs with ETA estimates.
 * Displays as a collapsible panel above the main content.
 * ETAs come from the backend (per-task-type averages), not local guesses.
 */
const QueueVisualization = memo(function QueueVisualization({ onJobClick }) {
    const [isCollapsed, setIsCollapsed] = useState(false);
    const contentId = useId();

    const { data } = useQuery({
        queryKey: ['jobs', 'queue'],
        queryFn: () => jobsApi.getQueueStatus(),
        // Poll only while a queue exists (WS invalidations keep it fresh
        // otherwise) — stops the forever-10s poll on idle dashboards.
        refetchInterval: (query) => {
            const q = query.state.data;
            const hasQueue = Array.isArray(q?.queue) && q.queue.length > 0;
            return hasQueue ? QUEUE_REFETCH_INTERVAL_MS : false;
        },
    });

    const { queue, stats, runningJobs, pendingJobs } = useMemo(() => {
        const rawQueue = Array.isArray(data?.queue) ? data.queue : [];
        const running = rawQueue.filter((j) => j.status === 'generating');
        const pending = rawQueue
            .filter((j) => j.status === 'pending')
            .sort((a, b) => (a.position || 999) - (b.position || 999));

        return {
            queue: rawQueue,
            stats: {
                avg_duration_seconds: data?.avg_duration_seconds || {},
                has_history: !!data?.has_history,
                total_pending: data?.total_pending ?? pending.length,
                total_running: data?.total_running ?? running.length,
            },
            runningJobs: running,
            pendingJobs: pending,
        };
    }, [data]);

    const avgDurationSeconds = useMemo(() => {
        const durations = stats.avg_duration_seconds || {};
        const values = Object.values(durations).filter((v) => typeof v === 'number' && v > 0);
        if (values.length === 0) return null;
        return Math.max(...values);
    }, [stats.avg_duration_seconds]);

    // Don't render if queue is empty
    if (queue.length === 0) return null;

    const formatETA = (seconds) => {
        if (!seconds || seconds <= 0) return 'Soon';
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
        return `${Math.round(seconds / 3600)}h`;
    };

    return (
        <div className="glass-panel rounded-2xl overflow-hidden mb-4 border border-white/5 shadow-xl">
            {/* Header */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                aria-expanded={!isCollapsed}
                aria-controls={contentId}
                className="w-full px-5 py-4 flex items-center justify-between hover:bg-white/5 transition-colors group"
            >
                <div className="flex items-center gap-3">
                    <Clock className="text-blue-400 drop-shadow-[0_0_8px_rgba(59,130,246,0.6)]" size={18} aria-hidden="true" />
                    <span className="font-semibold text-white tracking-wide">
                        Queue <span className="text-gray-400 font-normal">({stats.total_running} running, {stats.total_pending} pending)</span>
                    </span>
                    {!stats.has_history && (
                        <span className="text-[10px] text-yellow-400 bg-yellow-400/10 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider border border-yellow-400/20">
                            Calculating ETA...
                        </span>
                    )}
                </div>
                {isCollapsed ?
                    <ChevronDown size={18} className="text-gray-400 group-hover:text-white transition-colors" aria-hidden="true" /> :
                    <ChevronUp size={18} className="text-gray-400 group-hover:text-white transition-colors" aria-hidden="true" />
                }
            </button>

            {/* Content */}
            <AnimatePresence>
                {!isCollapsed && (
                    <div
                        id={contentId}
                    >
                        <div className="px-5 pb-5 space-y-3">
                            {/* Timeline Bar - Using flex for proper job layout */}
                            <div className="flex h-10 bg-[#0B0E14] rounded-xl overflow-hidden gap-0.5 shadow-inner" aria-hidden="true">
                                {runningJobs.map(job => (
                                    <div
                                        key={`timeline-${job.id}`}
                                        className="relative bg-blue-500/20 border-r border-blue-500/30 overflow-hidden flex-1 group transition-colors hover:bg-blue-500/30"
                                        title={`Running: ${job.prompt?.slice(0, 50) || 'Image generation'}`}
                                    >
                                        <div
                                            style={{ width: `${job.progress || 0}%` }}
                                        />
                                        {/* Content overlay */}
                                        <div className="relative z-10 flex items-center gap-1">
                                            <Loader2 className="animate-spin text-white" size={14} />
                                            <span className="text-xs text-white/90 font-medium">{Math.round(job.progress || 0)}%</span>
                                        </div>
                                    </div>
                                ))}

                                {/* Pending jobs */}
                                {pendingJobs.map((job) => (
                                    <div
                                        key={job.id}
                                        className="h-full bg-gray-700 border-l-2 border-gray-600 flex items-center justify-center cursor-pointer hover:bg-gray-600 transition-colors min-w-[50px] flex-1"
                                        onClick={() => onJobClick?.(job.id)}
                                        title={job.prompt || 'Pending...'}
                                    >
                                        <span className="text-xs text-gray-400">#{job.position}</span>
                                    </div>
                                ))}
                            </div>

                            {/* Job List with ETA */}
                            <div className="space-y-1 max-h-32 overflow-y-auto">
                                {queue.map((job) => (
                                    <button
                                        key={job.id}
                                        onClick={() => onJobClick?.(job.id)}
                                        className="w-full flex items-center justify-between px-3 py-2 bg-gray-800/50 rounded-lg hover:bg-gray-700/50 cursor-pointer transition-colors text-left group focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none"
                                        aria-label={`Job status: ${job.status}, Prompt: ${job.prompt || 'Generating'}, Progress: ${Math.round(job.progress || 0)}%`}
                                    >
                                        <div className="flex items-center gap-3 min-w-0">
                                            {job.status === 'generating' ? (
                                                <Loader2 className="flex-shrink-0 animate-spin text-blue-400" size={14} aria-hidden="true" />
                                            ) : (
                                                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-700 flex items-center justify-center text-xs text-gray-400" aria-hidden="true">
                                                    {job.position}
                                                </span>
                                            )}
                                            <span className="text-sm text-gray-300 truncate group-hover:text-white transition-colors">
                                                {job.prompt || 'Generating...'}
                                            </span>
                                        </div>
                                        <div className="flex items-center gap-2 flex-shrink-0">
                                            {job.status === 'generating' && job.progress > 0 && (
                                                <span className="text-xs text-blue-400">{Math.round(job.progress)}%</span>
                                            )}
                                            <span className="text-xs text-gray-500">
                                                ETA: {formatETA(job.eta_seconds)}
                                            </span>
                                        </div>
                                    </button>
                                ))}
                            </div>

                            {/* Footer Stats */}
                            <div className="text-xs text-gray-500 text-center pt-1">
                                {avgDurationSeconds ? `Avg. job time: ${formatETA(avgDurationSeconds)}` : 'Avg. job time: —'}
                                {pendingJobs.length > 0 && (
                                    <> • Total wait: ~{formatETA(pendingJobs[pendingJobs.length - 1].eta_seconds)}</>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
});

export default QueueVisualization;
