import { Wrench, Zap, Brain, RefreshCw, CheckCircle, XCircle, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { DataRow, StatusRow, ActionBtn } from './Shared';
import { STATUS_TONE, humanize } from './utils';
import { useLLMProviderTest } from '../../../hooks/useLLMProviderStatus';

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
                        <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">
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

export default function RuntimeTab({
    runtime, runtimeStatus, provider, capabilities, loading,
    onSetup,
    jobsAssigned, providerFailures,
}) {
    const [pingStatus, setPingStatus] = useState(null); // null, 'loading', 'success', 'error'
    const [pingLatency, setPingLatency] = useState(null);
    const isLLM = provider.worker_type === 'llm';

    const handlePingTest = async () => {
        if (!runtime.worker_url) return;
        setPingStatus('loading');
        setPingLatency(null);
        const start = Date.now();
        try {
            const res = await fetch(`/api/v2/providers/${provider.id}/ping`, { method: 'POST' });
            const data = await res.json();
            if (res.ok && data?.healthy) {
                const latency = data.latency_ms ?? Date.now() - start;
                setPingLatency(latency);
                setPingStatus('success');
                setTimeout(() => setPingStatus(null), 3000);
            } else {
                throw new Error('Ping failed');
            }
        } catch {
            setPingStatus('error');
            setTimeout(() => setPingStatus(null), 3000);
        }
    };

    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <StatusRow label="Runtime Status" value={humanize(runtimeStatus)} tone={STATUS_TONE[runtimeStatus]} />
                <StatusRow label="Connectivity" value={runtime.connected ? 'Connected' : 'Unavailable'} tone={runtime.connected ? 'green' : 'gray'} />
                <DataRow label="Worker URL" value={runtime.worker_url} mono />
                <DataRow label="Container Port" value={String(provider.runtime_config?.port ?? 'n/a')} />
                <DataRow label="Jobs Assigned" value={String(jobsAssigned)} />
                <DataRow label="Failures" value={String(providerFailures)} />
                <DataRow label="Last Seen" value={runtime.last_seen_at ? new Date(runtime.last_seen_at).toLocaleString() : 'N/A'} />
                {!isLLM && (
                    <>
                        <DataRow label="Container ID" value={runtime.container_id ? runtime.container_id.slice(0, 12) : 'N/A'} mono />
                        <DataRow label="Uptime" value={runtime.uptime ? Math.floor(runtime.uptime / 60) + 'm' : 'N/A'} />
                    </>
                )}
            </div>

            {/* LLM-specific: Test Connection + Model List */}
            {isLLM && <LLMRuntimePanel provider={provider} />}

            <div className="flex flex-wrap items-center gap-2">
                {capabilities.setup && (
                    <ActionBtn onClick={onSetup} disabled={Boolean(loading)} tone="blue" icon={Wrench} label="Setup" />
                )}
                {!isLLM && runtime.worker_url && (
                    <ActionBtn
                        onClick={handlePingTest}
                        disabled={pingStatus === 'loading'}
                        tone="green"
                        icon={Zap}
                        label={pingStatus === 'loading' ? "Pinging..." : "Send Ping Test"}
                    />
                )}
                {pingStatus === 'success' && (
                    <span className="text-sm text-green-400 ml-2">Success ({pingLatency}ms)</span>
                )}
                {pingStatus === 'error' && (
                    <span className="text-sm text-red-400 ml-2">Failed to reach worker</span>
                )}
            </div>
        </>
    );
}
