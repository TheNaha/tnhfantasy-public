import { memo, useState } from 'react';
import { Clock, ChevronDown, ChevronRight, Zap, ArrowDownToLine, Server } from 'lucide-react';
import { formatBytes } from '../../utils/bytes';
import { getProviderDisplayName } from '../../utils/providerUtils';

export const GenerationTelemetry = memo(function GenerationTelemetry({
    timings,
    steps,
    providerId,
    className = '',
    title = 'Generation Telemetry',
    collapsible = false,
    defaultExpanded = true,
}) {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded);

    if (!timings) return null;

    const total = Number(
        timings.total_e2e_seconds ||
        timings.total_backend_seconds ||
        timings.total_seconds ||
        0
    );

    const queueSec = Number(timings.queue_seconds ?? 0);
    const modelLoadSec = Number(timings.model_load_seconds ?? 0);
    const samplingSec = Number(timings.sampling_seconds ?? 0);
    const transferSec = Number(timings.transfer_seconds ?? 0);
    const processingSec = Number(timings.processing_seconds ?? 0);

    const stepCount = Number(steps || timings.steps || 0);
    const itPerSec = (samplingSec > 0 && stepCount > 0)
        ? (stepCount / samplingSec)
        : null;

    const transferBytes = timings.transfer_bytes ? Number(timings.transfer_bytes) : null;
    const transferFormat = timings.transfer_format ? String(timings.transfer_format).toUpperCase() : null;
    const transferRate = (transferBytes && transferSec > 0)
        ? (transferBytes / transferSec)
        : null;

    const activeProvider = providerId || timings.provider_id;
    return (
        <div data-testid="generation-telemetry" className={`bg-gray-800/60 rounded-xl border border-gray-700/80 p-3.5 ${className}`}>
            <div className="flex items-center justify-between gap-2 mb-2">
                <div
                    className={`flex items-center gap-1.5 text-xs font-semibold text-cyan-400 uppercase tracking-wider ${
                        collapsible ? 'cursor-pointer select-none' : ''
                    }`}
                    onClick={collapsible ? () => setIsExpanded(prev => !prev) : undefined}
                >
                    <Clock size={13} aria-hidden="true" />
                    <span>{title}</span>
                    {collapsible && (
                        isExpanded ? <ChevronDown size={14} className="text-gray-400" /> : <ChevronRight size={14} className="text-gray-400" />
                    )}
                </div>
                <span className="font-mono text-cyan-300 font-bold text-xs">
                    {total > 0 ? `${total.toFixed(2)}s` : '—'}
                </span>
            </div>

            {/* Visual multi-colored progress bar */}
            <div className="w-full bg-gray-700/80 rounded-full h-1.5 overflow-hidden flex mb-2.5">
                {queueSec > 0 && (
                    <div
                        style={{ width: `${Math.min(100, (queueSec / (total || 1)) * 100)}%` }}
                        className="bg-yellow-400 h-full"
                        title={`Queue: ${queueSec.toFixed(2)}s`}
                    />
                )}
                {modelLoadSec > 0 && (
                    <div
                        style={{ width: `${Math.min(100, (modelLoadSec / (total || 1)) * 100)}%` }}
                        className="bg-purple-400 h-full"
                        title={`Model Load: ${modelLoadSec.toFixed(2)}s`}
                    />
                )}
                {samplingSec > 0 && (
                    <div
                        style={{ width: `${Math.min(100, (samplingSec / (total || 1)) * 100)}%` }}
                        className="bg-blue-400 h-full"
                        title={`Sampling: ${samplingSec.toFixed(2)}s`}
                    />
                )}
                {transferSec > 0 && (
                    <div
                        style={{ width: `${Math.min(100, (transferSec / (total || 1)) * 100)}%` }}
                        className="bg-cyan-400 h-full"
                        title={`Transfer: ${transferSec.toFixed(2)}s`}
                    />
                )}
                {processingSec > 0 && (
                    <div
                        style={{ width: `${Math.min(100, (processingSec / (total || 1)) * 100)}%` }}
                        className="bg-emerald-400 h-full"
                        title={`Post-proc: ${processingSec.toFixed(2)}s`}
                    />
                )}
            </div>

            {(!collapsible || isExpanded) && (
                <div className="space-y-1.5 text-xs font-mono">
                    <div className="grid grid-cols-2 gap-1.5">
                        {timings.queue_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded">
                                <span className="text-yellow-400">Queue:</span>
                                <span className="text-gray-300">{queueSec.toFixed(2)}s</span>
                            </div>
                        )}
                        {timings.model_load_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded">
                                <span className="text-purple-400">Model Load:</span>
                                <span className="text-gray-300">{modelLoadSec.toFixed(2)}s</span>
                            </div>
                        )}
                        {timings.sampling_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded">
                                <span className="text-blue-400">Sampling:</span>
                                <div className="text-right">
                                    <span className="text-gray-300">{samplingSec.toFixed(2)}s</span>
                                    {itPerSec !== null && (
                                        <span className="text-3xs text-blue-300/80 block font-sans">
                                            {itPerSec >= 1 ? `${itPerSec.toFixed(2)} it/s` : `${(1 / itPerSec).toFixed(2)} s/it`}
                                        </span>
                                    )}
                                </div>
                            </div>
                        )}
                        {timings.transfer_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded">
                                <span className="text-cyan-400">Transfer:</span>
                                <div className="text-right">
                                    <span className="text-gray-300">{transferSec.toFixed(2)}s</span>
                                    {transferBytes !== null && (
                                        <span className="text-3xs text-cyan-300/80 block font-sans">
                                            {formatBytes(transferBytes)}{transferFormat ? ` (${transferFormat})` : ''}
                                        </span>
                                    )}
                                </div>
                            </div>
                        )}
                        {timings.processing_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded">
                                <span className="text-emerald-400">Post-proc:</span>
                                <span className="text-gray-300">{processingSec.toFixed(2)}s</span>
                            </div>
                        )}
                        {timings.total_backend_seconds !== undefined && (
                            <div className="flex justify-between items-center bg-gray-900/40 px-2 py-1 rounded font-bold">
                                <span className="text-gray-400">Backend:</span>
                                <span className="text-white">{Number(timings.total_backend_seconds).toFixed(2)}s</span>
                            </div>
                        )}
                    </div>

                    {/* Secondary Metrics: Speed, Transfer Bandwidth, Provider */}
                    {(itPerSec !== null || transferRate !== null || activeProvider) && (
                        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-gray-700/50 text-3xs text-gray-400 font-sans">
                            {itPerSec !== null && (
                                <span className="inline-flex items-center gap-1 bg-blue-500/10 text-blue-300 px-1.5 py-0.5 rounded border border-blue-500/20">
                                    <Zap size={10} className="text-blue-400" />
                                    <span>{stepCount} steps @ {itPerSec.toFixed(2)} it/s</span>
                                </span>
                            )}
                            {transferRate !== null && (
                                <span className="inline-flex items-center gap-1 bg-cyan-500/10 text-cyan-300 px-1.5 py-0.5 rounded border border-cyan-500/20">
                                    <ArrowDownToLine size={10} className="text-cyan-400" />
                                    <span>{formatBytes(transferRate)}/s</span>
                                </span>
                            )}
                            {activeProvider && (
                                <span className="inline-flex items-center gap-1 bg-purple-500/10 text-purple-300 px-1.5 py-0.5 rounded border border-purple-500/20">
                                    <Server size={10} className="text-purple-400" />
                                    <span>{getProviderDisplayName(activeProvider)}</span>
                                </span>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
});

export default GenerationTelemetry;
