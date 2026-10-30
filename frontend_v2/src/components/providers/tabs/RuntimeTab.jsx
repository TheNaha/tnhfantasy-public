import { Wrench, Zap, Brain, RefreshCw, CheckCircle, XCircle, Loader2, Rocket, Cpu, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { useQuery } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { DataRow, StatusRow, ActionBtn } from './Shared';
import { STATUS_TONE, humanize } from './utils';
import { useLLMProviderTest } from '../../../hooks/useLLMProviderStatus';
import { formatTimestamp } from '../../../utils/dateTime';
import { formatBytes, MB } from '../../../utils/bytes';
import { providersApi } from '../../../api';
import { getDeployTargetForProvider } from '../../../utils/providerStatus';


// ── LLM-specific panel shown inside RuntimeTab for LLM workers ──────────────
function LLMRuntimePanel({ provider }) {
    const testMutation = useLLMProviderTest();
    const [testResult, setTestResult] = useState(null); // null | { healthy, models, error, worker_url }

    const handleTest = async () => {
        setTestResult(null);
        try {
            const result = await testMutation.mutateAsync(provider.id);
            setTestResult(result);
        } catch (err) {
            setTestResult({ healthy: false, models: [], error: err?.message || 'Request failed' });
        }
    };

    return (
        <div className="space-y-4">
            {/* Test connection */}
            <div className="flex flex-wrap items-center gap-3">
                <button
                    type="button"
                    onClick={handleTest}
                    disabled={testMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg border border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/15 px-3 py-2 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {testMutation.isPending
                        ? <Loader2 size={14} className="animate-spin" />
                        : <Brain size={14} />}
                    {testMutation.isPending ? 'Testing…' : 'Test Connection'}
                </button>

                {testResult && (
                    testResult.healthy
                        ? <span className="flex items-center gap-1.5 text-sm text-green-400"><CheckCircle size={14} /> Connected</span>
                        : <span className="flex items-center gap-1.5 text-sm text-red-400"><XCircle size={14} /> {testResult.error || 'Unreachable'}</span>
                )}
            </div>

            {/* Model list from worker */}
            {testResult?.healthy && (
                <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-white/[0.03] flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-widest text-gray-500">
                            Available Models ({testResult.models?.length ?? 0})
                        </span>
                        <button
                            type="button"
                            onClick={handleTest}
                            className="p-1 text-gray-600 hover:text-gray-300 transition-colors rounded"
                            title="Refresh model list"
                        >
                            <RefreshCw size={12} />
                        </button>
                    </div>
                    {testResult.models?.length > 0 ? (
                        <div className="max-h-48 overflow-y-auto">
                            {testResult.models.map((m, i) => (
                                <div key={i} className="px-4 py-2 border-b border-white/[0.03] last:border-0 text-sm text-gray-300 font-mono text-xs">
                                    {m}
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="px-4 py-3 text-sm text-gray-500 italic">
                            No models returned by worker — check worker configuration.
                        </div>
                    )}
                </div>
            )}

            {testResult && !testResult.healthy && testResult.error && (
                <div className="rounded-lg border border-red-500/20 bg-red-500/8 px-4 py-3 text-sm text-red-200">
                    <span className="font-semibold">Error: </span>{testResult.error}
                </div>
            )}
        </div>
    );
}

function DiscoveredAssetsPanel({ provider }) {
    const [assets, setAssets] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const handleDiscover = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await providersApi.getDiscoveredModels(provider.id);
            setAssets(data?.models || []);
        } catch (err) {
            setError(err.message || 'Discovery failed');
        } finally {
            setLoading(false);
        }
    };

    const isImage = provider.worker_type === 'image' || provider.worker_type === 'hybrid' || !provider.worker_type;
    const isVoice = provider.worker_type === 'tts' || provider.type?.includes('tts');
    const assetTitle = isVoice ? 'Discovered Voices' : isImage ? 'Upstream Models' : 'Available Models';

    return (
        <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-white/[0.03] flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-widest text-gray-400 flex items-center gap-2">
                    <Brain size={13} className="text-blue-400" />
                    {assetTitle} {assets ? `(${assets.length})` : ''}
                </span>
                <button
                    type="button"
                    onClick={handleDiscover}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 rounded transition-colors disabled:opacity-50"
                >
                    {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    {loading ? 'Probing…' : assets ? 'Refresh' : 'Discover'}
                </button>
            </div>
            {assets !== null && (
                assets.length > 0 ? (
                    <div className="max-h-48 overflow-y-auto divide-y divide-white/[0.02]">
                        {assets.map((item, idx) => (
                            <div key={idx} className="px-4 py-2 flex items-center justify-between text-xs text-gray-300 font-mono">
                                <span className="truncate">{item.name || item.id || String(item)}</span>
                                {item.accent && <span className="text-gray-500 text-[11px] uppercase ml-2">{item.gender} • {item.accent}</span>}
                            </div>
                        ))}
                    </div>
                ) : (
                    <div className="px-4 py-3 text-xs text-gray-500 italic">
                        No models discovered. Verify provider volume or credentials.
                    </div>
                )
            )}
            {error && (
                <div className="px-4 py-2 text-xs text-red-400 bg-red-500/10 border-t border-red-500/20">
                    {error}
                </div>
            )}
        </div>
    );
}

export default function RuntimeTab({
    runtime, runtimeStatus, provider, capabilities, loading,
    onSetup, onDeploy,
    jobsAssigned, providerFailures,
}) {
    const [pingStatus, setPingStatus] = useState(null); // null, 'loading', 'success', 'error'
    const [pingLatency, setPingLatency] = useState(null);
    const [liveTelemetry, setLiveTelemetry] = useState(null);
    const [freeingVram, setFreeingVram] = useState(false);

    const isLLM = provider.worker_type === 'llm';
    const isHybridOrRemote = provider.worker_type === 'hybrid' || provider.type === 'remote_hybrid' || provider.type === 'direct_comfy';
    // Trust the backend's resolved mode: `in_process` is the in-process
    // engine, everything else a remote endpoint (external worker).
    const isInProcess = runtime.mode === 'in_process';
    // The engine-relevant settings live on `deploy_config`, which the status card
    // emits and which `LEGACY_DEPLOY_CONFIG_FIELDS` backfills from the provider
    // row's own `config`. This used to read `provider.config?.app_name` directly —
    // a key the card never sends — so the two rows below were always blank.
    const engineConfig = provider.deploy_config || {};
    // `runtime.last_seen_at` was never emitted either: it was a worker
    // self-report from the deleted container path. `reconciliation_state` is the
    // live equivalent and is stamped every time the reconciler contacts the
    // provider.
    const lastContact =
        provider.reconciliation_state?.last_contact_at ||
        provider.reconciliation?.last_contact_at ||
        null;

    const telemetry = provider.runtime_state?.telemetry || provider.diagnostics?.telemetry || provider.hardware_telemetry || {};
    const { data: logsData } = useQuery({
        queryKey: ['provider-logs', provider.id],
        queryFn: () => providersApi.getLogs(provider.id),
        enabled: Boolean(provider.id),
        staleTime: 30000,
    });
    const recentJobs = logsData?.recent_jobs || [];

    const activeTelemetry = liveTelemetry || telemetry;
    const vramChartPoints = (activeTelemetry.history?.vram || []).map((sample) => ({
        ts: sample.ts ? formatTimestamp(sample.ts) : '',
        used: sample.vram_used_mb ?? sample.vram_used ?? 0,
        total: sample.vram_total_mb ?? sample.vram_total ?? 0,
    }));
    const detectedGpu = activeTelemetry.detected_gpu;
    const concurrencyPolicy = activeTelemetry.concurrency_policy || provider.config?.concurrency_policy;
    const warmWorkload = activeTelemetry.warm_workload;
    const components = activeTelemetry.components;

    const handlePingTest = async () => {
        setPingStatus('loading');
        setPingLatency(null);
        try {
            const data = await providersApi.testProvider(provider.id);
            if (data?.healthy || data?.status === 'healthy' || data?.ready) {
                setPingLatency(data.latency_ms ?? null);
                setPingStatus('success');
                if (data?.telemetry || data?.details) {
                    setLiveTelemetry(data?.telemetry || {
                        detected_gpu: data.details?.detected_gpu,
                        concurrency_policy: data.details?.concurrency_policy,
                        warm_workload: data.details?.warm_workload,
                        components: data.details?.components,
                    });
                }
                setTimeout(() => setPingStatus(null), 3500);
            } else {
                throw new Error(data?.error || 'Test failed');
            }
        } catch {
            setPingStatus('error');
            setTimeout(() => setPingStatus(null), 3500);
        }
    };

    const handleFreeVram = async () => {
        setFreeingVram(true);
        try {
            await providersApi.freeVram(provider.id);
            toast.success('GPU VRAM purged and model weights unloaded');
            setLiveTelemetry((prev) => ({
                ...(prev || activeTelemetry),
                warm_workload: null,
            }));
        } catch (err) {
            toast.error(err?.message || 'Failed to free GPU VRAM');
        } finally {
            setFreeingVram(false);
        }
    };

    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <StatusRow label="Runtime Status" value={humanize(runtimeStatus)} tone={STATUS_TONE[runtimeStatus]} />
                <StatusRow label="Connectivity" value={runtime.connected ? 'Connected' : 'Unavailable'} tone={runtime.connected ? 'green' : 'gray'} />
                {isInProcess ? (
                    <>
                        <DataRow label="Engine Mode" value="In-Process Engine" />
                        {engineConfig.app_name && <DataRow label="Modal App" value={engineConfig.app_name} />}
                        {engineConfig.comfy_url && <DataRow label="ComfyUI URL" value={engineConfig.comfy_url} mono />}
                    </>
                ) : (
                    <DataRow label="Worker URL" value={runtime.worker_url} mono />
                )}
                <DataRow label="Jobs Assigned" value={String(jobsAssigned)} />
                <DataRow label="Failures" value={String(providerFailures)} />
                <DataRow label="Last Contact" value={lastContact ? formatTimestamp(lastContact) : 'N/A'} />
            </div>

            {/* Hardware & Daemons Telemetry Panel */}
            {(detectedGpu || components || concurrencyPolicy || warmWorkload) && (
                <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-white/[0.03] flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-widest text-emerald-400 flex items-center gap-2">
                            <Cpu size={14} className="text-emerald-400" />
                            Hardware & Daemons Telemetry
                        </span>
                        {warmWorkload && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-bold bg-amber-500/10 text-amber-300 border border-amber-500/20">
                                <Zap size={10} className="fill-current text-amber-400" />
                                Warm: {warmWorkload}
                            </span>
                        )}
                    </div>
                    <div className="p-4 space-y-3">
                        {detectedGpu && (
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs bg-black/30 p-3 rounded-lg border border-white/5">
                                <div>
                                    <span className="text-gray-500 block text-2xs">GPU Model</span>
                                    <span className="font-semibold text-gray-200">{detectedGpu.name || 'Generic GPU'}</span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block text-2xs">VRAM Capacity</span>
                                    <span className="font-mono text-gray-200">
                                        {detectedGpu.vram_total_mb ? formatBytes(detectedGpu.vram_total_mb * MB) : 'N/A'}
                                    </span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block text-2xs">Available VRAM</span>
                                    <span className="font-mono text-emerald-400">
                                        {detectedGpu.vram_free_mb ? `${formatBytes(detectedGpu.vram_free_mb * MB)} Free` : 'Active'}
                                    </span>
                                </div>
                            </div>
                        )}

                        {concurrencyPolicy && (
                            <div className="flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-indigo-950/20 border border-indigo-800/30">
                                <span className="text-gray-400">GPU Concurrency Coordinator:</span>
                                <span className="font-semibold text-indigo-300 uppercase tracking-wide">
                                    {concurrencyPolicy}
                                    <span className="normal-case font-normal text-gray-400 text-2xs ml-2">
                                        {concurrencyPolicy === 'exclusive' ? '(Sequential lock between Image & LLM)' : concurrencyPolicy === 'semi_concurrent' ? '(Concurrent RP + Image)' : '(Full Parallel)'}
                                    </span>
                                </span>
                            </div>
                        )}

                        {components && (
                            <div className="space-y-1.5 pt-1">
                                <span className="text-2xs font-bold uppercase tracking-wider text-gray-500 block">
                                    Sub-Services Mesh Topology
                                </span>
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                                    {Object.entries(components).map(([name, comp]) => {
                                        const label = name === 'comfyui' ? 'ComfyUI Server' : name === 'agent' ? 'Storage Agent' : 'llama-server';
                                        const isHealthy = comp.status === 'healthy';
                                        return (
                                            <div key={name} className="flex items-center justify-between p-2.5 rounded-lg bg-black/40 border border-white/5 text-xs">
                                                <div>
                                                    <div className="font-medium text-gray-200">{label}</div>
                                                    <div className="font-mono text-2xs text-gray-500">Port :{comp.port || '?'}</div>
                                                </div>
                                                <div className="text-right">
                                                    <div className={`flex items-center gap-1 font-semibold ${isHealthy ? 'text-green-400' : 'text-red-400'}`}>
                                                        <span className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-green-400 shadow-[0_0_6px_rgba(74,222,128,0.5)]' : 'bg-red-400'}`} />
                                                        {isHealthy ? 'Online' : 'Offline'}
                                                    </div>
                                                    {comp.latency_ms !== undefined && comp.latency_ms !== null && (
                                                        <span className="text-2xs font-mono text-gray-500">{Math.round(comp.latency_ms)}ms</span>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Model & Voice Discovery */}
            <DiscoveredAssetsPanel provider={provider} />

            {/* VRAM history chart (recharts) */}
            {vramChartPoints.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-white/[0.03]">
                        <span className="text-xs font-bold uppercase tracking-widest text-blue-400">
                            VRAM History ({vramChartPoints.length} samples)
                        </span>
                    </div>
                    <div className="p-3" style={{ width: '100%', height: 180 }}>
                        <ResponsiveContainer>
                            <LineChart data={vramChartPoints} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                                <XAxis dataKey="ts" tick={{ fontSize: 9, fill: '#6b7280' }} />
                                <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} />
                                <Tooltip contentStyle={{ background: '#111827', border: '1px solid rgba(255,255,255,0.1)', fontSize: 11 }} />
                                <Line type="monotone" dataKey="used" stroke="#3b82f6" strokeWidth={2} dot={false} name="Used MB" />
                                <Line type="monotone" dataKey="total" stroke="#6b7280" strokeWidth={1} dot={false} name="Total MB" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}

            {/* Recent jobs with boot times */}
            {recentJobs.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                    <div className="px-4 py-2.5 border-b border-white/[0.03]">
                        <span className="text-xs font-bold uppercase tracking-widest text-gray-400">
                            Recent Jobs
                        </span>
                    </div>
                    <div className="divide-y divide-white/[0.03]">
                        {recentJobs.slice(0, 8).map((job) => (
                            <div key={job.id} className="px-4 py-2 flex items-center justify-between text-xs">
                                <div className="flex items-center gap-2 min-w-0">
                                    <span className="font-mono text-gray-300 truncate">{job.id}</span>
                                    <span className="text-gray-500 uppercase">{job.task_type}</span>
                                </div>
                                <div className="flex items-center gap-3 text-gray-400">
                                    {job.boot_seconds != null && (
                                        <span className="font-mono text-blue-300">boot {Number(job.boot_seconds).toFixed(1)}s</span>
                                    )}
                                    {job.duration_seconds != null && (
                                        <span className="font-mono">{Number(job.duration_seconds).toFixed(1)}s</span>
                                    )}
                                    <span className={job.status === 'completed' ? 'text-emerald-400' : job.status === 'failed' ? 'text-red-400' : 'text-gray-400'}>
                                        {job.status}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
                {capabilities.setup && (
                    <ActionBtn onClick={onSetup} disabled={Boolean(loading)} tone="blue" icon={Wrench} label="Setup" />
                )}
                {(() => {
                    const deployTarget = getDeployTargetForProvider(provider);
                    if (!deployTarget || !onDeploy) return null;
                    const label = deployTarget === 'image' ? 'Image' : deployTarget === 'llm' ? 'LLM' : deployTarget === 'tts' ? 'TTS' : 'Beam';
                    return (
                        <ActionBtn onClick={() => onDeploy(provider)} disabled={Boolean(loading)} tone="purple" icon={Rocket} label={`Deploy ${label} Worker`} />
                    );
                })()}
                {!isLLM && (
                    <ActionBtn
                        onClick={handlePingTest}
                        disabled={pingStatus === 'loading'}
                        tone="green"
                        icon={Zap}
                        label={pingStatus === 'loading' ? "Testing..." : "Test Connection"}
                    />
                )}
                {isHybridOrRemote && (
                    <ActionBtn
                        onClick={handleFreeVram}
                        disabled={freeingVram}
                        tone="amber"
                        icon={Trash2}
                        label={freeingVram ? "Purging VRAM…" : "Purge GPU VRAM"}
                    />
                )}
                {pingStatus === 'success' && (
                    <span className="text-sm text-green-400 ml-2">Success {pingLatency ? `(${pingLatency}ms)` : ''}</span>
                )}
                {pingStatus === 'error' && (
                    <span className="text-sm text-red-400 ml-2">Failed to reach provider</span>
                )}
            </div>
        </>
    );
}

