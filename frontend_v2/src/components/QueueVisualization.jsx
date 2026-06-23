import { useState, useMemo, memo, useId } from 'react';
import { useActiveJobs } from '../hooks/useActiveJobs';
import useJobStore from '../store/jobStore';
import { Clock, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { AnimatePresence } from 'framer-motion';

/**
 * QueueVisualization - Shows pending and running jobs with ETA estimates.
 * Displays as a collapsible panel above the main content.
 */
const QueueVisualization = memo(function QueueVisualization({ onJobClick }) {
    const [isCollapsed, setIsCollapsed] = useState(false);
    const contentId = useId();

    // Use active jobs from React Query
    const { data: activeJobs = [] } = useActiveJobs();
    const allJobs = useJobStore(state => state.jobs);

    const { queue, stats, runningJobs, pendingJobs } = useMemo(() => {
        // Merge Zustand jobs into activeJobs to get realtime progress
        const jobMap = new Map();
        activeJobs.forEach(job => {
            jobMap.set(job.id, { ...job });
        });
        
        Object.keys(allJobs).forEach(id => {
            if (jobMap.has(id)) {
                jobMap.set(id, { ...jobMap.get(id), ...allJobs[id] });
            } else {
                jobMap.set(id, { id, ...allJobs[id] });
            }
        });
        
        const mergedJobs = Array.from(jobMap.values());

        // Filter for active items only and sort
        const runningStatuses = [
            'sent-to-provider', 'sent_to_provider', 'connecting', 'connected', 
            'pre-generation', 'pre_generation', 'generating', 'post-processing', 
            'post_processing', 'generating-blurhash', 'generating_blurhash', 
            'generating-thumbnails', 'generating_thumbnails', 'running', 'processing'
        ];
        
        const running = mergedJobs.filter(j => runningStatuses.includes(j.status));
        const pending = mergedJobs.filter(j => j.status === 'pending' || j.status === 'queued')
            .sort((a, b) => (a.queue_position || 999) - (b.queue_position || 999));

        // Calculate basic stats/ETAs locally since we have state
        // This is a simplified estimation - ideally backend sends this, but WS handles status
        const DEFAULT_AVG_JOB_TIME = 30; // Default seconds per job; backend sends actual stats via queue endpoint

        const runningProcessed = running.map(j => ({
            ...j,
            eta_seconds: Math.max(0, DEFAULT_AVG_JOB_TIME - ((j.progress || 0) / 100) * DEFAULT_AVG_JOB_TIME)
        }));

        const pendingProcessed = pending.map((j, index) => ({
            ...j,
            position: index + 1,
            eta_seconds: DEFAULT_AVG_JOB_TIME * (index + 1) + (running.length > 0 ? DEFAULT_AVG_JOB_TIME / 2 : 0)
        }));

        // Calculate approximate ETAs
        const calculatedQueue = [...runningProcessed, ...pendingProcessed];

        const derivedStats = {
            avg_duration_seconds: DEFAULT_AVG_JOB_TIME,
            has_history: true,
            total_pending: pending.length,
            total_running: running.length
        };

        return {
            queue: calculatedQueue,
            stats: derivedStats,
            // ⚡ Bolt: Return pre-filtered arrays to avoid O(N) filtering in render
            runningJobs: runningProcessed,
            pendingJobs: pendingProcessed
        };
    }, [activeJobs, allJobs]);

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
                        Queue <span className="text-gray-400 font-normal">({runningJobs.length} running, {pendingJobs.length} pending)</span>
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
                                            {job.status === 'running' ? (
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
                                            {job.status === 'running' && job.progress > 0 && (
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
                                Avg. job time: {formatETA(stats.avg_duration_seconds)}
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
