import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
    Clock,
    Play,
    Pause,
    RefreshCw,
    Loader2,
    CheckCircle2,
    AlertTriangle,
    Activity,
    Cpu,
    Server,
    Layers,
    Sliders,
    Zap,
    RotateCw,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { settingsApi } from '../api/settingsApi';
import { api } from '../api';
import * as ws from '../api/websocket';
import { QueryErrorState } from '../components/common/QueryState';

const INTERVAL_PRESETS = [
    { label: '1m', seconds: 60 },
    { label: '5m', seconds: 300 },
    { label: '15m', seconds: 900 },
    { label: '1h', seconds: 3600 },
    { label: '6h', seconds: 21600 },
    { label: '24h', seconds: 86400 },
    { label: '48h', seconds: 172800 },
];

function formatTime(iso) {
    if (!iso) return 'Never';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return iso;
    }
}

function formatRelativeNext(iso) {
    if (!iso) return 'Paused / None';
    try {
        const target = new Date(iso).getTime();
        const diffMs = target - Date.now();
        if (diffMs <= 0) return 'Due now';
        const diffSec = Math.round(diffMs / 1000);
        if (diffSec < 60) return `in ${diffSec}s`;
        const diffMin = Math.round(diffSec / 60);
        if (diffMin < 60) return `in ${diffMin}m`;
        const diffHr = (diffMin / 60).toFixed(1);
        return `in ${diffHr}h`;
    } catch {
        return iso;
    }
}

function formatInterval(seconds) {
    if (!seconds) return 'Cron / Event';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
    return `${(seconds / 86400).toFixed(1)}d`;
}

function formatJobResultSummary(result) {
    if (!result || typeof result !== 'object') return 'Completed';
    if (result.success != null || result.failed != null) {
        return `${result.success ?? 0} updated, ${result.failed ?? 0} failed`;
    }
    if (result.warmed != null) {
        return `${result.warmed} preview(s) cached, ${result.misses ?? 0} misses`;
    }
    if (result.stale_reaped != null) {
        return `${result.stale_reaped} stale, ${result.stranded_reaped ?? 0} stranded reaped`;
    }
    if (result.orphaned_models_removed != null) {
        return `${result.orphaned_models_removed} orphaned models cleaned`;
    }
    const entries = Object.entries(result).filter(([k]) => k !== 'status');
    if (entries.length > 0) {
        return entries.slice(0, 2).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`).join(', ');
    }
    return result.status ? `Status: ${result.status}` : 'Completed';
}

function StatusBadge({ status, paused }) {
    if (paused) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-gray-500/20 border border-gray-500/30 text-gray-400">
                <Pause size={10} /> Paused
            </span>
        );
    }
    switch (status) {
        case 'running':
            return (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-blue-500/20 border border-blue-500/40 text-blue-400 animate-pulse">
                    <Loader2 size={10} className="animate-spin" /> Running
                </span>
            );
        case 'success':
            return (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                    <CheckCircle2 size={10} /> Success
                </span>
            );
        case 'failed':
            return (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-red-500/15 border border-red-500/30 text-red-400">
                    <AlertTriangle size={10} /> Failed
                </span>
            );
        case 'skipped':
            return (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-amber-500/15 border border-amber-500/30 text-amber-300">
                    Skipped (Locked)
                </span>
            );
        default:
            return (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-gray-500/15 border border-gray-500/30 text-gray-400">
                    Idle
                </span>
            );
    }
}

export default function BackgroundTasks() {
    const queryClient = useQueryClient();
    const [editingJobId, setEditingJobId] = useState(null);
    const [customIntervals, setCustomIntervals] = useState({});
    const [resyncProgress, setResyncProgress] = useState(null);

    const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
        queryKey: ['scheduler_status'],
        queryFn: ({ signal }) => settingsApi.getSchedulerStatus({ signal }),
        refetchInterval: 5000,
    });

    // WebSocket real-time progress for metadata resync
    useEffect(() => {
        const handleProgress = (payload) => {
            setResyncProgress(payload);
            if (payload?.status === 'completed') {
                queryClient.invalidateQueries({ queryKey: ['scheduler_status'] });
                toast.success('Metadata resync completed!');
            }
        };

        ws.on('RESYNC_PROGRESS', handleProgress);
        return () => ws.off('RESYNC_PROGRESS', handleProgress);
    }, [queryClient]);

    const runJobMutation = useMutation({
        mutationFn: (jobId) => settingsApi.runSchedulerJob(jobId),
        onSuccess: (res, jobId) => {
            toast.success(`Job "${jobId}" triggered`);
            queryClient.invalidateQueries({ queryKey: ['scheduler_status'] });
        },
        onError: (err, jobId) => {
            toast.error(`Failed to run "${jobId}": ${err.message}`);
        },
    });

    const updateJobMutation = useMutation({
        mutationFn: ({ jobId, data }) => settingsApi.updateSchedulerJob(jobId, data),
        onSuccess: (res, { jobId }) => {
            toast.success(`Job "${jobId}" updated`);
            setEditingJobId(null);
            queryClient.invalidateQueries({ queryKey: ['scheduler_status'] });
        },
        onError: (err, { jobId }) => {
            toast.error(`Update failed for "${jobId}": ${err.message}`);
        },
    });

    const triggerResyncMutation = useMutation({
        mutationFn: ({ mode, sampleSize }) => api.post('/api/v2/models/maintenance/resync-all', {
            mode,
            sample_size: sampleSize,
        }),
        onSuccess: (res, { mode }) => {
            if (res.status === 'already_running') {
                toast('Resync is already in progress.', { icon: 'ℹ️' });
            } else {
                toast.success(`Started ${mode === 'random' ? 'random batch' : 'full'} resync!`);
            }
            queryClient.invalidateQueries({ queryKey: ['scheduler_status'] });
        },
        onError: (err) => {
            toast.error(`Failed to start resync: ${err.message}`);
        },
    });

    if (isError) {
        return (
            <div className="p-6 max-w-7xl mx-auto">
                <QueryErrorState noun="background tasks" error={error} onRetry={refetch} />
            </div>
        );
    }

    const jobs = data?.jobs || [];
    const activeTasks = data?.active_tasks || [];
    const workerPools = data?.worker_pools || {};
    const resyncStatus = data?.resync_status || {};
    const isResyncActive = resyncStatus?.in_progress || resyncProgress?.status === 'processing';
    const currentProgress = resyncProgress || (isResyncActive ? resyncStatus : null);

    return (
        <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-8 animate-fade-in">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-800 pb-6">
                <div>
                    <h1 className="text-2xl md:text-3xl font-bold text-white flex items-center gap-3">
                        <Clock className="text-blue-400" size={32} />
                        Background Tasks Control Center
                    </h1>
                    <p className="text-sm text-gray-400 mt-1">
                        Monitor, force-run, and dynamically tune background recurring jobs and asynchronous workers.
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => refetch()}
                        disabled={isFetching}
                        aria-label="Refresh background tasks"
                        className="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 rounded-xl text-sm font-semibold flex items-center gap-2 transition-all disabled:opacity-50"
                    >
                        <RefreshCw size={16} className={isFetching ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {/* Quick-Launch Resync Card */}
            <div className="bg-gradient-to-br from-blue-950/40 via-gray-900 to-gray-900 border border-blue-900/40 rounded-2xl p-6 shadow-xl relative overflow-hidden">
                <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                    <div className="space-y-2 max-w-xl">
                        <div className="flex items-center gap-2">
                            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-400 border border-blue-500/30">
                                Civitai Metadata Resync
                            </span>
                            {isResyncActive && (
                                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse">
                                    Resync Active
                                </span>
                            )}
                        </div>
                        <h2 className="text-lg md:text-xl font-bold text-white">
                            Dual-Variant Model Metadata Sync
                        </h2>
                        <p className="text-xs md:text-sm text-gray-400">
                            Run a rapid 5-model random batch refresh or launch an exhaustive deep crawl across all installed models without blocking foreground operations.
                        </p>
                        {resyncStatus?.last_completed_at && !isResyncActive && (
                            <div className="text-xs text-gray-500 flex items-center gap-1.5 pt-1">
                                <CheckCircle2 size={12} className="text-emerald-500" />
                                Last completed: {formatTime(resyncStatus.last_completed_at)}
                            </div>
                        )}
                    </div>

                    <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
                        <button
                            onClick={() => triggerResyncMutation.mutate({ mode: 'random', sampleSize: 5 })}
                            disabled={isResyncActive || triggerResyncMutation.isPending}
                            aria-label="Run random batch metadata resync for 5 models"
                            className="flex-1 md:flex-none px-4 py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 disabled:opacity-50 text-white rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all shadow-sm"
                        >
                            <Zap size={16} className="text-amber-400" />
                            Random Batch (5 Models)
                        </button>
                        <button
                            onClick={() => triggerResyncMutation.mutate({ mode: 'full' })}
                            disabled={isResyncActive || triggerResyncMutation.isPending}
                            aria-label="Run full deep metadata resync for all models"
                            className="flex-1 md:flex-none px-4 py-2.5 bg-blue-600 hover:bg-blue-500 border border-blue-500/50 disabled:opacity-50 text-white rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-900/30"
                        >
                            <RotateCw size={16} />
                            Full Deep Resync (All)
                        </button>
                    </div>
                </div>

                {/* Active Resync Progress Bar */}
                {isResyncActive && currentProgress && (
                    <div className="mt-6 pt-6 border-t border-gray-800/80 space-y-3">
                        <div className="flex items-center justify-between text-xs text-gray-300">
                            <span className="font-medium text-white truncate max-w-md">
                                Processing: <span className="text-blue-400 font-mono">{currentProgress.current_model || 'Connecting...'}</span>
                            </span>
                            <span className="font-mono text-gray-400">
                                {currentProgress.processed || 0} / {currentProgress.total || 0} ({Math.round(((currentProgress.processed || 0) / Math.max(1, currentProgress.total || 1)) * 100)}%)
                            </span>
                        </div>
                        <div className="w-full bg-gray-800 rounded-full h-2.5 overflow-hidden border border-gray-700">
                            <div
                                className="bg-gradient-to-r from-blue-600 to-indigo-500 h-full transition-all duration-300 rounded-full"
                                style={{ width: `${Math.max(5, ((currentProgress.processed || 0) / Math.max(1, currentProgress.total || 1)) * 100)}%` }}
                            />
                        </div>
                        <div className="flex items-center gap-4 text-2xs text-gray-400 pt-1">
                            <span className="text-emerald-400 font-bold">{currentProgress.results?.success || 0} succeeded</span>
                            <span className="text-red-400 font-bold">{currentProgress.results?.failed || 0} failed</span>
                            <span className="text-gray-500">Mode: {currentProgress.mode || 'full'}</span>
                        </div>
                    </div>
                )}
            </div>

            {/* Scheduled Periodic Jobs Section */}
            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-white flex items-center gap-2">
                            <Sliders size={20} className="text-indigo-400" />
                            Scheduled Recurring Jobs
                        </h2>
                        <p className="text-xs text-gray-400 mt-0.5">
                            APScheduler interval and cron timers running on background threads.
                        </p>
                    </div>
                    <span className="text-xs text-gray-500 font-mono">
                        {jobs.length} registered
                    </span>
                </div>

                {isLoading ? (
                    <div className="p-12 text-center text-gray-400 flex flex-col items-center justify-center gap-3 bg-gray-900/50 rounded-2xl border border-gray-800">
                        <Loader2 size={32} className="animate-spin text-blue-500" />
                        <span className="text-sm font-medium">Loading background schedules...</span>
                    </div>
                ) : jobs.length === 0 ? (
                    <div className="p-8 text-center text-gray-500 bg-gray-900/30 rounded-2xl border border-gray-800 text-sm">
                        No scheduled jobs registered.
                    </div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {jobs.map((job) => {
                            const isEditing = editingJobId === job.id;
                            const currentInterval = customIntervals[job.id] ?? (job.interval_seconds || 300);

                            return (
                                <div
                                    key={job.id}
                                    className="bg-gray-900/90 border border-gray-800 hover:border-gray-700/80 rounded-2xl p-5 flex flex-col justify-between space-y-4 transition-all shadow-md group"
                                >
                                    <div className="space-y-3">
                                        <div className="flex items-start justify-between gap-2">
                                            <div className="space-y-1 min-w-0">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <span className="text-xs font-semibold text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
                                                        {job.category || 'General'}
                                                    </span>
                                                    <span className="text-2xs font-mono text-gray-500">
                                                        {job.id}
                                                    </span>
                                                </div>
                                                <h3 className="font-bold text-white text-base truncate" title={job.title || job.name}>
                                                    {job.title || job.name}
                                                </h3>
                                            </div>
                                            <StatusBadge status={job.last_status} paused={job.paused} />
                                        </div>

                                        <p className="text-xs text-gray-400 line-clamp-2 leading-relaxed">
                                            {job.description || 'Periodic background maintenance task.'}
                                        </p>

                                        <div className="grid grid-cols-2 gap-2 text-2xs pt-2 border-t border-gray-800/80">
                                            <div className="bg-gray-800/40 p-2 rounded-lg border border-gray-800">
                                                <span className="text-gray-500 block">Frequency</span>
                                                <span className="font-medium text-gray-200">
                                                    {formatInterval(job.interval_seconds)}
                                                </span>
                                            </div>
                                            <div className="bg-gray-800/40 p-2 rounded-lg border border-gray-800">
                                                <span className="text-gray-500 block">Next Fire</span>
                                                <span className="font-medium text-gray-200">
                                                    {formatRelativeNext(job.next_run)}
                                                </span>
                                            </div>
                                            <div className="bg-gray-800/40 p-2 rounded-lg border border-gray-800">
                                                <span className="text-gray-500 block">Last Run</span>
                                                <span className="font-medium text-gray-200">
                                                    {formatTime(job.last_run_at)}
                                                </span>
                                            </div>
                                            <div className="bg-gray-800/40 p-2 rounded-lg border border-gray-800">
                                                <span className="text-gray-500 block">Duration</span>
                                                <span className="font-medium text-gray-200">
                                                    {job.last_duration_seconds ? `${job.last_duration_seconds}s` : '—'}
                                                </span>
                                            </div>
                                        </div>

                                        {job.last_result && (
                                            <div className="pt-2 border-t border-gray-800/80">
                                                <details className="group/details">
                                                    <summary className="cursor-pointer text-2xs text-gray-400 hover:text-gray-200 flex items-center justify-between font-mono select-none">
                                                        <span className="flex items-center gap-1.5 text-emerald-400 truncate pr-2">
                                                            <CheckCircle2 size={11} className="shrink-0" />
                                                            <span className="truncate">{formatJobResultSummary(job.last_result)}</span>
                                                        </span>
                                                        <span className="text-gray-500 text-3xs group-open/details:rotate-180 transition-transform shrink-0">▼</span>
                                                    </summary>
                                                    <pre className="mt-2 p-2.5 bg-black/70 border border-gray-800 rounded-lg text-2xs font-mono text-emerald-300/90 overflow-x-auto max-h-36 custom-scrollbar whitespace-pre-wrap">
                                                        {JSON.stringify(job.last_result, null, 2)}
                                                    </pre>
                                                </details>
                                            </div>
                                        )}

                                        {job.last_error && (
                                            <div className="p-2 bg-red-500/10 border border-red-500/20 rounded-lg text-2xs text-red-400 truncate" title={job.last_error}>
                                                Error: {job.last_error}
                                            </div>
                                        )}
                                    </div>

                                    {/* Action Bar */}
                                    <div className="pt-3 border-t border-gray-800/80 space-y-3">
                                        {isEditing ? (
                                            <div className="space-y-2 bg-gray-950/60 p-3 rounded-xl border border-gray-800">
                                                <div className="text-2xs font-semibold text-gray-300 uppercase tracking-wider">
                                                    Select Frequency
                                                </div>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {INTERVAL_PRESETS.map((preset) => (
                                                        <button
                                                            key={preset.label}
                                                            type="button"
                                                            onClick={() => setCustomIntervals(prev => ({ ...prev, [job.id]: preset.seconds }))}
                                                            className={`px-2 py-1 text-2xs rounded-md font-medium transition-all ${
                                                                currentInterval === preset.seconds
                                                                    ? 'bg-blue-600 text-white font-bold'
                                                                    : 'bg-gray-800 text-gray-400 hover:text-white'
                                                            }`}
                                                        >
                                                            {preset.label}
                                                        </button>
                                                    ))}
                                                </div>
                                                <div className="flex items-center gap-2 pt-2">
                                                    <input
                                                        type="number"
                                                        min="10"
                                                        max="604800"
                                                        value={currentInterval}
                                                        onChange={(e) => setCustomIntervals(prev => ({ ...prev, [job.id]: parseInt(e.target.value, 10) || 60 }))}
                                                        className="w-24 px-2 py-1 text-xs bg-gray-900 border border-gray-700 rounded text-white"
                                                        placeholder="seconds"
                                                    />
                                                    <span className="text-2xs text-gray-400">sec</span>
                                                    <button
                                                        onClick={() => updateJobMutation.mutate({ jobId: job.id, data: { interval_seconds: currentInterval } })}
                                                        disabled={updateJobMutation.isPending}
                                                        aria-label={`Apply interval ${currentInterval} seconds for ${job.id}`}
                                                        className="ml-auto px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded transition-all"
                                                    >
                                                        Save
                                                    </button>
                                                    <button
                                                        onClick={() => setEditingJobId(null)}
                                                        aria-label="Cancel editing interval"
                                                        className="px-2 py-1 text-xs text-gray-400 hover:text-white"
                                                    >
                                                        Cancel
                                                    </button>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="flex items-center justify-between gap-2">
                                                <button
                                                    onClick={() => runJobMutation.mutate(job.id)}
                                                    disabled={runJobMutation.isPending || job.last_status === 'running'}
                                                    aria-label={`Run scheduled job ${job.title || job.name} now`}
                                                    className="flex-1 px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 text-blue-400 hover:text-blue-300 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all disabled:opacity-50"
                                                >
                                                    <Play size={12} />
                                                    Run Now
                                                </button>
                                                <button
                                                    onClick={() => updateJobMutation.mutate({ jobId: job.id, data: { paused: !job.paused } })}
                                                    disabled={updateJobMutation.isPending}
                                                    aria-label={job.paused ? `Resume job ${job.id}` : `Pause job ${job.id}`}
                                                    className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all"
                                                    title={job.paused ? 'Resume schedule' : 'Pause schedule'}
                                                >
                                                    {job.paused ? <Play size={12} className="text-emerald-400" /> : <Pause size={12} />}
                                                    {job.paused ? 'Resume' : 'Pause'}
                                                </button>
                                                <button
                                                    onClick={() => {
                                                        setEditingJobId(job.id);
                                                        setCustomIntervals(prev => ({ ...prev, [job.id]: job.interval_seconds || 300 }));
                                                    }}
                                                    aria-label={`Configure interval for ${job.title || job.name}`}
                                                    className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-800 rounded-xl transition-all"
                                                    title="Adjust interval"
                                                >
                                                    <Sliders size={14} />
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* Bottom Row: Active Coroutines & Queue Worker Pools */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Active Coroutines */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
                    <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                        <div className="flex items-center gap-2">
                            <Activity size={18} className="text-emerald-400" />
                            <h3 className="font-bold text-white text-base">Active Tracked Coroutines</h3>
                        </div>
                        <span className="text-xs text-gray-400 font-mono">
                            {activeTasks.length} running
                        </span>
                    </div>

                    {activeTasks.length === 0 ? (
                        <div className="text-xs text-gray-500 py-6 text-center">
                            No active non-daemon background tasks.
                        </div>
                    ) : (
                        <div className="space-y-2">
                            {activeTasks.map((t, idx) => (
                                <div
                                    key={idx}
                                    className="p-2.5 bg-gray-800/40 rounded-xl border border-gray-800 flex items-center justify-between text-xs"
                                >
                                    <div className="flex items-center gap-2 min-w-0">
                                        <Loader2 size={12} className="animate-spin text-emerald-400 flex-shrink-0" />
                                        <span className="font-mono text-gray-200 truncate">{t.name}</span>
                                    </div>
                                    <span className="px-2 py-0.5 rounded text-2xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                        Running
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Worker Pools */}
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
                    <div className="flex items-center justify-between border-b border-gray-800 pb-3">
                        <div className="flex items-center gap-2">
                            <Cpu size={18} className="text-purple-400" />
                            <h3 className="font-bold text-white text-base">In-Process Job Queue Pools</h3>
                        </div>
                        <span className="text-xs text-gray-400 font-mono">
                            {Object.keys(workerPools).length} pools
                        </span>
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        {Object.entries(workerPools).map(([name, info]) => (
                            <div key={name} className="p-3 bg-gray-800/40 rounded-xl border border-gray-800 space-y-2">
                                <div className="text-xs font-bold text-white uppercase tracking-wider flex items-center justify-between">
                                    <span>{name}</span>
                                    <Layers size={12} className="text-purple-400" />
                                </div>
                                <div className="text-2xs space-y-1 text-gray-400">
                                    <div className="flex justify-between">
                                        <span>Max Workers:</span>
                                        <span className="font-mono text-white font-semibold">{info.max_workers}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Active:</span>
                                        <span className="font-mono text-emerald-400 font-semibold">{info.active_workers}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Queued:</span>
                                        <span className="font-mono text-amber-400 font-semibold">{info.queued}</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
