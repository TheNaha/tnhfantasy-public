import { memo, useState } from 'react';
import { Clock, ChevronDown, ChevronRight } from 'lucide-react';

export const GenerationTelemetry = memo(function GenerationTelemetry({
    timings,
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
                <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
                    {timings.queue_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded">
                            <span className="text-yellow-400">Queue:</span>
                            <span className="text-gray-300">{queueSec.toFixed(2)}s</span>
                        </div>
                    )}
                    {timings.model_load_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded">
                            <span className="text-purple-400">Model Load:</span>
                            <span className="text-gray-300">{modelLoadSec.toFixed(2)}s</span>
                        </div>
                    )}
                    {timings.sampling_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded">
                            <span className="text-blue-400">Sampling:</span>
                            <span className="text-gray-300">{samplingSec.toFixed(2)}s</span>
                        </div>
                    )}
                    {timings.transfer_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded">
                            <span className="text-cyan-400">Transfer:</span>
                            <span className="text-gray-300">{transferSec.toFixed(2)}s</span>
                        </div>
                    )}
                    {timings.processing_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded">
                            <span className="text-emerald-400">Post-proc:</span>
                            <span className="text-gray-300">{processingSec.toFixed(2)}s</span>
                        </div>
                    )}
                    {timings.total_backend_seconds !== undefined && (
                        <div className="flex justify-between bg-gray-900/40 px-2 py-1 rounded font-bold">
                            <span className="text-gray-400">Backend:</span>
                            <span className="text-white">{Number(timings.total_backend_seconds).toFixed(2)}s</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
});

export default GenerationTelemetry;
