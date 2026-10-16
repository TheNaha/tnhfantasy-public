import { useState } from 'react';
import {
    Activity,
    AlertCircle,
    Check,
    CheckCircle2,
    ChevronDown,
    ChevronUp,
    Clock,
    Copy,
    FileText,
    Gauge,
    Loader2,
    RefreshCw,
    Rocket,
    Terminal,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { providersApi } from '../../../api';
import { copyToClipboard } from '../../../utils/clipboard';
import { formatTimestamp } from '../../../utils/dateTime';
import { formatBytes } from '../../../utils/bytes';
import { QueryErrorState } from '../../common/QueryState';

export default function LogsTab({ providerId }) {
    const [deployOutputExpanded, setDeployOutputExpanded] = useState(true);
    const [copiedDeploy, setCopiedDeploy] = useState(false);
    const [expandedFailureId, setExpandedFailureId] = useState(null);

    const {
        data,
        isLoading,
        isError,
        error,
        refetch,
        isFetching,
    } = useQuery({
        queryKey: ['provider-logs', providerId],
        queryFn: () => providersApi.getLogs(providerId),
        refetchInterval: 15000,
        enabled: Boolean(providerId),
    });

    const handleCopyDeployLogs = async (text) => {
        if (!text) return;
        const ok = await copyToClipboard(text);
        if (ok) {
            setCopiedDeploy(true);
            setTimeout(() => setCopiedDeploy(false), 2000);
            toast.success('Deployment output copied to clipboard');
        }
    };

    if (isLoading) {
        return (
            <div className="flex h-48 flex-col items-center justify-center gap-3 text-gray-500">
                <Loader2 size={24} className="animate-spin text-blue-400" />
                <p className="text-xs">Loading provider logs & activity…</p>
            </div>
        );
    }

    if (isError) {
        return (
            <div className="py-4">
                <QueryErrorState error={error} noun="provider logs" onRetry={() => refetch()} />
            </div>
        );
    }

    const deploy = data?.deploy;
    const failures = data?.recent_failures || [];
    const recentJobs = data?.recent_jobs || [];
    const diagnostics = data?.diagnostics || {};
    const diagWarnings = diagnostics.warnings || [];
    const diagErrors = diagnostics.errors || [];

    return (
        <div className="space-y-6">
            {/* Header / Refresh Bar */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Terminal size={16} className="text-purple-400" />
                    <h3 className="text-sm font-semibold text-white tracking-wide">
                        Provider Activity & Logs
                    </h3>
                </div>
                <button
                    type="button"
                    onClick={() => refetch()}
                    disabled={isFetching}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors disabled:opacity-50"
                >
                    <RefreshCw size={12} className={isFetching ? 'animate-spin text-blue-400' : ''} />
                    <span>{isFetching ? 'Refreshing…' : 'Refresh'}</span>
                </button>
            </div>

            {/* Section 1: Latest Cloud Deployment */}
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <div className="px-4 py-3 border-b border-white/[0.04] bg-white/[0.01] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Rocket size={15} className="text-purple-400" />
                        <span className="text-xs font-bold uppercase tracking-wider text-gray-300">
                            Latest Cloud Deployment
                        </span>
                    </div>
                    {deploy && (
                        <div className="flex items-center gap-2">
                            {deploy.dry_run && (
                                <span className="text-[11px] uppercase font-mono px-2 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-500/30">
                                    Dry Run
                                </span>
                            )}
                            <span
                                className={`text-[11px] font-semibold px-2 py-0.5 rounded-full flex items-center gap-1 ${
                                    deploy.ok
                                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                        : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                }`}
                            >
                                {deploy.ok ? (
                                    <>
                                        <CheckCircle2 size={11} /> Succeeded
                                    </>
                                ) : (
                                    <>
                                        <AlertCircle size={11} /> Failed (Exit {deploy.exit_code ?? '?'})
                                    </>
                                )}
                            </span>
                        </div>
                    )}
                </div>

                {deploy ? (
                    <div className="p-4 space-y-3">
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                            <div>
                                <span className="text-gray-500 block">Target / Artifact</span>
                                <span className="font-mono text-gray-200">{deploy.target} ({deploy.artifact})</span>
                            </div>
                            <div>
                                <span className="text-gray-500 block">Transport</span>
                                <span className="text-gray-200 capitalize">{deploy.transport}</span>
                            </div>
                            <div>
                                <span className="text-gray-500 block">Duration</span>
                                <span className="font-mono text-gray-200">{deploy.elapsed_seconds}s</span>
                            </div>
                            <div>
                                <span className="text-gray-500 block">Timestamp</span>
                                <span className="text-gray-200">{deploy.timestamp ? formatTimestamp(deploy.timestamp) : 'N/A'}</span>
                            </div>
                        </div>

                        {/* Terminal Output Viewer */}
                        {deploy.output && (
                            <div className="mt-3">
                                <div className="flex items-center justify-between pb-2">
                                    <button
                                        type="button"
                                        onClick={() => setDeployOutputExpanded(!deployOutputExpanded)}
                                        className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                                    >
                                        {deployOutputExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                        <span>Build & Deployment Output</span>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => handleCopyDeployLogs(deploy.output)}
                                        className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-white transition-colors px-2 py-0.5 rounded hover:bg-white/5"
                                    >
                                        {copiedDeploy ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                        <span>{copiedDeploy ? 'Copied' : 'Copy Output'}</span>
                                    </button>
                                </div>
                                {deployOutputExpanded && (
                                    <pre className="font-mono text-xs bg-black/80 border border-white/5 rounded-xl p-3 text-gray-300 max-h-64 overflow-y-auto whitespace-pre-wrap leading-relaxed shadow-inner">
                                        {deploy.output}
                                    </pre>
                                )}
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="p-6 text-center text-xs text-gray-500">
                        No deployments have been executed for this provider yet.
                    </div>
                )}
            </div>

            {/* Section 2: Recent Job Performance & Transfer Breakdown */}
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <div className="px-4 py-3 border-b border-white/[0.04] bg-white/[0.01] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Gauge size={15} className="text-cyan-400" />
                        <span className="text-xs font-bold uppercase tracking-wider text-gray-300">
                            Recent Job Latency & Transfer Breakdown ({recentJobs.length})
                        </span>
                    </div>
                </div>

                {recentJobs.length > 0 ? (
                    <div className="divide-y divide-white/[0.03]">
                        {recentJobs.map((j) => {
                            const timings = j.timings;
                            const hasTimings = timings && (timings.inference_seconds || timings.transfer_seconds);
                            const totalTime = timings?.total_seconds || j.duration_seconds || 0;
                            const inferenceTime = timings?.inference_seconds || Math.max(0, totalTime - (timings?.transfer_seconds || 0));
                            const transferTime = timings?.transfer_seconds || 0;
                            const inferencePct = totalTime > 0 ? Math.min(100, Math.max(5, (inferenceTime / totalTime) * 100)) : 100;
                            const transferPct = totalTime > 0 && transferTime > 0 ? Math.min(100, Math.max(5, (transferTime / totalTime) * 100)) : 0;
                            const isWebp = timings?.transfer_format === 'webp';
                            const isSuccess = j.status === 'completed' || j.status === 'success';

                            return (
                                <div key={j.id} className="p-4 hover:bg-white/[0.01] transition-colors space-y-2.5">
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                        <div className="flex items-center gap-2">
                                            <span className={`w-2 h-2 rounded-full ${isSuccess ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]' : 'bg-rose-400'}`} />
                                            <span className="font-mono text-xs font-semibold text-gray-200">
                                                Job {j.id.slice(0, 8)}…
                                            </span>
                                            <span className="text-2xs uppercase font-mono px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
                                                {j.task_type || 'image'}
                                            </span>
                                            {isWebp && (
                                                <span className="text-2xs font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" title="Wire optimized: WebP transport saves ~80% network transfer time">
                                                    ⚡ WebP Wire
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-3 text-xs">
                                            {j.created_at && (
                                                <span className="text-gray-500 flex items-center gap-1 text-2xs">
                                                    <Clock size={11} />
                                                    {formatTimestamp(j.created_at)}
                                                </span>
                                            )}
                                            <span className="font-mono font-semibold text-gray-200 bg-black/40 px-2 py-0.5 rounded border border-white/5">
                                                {totalTime > 0 ? `${totalTime.toFixed(1)}s total` : '—'}
                                            </span>
                                        </div>
                                    </div>

                                    {/* Dual-tone Progress Bar: Inference vs Transfer */}
                                    {hasTimings && totalTime > 0 && (
                                        <div className="space-y-1.5">
                                            <div className="h-2 w-full bg-black/60 rounded-full overflow-hidden flex shadow-inner border border-white/5">
                                                <div
                                                    style={{ width: `${inferencePct}%` }}
                                                    className="bg-blue-500 h-full transition-all"
                                                    title={`Model Inference: ${inferenceTime.toFixed(1)}s`}
                                                />
                                                {transferPct > 0 && (
                                                    <div
                                                        style={{ width: `${transferPct}%` }}
                                                        className="bg-emerald-400 h-full transition-all"
                                                        title={`Wire Transfer: ${transferTime.toFixed(2)}s`}
                                                    />
                                                )}
                                            </div>
                                            <div className="flex items-center justify-between text-2xs font-mono">
                                                <div className="flex items-center gap-1.5 text-blue-400">
                                                    <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                                                    <span>Inference: {inferenceTime.toFixed(1)}s</span>
                                                </div>
                                                <div className="flex items-center gap-1.5 text-emerald-400">
                                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                                    <span>
                                                        Transfer: {transferTime.toFixed(2)}s
                                                        {timings?.transfer_bytes ? ` (${formatBytes(timings.transfer_bytes)})` : ''}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {!hasTimings && (
                                        <div className="text-2xs text-gray-500 font-mono">
                                            Duration: {j.duration_seconds !== null ? `${j.duration_seconds}s` : 'Unknown'}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <div className="p-6 text-center text-xs text-gray-500 flex flex-col items-center gap-2">
                        <Clock size={24} className="text-gray-600" />
                        <span>No completed job history recorded for this provider yet.</span>
                    </div>
                )}
            </div>

            {/* Section 3: Recent Job Failures & Errors */}
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <div className="px-4 py-3 border-b border-white/[0.04] bg-white/[0.01] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <AlertCircle size={15} className="text-rose-400" />
                        <span className="text-xs font-bold uppercase tracking-wider text-gray-300">
                            Recent Job Execution Failures ({failures.length})
                        </span>
                    </div>
                </div>

                {failures.length > 0 ? (
                    <div className="divide-y divide-white/[0.03]">
                        {failures.map((f) => {
                            const isExpanded = expandedFailureId === f.id;
                            return (
                                <div key={f.id} className="p-4 hover:bg-white/[0.01] transition-colors">
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-2">
                                                <span className="font-mono text-xs font-semibold text-rose-300 truncate">
                                                    Job {f.id.slice(0, 8)}…
                                                </span>
                                                <span className="text-[11px] uppercase font-mono px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">
                                                    {f.task_type || 'image'}
                                                </span>
                                                {f.completed_at && (
                                                    <span className="text-[11px] text-gray-500 flex items-center gap-1">
                                                        <Clock size={11} />
                                                        {formatTimestamp(f.completed_at)}
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-xs text-gray-300 mt-1 line-clamp-2 font-mono bg-rose-500/5 p-1.5 rounded border border-rose-500/10">
                                                {f.error || f.message || 'Execution failed without error message'}
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setExpandedFailureId(isExpanded ? null : f.id)}
                                            className="text-gray-500 hover:text-white p-1 rounded hover:bg-white/5 transition-colors"
                                            aria-label="Toggle failure details"
                                        >
                                            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                        </button>
                                    </div>
                                    {isExpanded && (
                                        <div className="mt-2 pt-2 border-t border-white/[0.04]">
                                            <div className="flex items-center justify-between text-[11px] text-gray-500 mb-1">
                                                <span>Full Error Trace:</span>
                                                <button
                                                    type="button"
                                                    onClick={() => handleCopyDeployLogs(f.error || f.message || '')}
                                                    className="inline-flex items-center gap-1 text-gray-400 hover:text-white"
                                                >
                                                    <Copy size={11} /> Copy
                                                </button>
                                            </div>
                                            <pre className="font-mono text-[11px] bg-black/60 p-2.5 rounded-lg text-rose-200/90 whitespace-pre-wrap max-h-48 overflow-y-auto">
                                                {f.error || f.message}
                                            </pre>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <div className="p-6 text-center text-xs text-gray-500 flex flex-col items-center gap-2">
                        <CheckCircle2 size={24} className="text-emerald-500/40" />
                        <span>No recent job failures on record for this provider.</span>
                    </div>
                )}
            </div>

            {/* Section 3: Health Probe Warnings & Alerts */}
            {(diagWarnings.length > 0 || diagErrors.length > 0) && (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 space-y-2">
                    <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-amber-300">
                        <Activity size={14} className="text-amber-400" />
                        <span>Health Diagnostics & Warnings</span>
                    </div>
                    {diagErrors.map((err, idx) => (
                        <div key={`err-${idx}`} className="text-xs text-rose-300 bg-rose-500/10 p-2 rounded border border-rose-500/20">
                            {err}
                        </div>
                    ))}
                    {diagWarnings.map((warn, idx) => (
                        <div key={`warn-${idx}`} className="text-xs text-amber-200/90 bg-amber-500/10 p-2 rounded border border-amber-500/20">
                            {warn}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
