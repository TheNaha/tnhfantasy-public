import { AlertTriangle, CheckCircle, XCircle, Activity, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { DataRow } from './Shared';
import { providersApi } from '../../../api';

export default function DiagnosticsTab({ providerId, diagnostics, runtime, credentialSummary, providerFailures }) {
    const warnings = diagnostics.warnings || [];
    const errors = diagnostics.errors || [];
    const hasIssues = warnings.length > 0 || errors.length > 0 || providerFailures > 0;

    const { data: metricsData, isLoading: metricsLoading } = useQuery({
        queryKey: ['provider-live-metrics', providerId],
        queryFn: () => providersApi.getLiveMetrics(providerId),
        refetchInterval: 5000, // Poll every 5s while tab is open
        enabled: !!providerId,
    });

    const metrics = metricsData;

    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden mb-4">
                <DataRow label="Backend URL" value={diagnostics.worker?.backend_url} mono />
                <DataRow label="Worker URL" value={diagnostics.worker?.worker_url} mono />
                <DataRow label="Runtime Mode" value={diagnostics.worker?.mode || runtime.mode} />
                <DataRow label="Credential Ready" value={credentialSummary.ready ? 'Yes' : 'Missing'} />
                <DataRow label="GPU" value={diagnostics.worker?.gpu || runtime.gpu || 'N/A'} />
                <DataRow label="Version" value={diagnostics.worker?.version || runtime.version || 'N/A'} />
                {credentialSummary.configured_fields?.length > 0 && (
                    <DataRow label="Configured Secrets" value={credentialSummary.configured_fields.join(', ')} />
                )}
            </div>

            <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 mb-4">
                <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm font-medium text-blue-200 flex items-center gap-2">
                        <Activity size={16} className="text-blue-400" />
                        Live Remote Metrics
                    </h3>
                    {metricsLoading && <Loader2 size={14} className="text-blue-400 animate-spin" />}
                </div>
                {!metricsLoading && !metrics && (
                    <div className="text-xs text-gray-500 italic">No metrics available.</div>
                )}
                {metrics && (
                    <div className="grid grid-cols-2 gap-3 text-sm">
                        <div>
                            <div className="text-xs text-gray-500">Status</div>
                            <div className={metrics.status === 'online' ? 'text-green-400' : 'text-red-400'}>
                                {metrics.status}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-gray-500">Ping Latency</div>
                            <div className="text-gray-200">{metrics.latency_ms > 0 ? `${metrics.latency_ms} ms` : 'N/A'}</div>
                        </div>
                        {metrics.info && (
                            <>
                                <div>
                                    <div className="text-xs text-gray-500">Remote Version</div>
                                    <div className="text-gray-200">{metrics.info.version || 'unknown'}</div>
                                </div>
                                <div>
                                    <div className="text-xs text-gray-500">ComfyUI Mode</div>
                                    <div className="text-gray-200">{metrics.info.comfy_mode || 'unknown'}</div>
                                </div>
                            </>
                        )}
                        {metrics.error && (
                            <div className="col-span-2 text-xs text-red-400 mt-1">
                                Error: {metrics.error}
                            </div>
                        )}
                    </div>
                )}
            </div>

            <div className="space-y-2">
                {providerFailures > 0 && (
                    <div className="flex items-start gap-3 rounded-lg border border-amber-500/20 bg-amber-500/8 p-3">
                        <AlertTriangle size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-amber-200">{providerFailures} consecutive failure{providerFailures !== 1 ? 's' : ''} recorded</span>
                    </div>
                )}
                {errors.map((msg) => (
                    <div key={`e-${msg}`} className="flex items-start gap-3 rounded-lg border border-red-500/20 bg-red-500/8 p-3">
                        <XCircle size={16} className="text-red-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-red-200">{msg}</span>
                    </div>
                ))}
                {warnings.map((msg) => (
                    <div key={`w-${msg}`} className="flex items-start gap-3 rounded-lg border border-yellow-500/20 bg-yellow-500/8 p-3">
                        <AlertTriangle size={16} className="text-yellow-400 mt-0.5 flex-shrink-0" />
                        <span className="text-sm text-yellow-200">{msg}</span>
                    </div>
                ))}
                {!hasIssues && (
                    <div className="flex items-center gap-3 rounded-lg border border-green-500/20 bg-green-500/8 p-3">
                        <CheckCircle size={16} className="text-green-400 flex-shrink-0" />
                        <span className="text-sm text-green-200">All diagnostics clear — no issues detected</span>
                    </div>
                )}
            </div>
        </>
    );
}
