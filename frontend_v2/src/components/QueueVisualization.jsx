import { useState, useEffect, memo } from 'react';
import { useJobStore } from '../store/jobStore';
import { Clock, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * QueueVisualization - Shows pending and running jobs with ETA estimates.
 * Displays as a collapsible panel above the main content.
 */
const QueueVisualization = memo(function QueueVisualization({ onJobClick }) {
    const [queue, setQueue] = useState([]);
    const [isCollapsed, setIsCollapsed] = useState(false);

    // Use global WebSocket job store
    const { jobs: activeJobs } = useJobStore();
    const [stats, setStats] = useState({ avg_duration_seconds: 30, has_history: false });

    // Derive queue from active jobs
    useEffect(() => {
        // Filter for active items only and sort
        const running = activeJobs.filter(j => j.status === 'running' || j.status === 'processing');
        const pending = activeJobs.filter(j => j.status === 'pending' || j.status === 'queued')
            .sort((a, b) => (a.queue_position || 999) - (b.queue_position || 999));

        // Calculate basic stats/ETAs locally since we have state
        // This is a simplified estimation - ideally backend sends this, but WS handles status
        const avgTime = 30; // Default or fetch once on mount if needed

        // Calculate approximate ETAs
        const calculatedQueue = [
            ...running.map(j => ({
                ...j,
                eta_seconds: Math.max(0, avgTime - ((Date.now() - new Date(j.started_at || Date.now())) / 1000))
            })),
            ...pending.map((j, idx) => ({
                ...j,
                position: idx + 1,
                eta_seconds: avgTime * (idx + 1) + (running.length > 0 ? avgTime / 2 : 0)
            }))
        ];

        setQueue(calculatedQueue);

        // Update valid stats
        setStats({
            avg_duration_seconds: avgTime,
            has_history: true,
            total_pending: pending.length,
            total_running: running.length
        });

    }, [activeJobs]);

    // Don't render if queue is empty
    if (queue.length === 0) return null;

    const formatETA = (seconds) => {
        if (!seconds || seconds <= 0) return 'Soon';
        if (seconds < 60) return `${Math.round(seconds)}s`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
        return `${Math.round(seconds / 3600)}h`;
    };

    const runningJobs = queue.filter(j => j.status === 'running');
    const pendingJobs = queue.filter(j => j.status === 'pending');

    return (
        <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-gray-900/80 backdrop-blur-sm border border-gray-800 rounded-xl overflow-hidden mb-4"
        >
            {/* Header */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-gray-800/50 transition-colors"
            >
                <div className="flex items-center gap-3">
                    <Clock className="text-blue-400" size={18} />
                    <span className="font-medium text-white">
                        Queue ({runningJobs.length} running, {pendingJobs.length} pending)
                    </span>
                    {!stats.has_history && (
                        <span className="text-xs text-yellow-500 bg-yellow-500/10 px-2 py-0.5 rounded">
                            Calculating ETA...
                        </span>
                    )}
                </div>
                {isCollapsed ? <ChevronDown size={18} className="text-gray-400" /> : <ChevronUp size={18} className="text-gray-400" />}
            </button>

            {/* Content */}
            <AnimatePresence>
                {!isCollapsed && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                    >
                        <div className="px-4 pb-4 space-y-2">
                            {/* Timeline Bar - Using flex for proper job layout */}
                            <div className="flex h-8 bg-gray-800 rounded-lg overflow-hidden gap-0.5">
                                {/* Running jobs */}
                                {runningJobs.map((job, idx) => (
                                    <motion.div
                                        key={job.id}
                                        initial={{ width: 0 }}
                                        animate={{ flex: 1 }}
                                        className="relative h-full bg-gray-700 flex items-center justify-center cursor-pointer min-w-[60px] overflow-hidden"
                                        onClick={() => onJobClick?.(job.id)}
                                        title={job.prompt || 'Running...'}
                                    >
                                        {/* Progress fill */}
                                        <div
                                            className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-600 to-blue-400 transition-all duration-300"
                                            style={{ width: `${job.progress || 0}%` }}
                                        />
                                        {/* Content overlay */}
                                        <div className="relative z-10 flex items-center gap-1">
                                            <Loader2 className="animate-spin text-white" size={14} />
                                            <span className="text-xs text-white/90 font-medium">{Math.round(job.progress || 0)}%</span>
                                        </div>
                                    </motion.div>
                                ))}

                                {/* Pending jobs */}
                                {pendingJobs.map((job, idx) => (
                                    <motion.div
                                        key={job.id}
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1, flex: 0.8 }}
                                        className="h-full bg-gray-700 border-l-2 border-gray-600 flex items-center justify-center cursor-pointer hover:bg-gray-600 transition-colors min-w-[50px]"
                                        onClick={() => onJobClick?.(job.id)}
                                        title={job.prompt || 'Pending...'}
                                    >
                                        <span className="text-xs text-gray-400">#{job.position}</span>
                                    </motion.div>
                                ))}
                            </div>

                            {/* Job List with ETA */}
                            <div className="space-y-1 max-h-32 overflow-y-auto">
                                {queue.map((job) => (
                                    <div
                                        key={job.id}
                                        onClick={() => onJobClick?.(job.id)}
                                        className="flex items-center justify-between px-3 py-2 bg-gray-800/50 rounded-lg hover:bg-gray-700/50 cursor-pointer transition-colors"
                                    >
                                        <div className="flex items-center gap-3 min-w-0">
                                            {job.status === 'running' ? (
                                                <Loader2 className="flex-shrink-0 animate-spin text-blue-400" size={14} />
                                            ) : (
                                                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-700 flex items-center justify-center text-xs text-gray-400">
                                                    {job.position}
                                                </span>
                                            )}
                                            <span className="text-sm text-gray-300 truncate">
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
                                    </div>
                                ))}
                            </div>

                            {/* Footer Stats */}
                            <div className="text-xs text-gray-500 text-center pt-1">
                                Avg. job time: {formatETA(stats.avg_duration_seconds)}
                                {pendingJobs.length > 0 && (
                                    <> • Total wait: ~{formatETA(pendingJobs.reduce((sum, j) => sum + j.eta_seconds, 0))}</>
                                )}
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.div>
    );
});

export default QueueVisualization;
