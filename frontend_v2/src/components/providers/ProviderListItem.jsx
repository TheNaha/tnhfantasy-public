import React, { useMemo, useState } from 'react';
import {
    Activity,
    Circle,
    Cpu,
    Edit2,
    Loader2,
    Power,
    PowerOff,
    Rocket,
    Server,
    Trash2,
    ChevronRight,
    Zap,
} from 'lucide-react';
import {
    providerBadgeToneClass,
    summarizeProviderStatus,
    getDeployTargetForProvider,
} from '../../utils/providerStatus';
import { providersApi } from '../../api';
import { formatBytes, MB } from '../../utils/bytes';

const EMPTY_OBJECT = Object.freeze({});

function statusColorByTone(tone) {
    const map = {
        online: 'text-green-400',
        offline: 'text-gray-500',
        deploying: 'text-purple-400',
        syncing: 'text-blue-400',
        downloading: 'text-cyan-400',
        warning: 'text-amber-300',
        failed: 'text-red-400',
        working: 'text-sky-300',
    };
    return map[tone] || map.offline;
}

/**
 * A three-point sparkline, in eight lines of SVG.
 *
 * This rendered through `recharts` (`LineChart`/`Line`/`ResponsiveContainer`/
 * `YAxis`) into a `h-6 w-12` box — 290.37 kB raw / 88.56 kB gzip. Rollup already
 * kept that out of the app shell, but `ProviderListItem` imports it statically,
 * so opening /providers downloaded the whole library to draw two trend lines;
 * `src/pages/Statistics.jsx` is the one consumer that genuinely needs it, and it
 * now has the library to itself behind `vendor-charts`.
 *
 * The same shape it drew before: `domain`-scaled into a 0..100 viewport,
 * `preserveAspectRatio="none"` so a non-square box stretches rather than
 * letterboxes (what `ResponsiveContainer` does), and
 * `vectorEffect="non-scaling-stroke"` so the 1.5px line stays 1.5px instead of
 * being scaled with the box. The gentle `monotone` curve between points is
 * deliberately not reproduced — at 48x24 it was never visible, and a polyline
 * cannot interpolate.
 */
function SparkLine({ data, color, label, domain = [0, 100] }) {
    const points = useMemo(() => {
        if (!data || data.length === 0) return null;
        const [low, high] = domain;
        const span = high - low || 1;
        const step = data.length > 1 ? 100 / (data.length - 1) : 100;
        return data
            .map((v, i) => {
                const clamped = Math.min(Math.max(Number(v) || 0, low), high);
                return `${(i * step).toFixed(2)},${(100 - ((clamped - low) / span) * 100).toFixed(2)}`;
            })
            .join(' ');
    }, [data, domain]);

    if (!points) return null;
    return (
        <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="h-6 w-12"
            role="img"
            aria-label={label}
        >
            <polyline
                points={points}
                fill="none"
                stroke={color}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
            />
        </svg>
    );
}

function ProviderListItem({
    provider,
    loading,
    actionLabel = null,
    isSelected,
    onSelect,
    onToggleEnabled,
    onEdit,
    onDelete,
    onDeploy,
    providerFailures = 0,
    jobsAssigned = 0,
}) {
    const runtime = provider.runtime_state ?? EMPTY_OBJECT;
    const credentialSummary = provider.credential_summary ?? EMPTY_OBJECT;
    const diagnostics = provider.diagnostics ?? EMPTY_OBJECT;
    const reconciliation = provider.reconciliation_state ?? EMPTY_OBJECT;

    const runtimeStatus = runtime.status || (runtime.connected ? 'active' : 'stopped');
    const currentAction = actionLabel || loading || null;

    const statusSummary = useMemo(
        () => summarizeProviderStatus(provider, {
            actionLabel: currentAction,
            jobsAssigned,
            providerFailures,
        }),
        [currentAction, jobsAssigned, provider, providerFailures],
    );

    const hasIssues = (diagnostics.warnings?.length || 0) > 0
        || (diagnostics.errors?.length || 0) > 0
        || providerFailures > 0;

    const isReconciling = reconciliation.status === 'reconciling' || reconciliation.status === 'queued';

    const telemetry = provider.runtime_state?.telemetry || provider.diagnostics?.telemetry || provider.hardware_telemetry || {};
    const vramHistory = telemetry.vram_history || [];
    const tempHistory = telemetry.gpu_temp_history || [];
    const detectedGpu = telemetry.detected_gpu;
    const warmWorkload = telemetry.warm_workload;
    const components = telemetry.components;

    const [pingState, setPingState] = useState({ latency: null, pinging: false, error: null });

    const handlePing = async (e) => {
        e.stopPropagation();
        setPingState({ latency: null, pinging: true, error: null });
        try {
            const res = await providersApi.testProvider(provider.id);
            const lat = res?.latency_ms ?? res?.data?.latency_ms ?? res?.details?.latency_ms ?? res?.data?.details?.latency_ms;
            setPingState({ latency: lat ?? null, pinging: false, error: null });
        } catch (err) {
            setPingState({ latency: null, pinging: false, error: err?.message || 'Failed' });
        }
    };

    return (
        <div
            className={`group rounded-2xl border px-5 py-4 transition-all duration-300 ${
                isSelected
                    ? 'border-blue-500/50 bg-[#0B0E14] shadow-[0_0_20px_rgba(59,130,246,0.15)] scale-[1.01] z-10 relative'
                    : provider.enabled
                        ? 'border-white/5 bg-[#0B0E14]/60 hover:bg-[#0B0E14]/80 hover:border-white/10 hover:shadow-lg backdrop-blur-sm'
                        : 'border-white/5 bg-[#0B0E14]/30 opacity-60 hover:opacity-80 backdrop-blur-sm'
            } cursor-pointer`}
            onClick={() => onSelect?.(provider.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && onSelect?.(provider.id)}
        >
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                {/* `sm:min-w-[14rem]` is load-bearing. `min-w-0` alone sets this
                    column's automatic minimum to 0, so in the `sm:flex-row` card
                    the sibling row of `flex-shrink-0` status badges (~662px)
                    takes the entire 704px card and the provider's name and
                    description render at **0px** — the card shows a badge and no
                    title at all from 640px upward, which is every tablet. The
                    floor is below the badge row's worst case, so the name keeps a
                    readable width instead of collapsing. */}
                <div className="flex items-center gap-4 w-full sm:w-auto sm:min-w-[14rem] flex-1 min-w-0">
                    {/* Status indicator + icon */}
                    <div className="relative flex-shrink-0">
                        <div className={`flex h-12 w-12 items-center justify-center rounded-2xl border shadow-inner ${
                            runtimeStatus === 'running' || runtimeStatus === 'active'
                                ? 'border-green-500/30 bg-green-500/10 shadow-[inset_0_0_15px_rgba(34,197,94,0.1)]'
                                : runtimeStatus === 'failed'
                                    ? 'border-red-500/30 bg-red-500/10 shadow-[inset_0_0_15px_rgba(239,68,68,0.1)]'
                                    : 'border-white/5 bg-white/5'
                        }`}>
                            <Server
                                size={20}
                                className={
                                    runtimeStatus === 'running' || runtimeStatus === 'active'
                                        ? 'text-green-400 drop-shadow-[0_0_8px_rgba(34,197,94,0.5)]'
                                        : runtimeStatus === 'failed'
                                            ? 'text-red-400 drop-shadow-[0_0_8px_rgba(239,68,68,0.5)]'
                                            : 'text-gray-500'
                                }
                            />
                        </div>
                        {/* Tiny status dot */}
                        <Circle
                            size={10}
                            className={`fill-current absolute -right-1 -top-1 border-2 border-[#0B0E14] rounded-full drop-shadow-md ${statusColorByTone(statusSummary.dotTone)}`}
                        />
                    </div>

                    {/* Provider info — name + subtitle */}
                    <div className="min-w-0 flex-1 pl-2">
                        <div className="flex flex-wrap items-center gap-2.5 mb-1">
                        <h3 className="truncate text-base font-bold text-white tracking-wide">
                            {provider.id}
                        </h3>
                        <span className="flex-shrink-0 rounded-lg bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-indigo-300 shadow-inner">
                            P{provider.priority}
                        </span>
                        {!provider.enabled && (
                            <span
                                className="flex-shrink-0 rounded-lg bg-gray-500/10 border border-gray-500/20 px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-gray-400 shadow-inner"
                                title="Intentionally paused. Excluded from load balancer routing."
                            >
                                Paused
                            </span>
                        )}
                        {!['online', 'offline', 'configured', 'disabled'].includes(statusSummary.stage) && (
                            <span className={`flex-shrink-0 rounded-lg border px-2 py-0.5 text-xs font-bold uppercase tracking-widest shadow-inner ${providerBadgeToneClass(statusSummary.stage)}`}>
                                {statusSummary.label}
                            </span>
                        )}
                        {detectedGpu?.name && (
                            <span
                                className="flex-shrink-0 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-xs font-bold text-emerald-300 shadow-inner flex items-center gap-1"
                                title={`GPU: ${detectedGpu.name}${detectedGpu.vram_total_mb ? ` (${formatBytes(detectedGpu.vram_total_mb * MB)} VRAM)` : ''}`}
                            >
                                <Cpu size={12} className="text-emerald-400" />
                                <span>{detectedGpu.name.replace('NVIDIA ', '')}</span>
                                {detectedGpu.vram_total_mb && (
                                    <span className="text-emerald-400/70 font-mono text-2xs">
                                        {formatBytes(detectedGpu.vram_total_mb * MB)}
                                    </span>
                                )}
                            </span>
                        )}
                        {warmWorkload && (
                            <span
                                className="flex-shrink-0 rounded-lg bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-xs font-bold text-amber-300 shadow-inner flex items-center gap-1"
                                title={`Active warm workload loaded in VRAM: ${warmWorkload}`}
                            >
                                <Zap size={11} className="text-amber-400 fill-amber-400/20" />
                                <span>{warmWorkload}</span>
                            </span>
                        )}
                        {components && (
                            <div className="flex-shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-black/40 border border-white/5" title="Sub-services: ComfyUI (:8188), Agent (:8001), LLM (:8003)">
                                <span title={`ComfyUI (:8188) - ${components.comfyui?.status || 'unknown'}`} className="flex items-center gap-0.5 text-2xs text-gray-400 font-mono">
                                    C<span className={`inline-block w-1.5 h-1.5 rounded-full ${components.comfyui?.status === 'healthy' ? 'bg-green-400' : 'bg-red-400'}`} />
                                </span>
                                <span title={`Remote Agent (:8001) - ${components.agent?.status || 'unknown'}`} className="flex items-center gap-0.5 text-2xs text-gray-400 font-mono">
                                    A<span className={`inline-block w-1.5 h-1.5 rounded-full ${components.agent?.status === 'healthy' ? 'bg-green-400' : 'bg-red-400'}`} />
                                </span>
                                <span title={`llama-server (:8003) - ${components.llm?.status || 'unknown'}`} className="flex items-center gap-0.5 text-2xs text-gray-400 font-mono">
                                    L<span className={`inline-block w-1.5 h-1.5 rounded-full ${components.llm?.status === 'healthy' ? 'bg-green-400' : 'bg-red-400'}`} />
                                </span>
                            </div>
                        )}
                        {provider.enabled && hasIssues && (
                            <span
                                className="flex-shrink-0 rounded-lg bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-amber-300 shadow-inner"
                                title="Issues detected on this active provider"
                            >
                                ⚠
                            </span>
                        )}
                        {isReconciling && (
                            <span className="flex-shrink-0 rounded-lg bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 text-xs font-bold uppercase tracking-widest text-blue-300 animate-pulse shadow-inner">
                                Syncing
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2 text-xs font-medium text-gray-500">
                        <span className="uppercase tracking-widest">
                            {provider.worker_type === 'llm'
                                ? 'LLM'
                                : provider.worker_type === 'hybrid'
                                    ? 'Hybrid (All-in-One)'
                                    : provider.type} provider
                        </span>
                        {provider.capabilities && provider.capabilities.length > 1 && (
                            <span className="flex items-center gap-1">
                                {provider.capabilities.map((cap) => (
                                    <span key={cap} className="rounded bg-gray-800 border border-gray-700 px-1.5 py-0.2 text-2xs text-gray-300 uppercase">
                                        {cap}
                                    </span>
                                ))}
                            </span>
                        )}
                        {provider.config?.concurrency_policy && (
                            <span className="rounded bg-indigo-950/60 border border-indigo-800/40 px-1.5 py-0.2 text-2xs text-indigo-300">
                                Policy: {provider.config.concurrency_policy}
                            </span>
                        )}
                        {credentialSummary.account_label && (
                            <>
                                <span className="text-gray-700">·</span>
                                <span className="truncate text-gray-400">{credentialSummary.account_label}</span>
                            </>
                        )}
                    </div>
                    {statusSummary.message && (
                        <p
                            className="mt-1.5 truncate text-2xs font-medium text-gray-400/80"
                            title={provider.enabled ? statusSummary.message : 'Intentionally paused — excluded from load balancer'}
                        >
                            {provider.enabled ? statusSummary.message : 'Intentionally paused — excluded from load balancer'}
                        </p>
                    )}
                    </div>
                </div>

                {/* Metrics */}
                <div className="hidden items-center gap-2 md:flex">
                    {vramHistory.length > 0 && (
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-white/5 bg-black/40 shadow-inner">
                            <span className="text-xs font-bold uppercase tracking-widest text-gray-500">VRAM</span>
                            <SparkLine
                                data={vramHistory}
                                color="#3b82f6"
                                label={`VRAM trend, ${vramHistory.length} readings, latest ${vramHistory[vramHistory.length - 1]}%`}
                            />
                            <span className="text-xs font-bold text-blue-400 min-w-[3ch]">{vramHistory[vramHistory.length - 1]}%</span>
                        </div>
                    )}
                    {tempHistory.length > 0 && (
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-white/5 bg-black/40 shadow-inner">
                            <span className="text-xs font-bold uppercase tracking-widest text-gray-500">GPU</span>
                            <SparkLine
                                data={tempHistory}
                                color="#ef4444"
                                domain={[30, 90]}
                                label={`GPU temperature trend, ${tempHistory.length} readings, latest ${tempHistory[tempHistory.length - 1]} degrees`}
                            />
                            <span className="text-xs font-bold text-red-400 min-w-[3ch]">{tempHistory[tempHistory.length - 1]}°</span>
                        </div>
                    )}
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/5 bg-black/40 shadow-inner text-xs font-bold text-gray-300">
                        <Circle size={8} className={`fill-current ${statusColorByTone(statusSummary.dotTone)}`} />
                        {statusSummary.label}
                    </span>
                    {runtime.connected !== undefined && (
                        <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/5 bg-black/40 shadow-inner text-xs font-bold ${runtime.connected ? 'text-green-400' : 'text-gray-500'}`}>
                            {runtime.connected ? 'Connected' : 'Offline'}
                        </span>
                    )}
                    {provider.worker_type !== 'llm' && statusSummary.downloadsActive > 0 && (
                        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-cyan-500/20 bg-cyan-500/10 shadow-inner text-xs font-bold text-cyan-300">
                            {statusSummary.downloadsActive} downloading
                        </span>
                    )}
                    {provider.worker_type !== 'llm' && statusSummary.downloadsQueued > 0 && (
                        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-blue-500/20 bg-blue-500/10 shadow-inner text-xs font-bold text-blue-300">
                            {statusSummary.downloadsQueued} queued
                        </span>
                    )}
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/5 bg-black/40 shadow-inner text-xs font-bold text-gray-300">
                        {jobsAssigned} job{jobsAssigned !== 1 ? 's' : ''}
                    </span>
                    {providerFailures > 0 && (
                        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-red-500/20 bg-red-500/10 shadow-inner text-xs font-bold text-red-400">
                            {providerFailures} fail{providerFailures !== 1 ? 's' : ''}
                        </span>
                    )}
                    {/* Live Ping Chip */}
                    <button
                        type="button"
                        onClick={handlePing}
                        disabled={pingState.pinging}
                        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border transition-all text-xs font-mono font-medium shadow-inner ${
                            pingState.pinging
                                ? 'border-blue-500/30 bg-blue-500/10 text-blue-300'
                                : pingState.latency !== null
                                    ? pingState.latency < 100
                                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                                        : pingState.latency < 250
                                            ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20'
                                            : 'border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20'
                                    : pingState.error
                                        ? 'border-red-500/30 bg-red-500/10 text-red-300'
                                        : 'border-white/5 bg-black/40 text-gray-400 hover:text-gray-200 hover:bg-white/5'
                        }`}
                        title="Click to ping worker over NetBird mesh / network"
                    >
                        {pingState.pinging ? (
                            <Loader2 size={11} className="animate-spin text-blue-400" />
                        ) : (
                            <Activity size={11} className={pingState.latency !== null ? 'text-current' : 'text-gray-500'} />
                        )}
                        <span>
                            {pingState.pinging
                                ? 'Ping…'
                                : pingState.latency !== null
                                    ? `${Math.round(pingState.latency)}ms`
                                    : pingState.error
                                        ? 'Failed'
                                        : 'Ping'}
                        </span>
                    </button>
                </div>

                {/* Actions */}
                {/* `flex-wrap` + `min-w-0`: this action row is three
                    `flex-shrink-0` buttons and the name column now has a
                    14rem floor (see above), which together exceed a 704px card
                    at 768px. Without wrapping the app root clipped them with
                    `overflow-x-hidden` and Enable / Edit / Delete were entirely
                    outside the viewport. Wrapping puts them on their own line
                    instead. */}
                <div className="flex items-center gap-2 mt-3 sm:mt-0 sm:pl-4 justify-end w-full sm:w-auto min-w-0 flex-wrap border-t sm:border-none border-white/5 pt-3 sm:pt-0" onClick={(e) => e.stopPropagation()}>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onToggleEnabled?.(provider.id, provider.enabled);
                        }}
                        className={`rounded-xl p-2.5 transition-all duration-300 ${provider.enabled ? 'text-green-400 bg-green-500/10 hover:bg-green-500/20 hover:text-green-300' : 'text-gray-500 bg-white/5 hover:bg-white/10 hover:text-gray-300'}`}
                        title={provider.enabled ? 'Disable' : 'Enable'}
                        aria-label={provider.enabled ? 'Disable Provider' : 'Enable Provider'}
                    >
                        {provider.enabled ? <Power size={16} /> : <PowerOff size={16} />}
                    </button>
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onEdit?.(provider);
                        }}
                        className="rounded-xl p-2.5 text-gray-400 bg-white/5 hover:bg-blue-500/10 hover:text-blue-400 transition-all duration-300"
                        title="Edit"
                        aria-label="Edit Provider"
                    >
                        <Edit2 size={16} />
                    </button>
                    {(() => {
                        const deployTarget = getDeployTargetForProvider(provider);
                        if (!deployTarget || !onDeploy) return null;
                        const label = deployTarget === 'image' ? 'Image' : deployTarget === 'llm' ? 'LLM' : deployTarget === 'tts' ? 'TTS' : 'Beam';
                        return (
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDeploy?.(provider);
                                }}
                                className="rounded-xl p-2.5 text-purple-400 bg-purple-500/10 hover:bg-purple-500/20 hover:text-purple-300 transition-all duration-300"
                                title={`Deploy ${label} Worker`}
                                aria-label={`Deploy ${label} Worker`}
                            >
                                <Rocket size={16} />
                            </button>
                        );
                    })()}
                    <button
                        type="button"
                        onClick={(e) => {
                            e.stopPropagation();
                            onDelete?.(provider.id);
                        }}
                        className="rounded-xl p-2.5 text-gray-400 bg-white/5 hover:bg-red-500/10 hover:text-red-400 transition-all duration-300"
                        title="Delete"
                        aria-label="Delete Provider"
                    >
                        <Trash2 size={16} />
                    </button>
                    {currentAction && (
                        <Loader2 className="ml-2 animate-spin text-blue-400" size={16} />
                    )}
                    <div className={`ml-2 p-1.5 rounded-lg transition-colors ${isSelected ? 'bg-blue-500/10 text-blue-400' : 'text-gray-600 group-hover:text-gray-400'}`}>
                        <ChevronRight
                            size={18}
                            className={`transition-transform duration-300 ${
                                isSelected ? 'rotate-90' : 'group-hover:translate-x-0.5'
                            }`}
                        />
                    </div>
                </div>
            </div>

            {/* Mobile-only metrics row */}
            <div className="mt-3 flex flex-wrap items-center gap-2 md:hidden">
                <span className="metric-chip">
                    <Circle size={6} className={`fill-current ${statusColorByTone(statusSummary.dotTone)}`} />
                    {statusSummary.label}
                </span>
                <span className="metric-chip">
                    {jobsAssigned} jobs
                </span>
                {statusSummary.downloadsActive > 0 && (
                    <span className="metric-chip text-cyan-300 border-cyan-500/20">
                        {statusSummary.downloadsActive} downloading
                    </span>
                )}
                {providerFailures > 0 && (
                    <span className="metric-chip text-red-400 border-red-500/20">
                        {providerFailures} fails
                    </span>
                )}
            </div>
        </div>
    );
}

export default React.memo(ProviderListItem);
