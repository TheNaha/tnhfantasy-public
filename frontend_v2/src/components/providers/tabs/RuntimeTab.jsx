import { Wrench, Zap, Brain, RefreshCw, CheckCircle, XCircle, Loader2, Rocket } from 'lucide-react';
import { useState } from 'react';
import { DataRow, StatusRow, ActionBtn } from './Shared';
import { STATUS_TONE, humanize } from './utils';
import { useLLMProviderTest } from '../../../hooks/useLLMProviderStatus';
import { formatTimestamp } from '../../../utils/dateTime';
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

    const isImage = provider.worker_type === 'image' || !provider.worker_type;
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
    const isLLM = provider.worker_type === 'llm';
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

    const handlePingTest = async () => {
        setPingStatus('loading');
        setPingLatency(null);
        try {
            const data = await providersApi.testProvider(provider.id);
            if (data?.healthy || data?.status === 'healthy' || data?.ready) {
                setPingLatency(data.latency_ms ?? null);
                setPingStatus('success');
                setTimeout(() => setPingStatus(null), 3500);
            } else {
                throw new Error(data?.error || 'Test failed');
            }
        } catch {
            setPingStatus('error');
            setTimeout(() => setPingStatus(null), 3500);
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

            {/* Model & Voice Discovery */}
            <DiscoveredAssetsPanel provider={provider} />

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

