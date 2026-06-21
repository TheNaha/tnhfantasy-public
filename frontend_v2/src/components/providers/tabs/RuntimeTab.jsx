import { Wrench, Zap } from 'lucide-react';
import { useState } from 'react';
import { DataRow, StatusRow, ActionBtn, STATUS_TONE, humanize } from './Shared';

export default function RuntimeTab({
    runtime, runtimeStatus, provider, capabilities, loading,
    onSetup,
    jobsAssigned, providerFailures,
}) {
    const [pingStatus, setPingStatus] = useState(null); // null, 'loading', 'success', 'error'
    const [pingLatency, setPingLatency] = useState(null);

    const handlePingTest = async () => {
        if (!runtime.worker_url) return;
        setPingStatus('loading');
        setPingLatency(null);
        const start = Date.now();
        try {
            const res = await fetch(`${runtime.worker_url}/health`);
            if (res.ok) {
                const latency = Date.now() - start;
                setPingLatency(latency);
                setPingStatus('success');
                setTimeout(() => setPingStatus(null), 3000);
            } else {
                throw new Error('Ping failed');
            }
        } catch (error) {
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
                <DataRow label="Container ID" value={runtime.container_id ? runtime.container_id.slice(0, 12) : 'N/A'} mono />
                <DataRow label="Uptime" value={runtime.uptime ? Math.floor(runtime.uptime / 60) + 'm' : 'N/A'} />
            </div>

            <div className="flex flex-wrap items-center gap-2">
                {capabilities.setup && (
                    <ActionBtn onClick={onSetup} disabled={Boolean(loading)} tone="blue" icon={Wrench} label="Setup" />
                )}
                {runtime.worker_url && (
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
