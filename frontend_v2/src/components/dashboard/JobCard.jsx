import { memo, useCallback, useMemo } from 'react';
import { Loader2, Server, ChevronDown, ChevronUp, Cpu, Layers, Box, Clock, X, Send, Wifi, Zap, Image, Settings } from 'lucide-react';
import { getProviderDisplayName } from '../../utils/providerUtils';
import { formatElapsed } from '../../utils/dateTime';
import { useJobStatus } from '../../hooks/useJobStatus';
import useGlobalClock from '../../hooks/useGlobalClock';

const PHASE_CONFIG = {
    'pending': { icon: Clock, label: 'Queued', color: 'text-gray-400', bar: 'bg-gray-600' },
    'validating': { icon: Settings, label: 'Validating', color: 'text-blue-300', bar: 'bg-blue-500' },
    'sent-to-provider': { icon: Send, label: 'Sending', color: 'text-blue-400', bar: 'bg-blue-500' },
    'sent_to_provider': { icon: Send, label: 'Sending', color: 'text-blue-400', bar: 'bg-blue-500' },
    'connecting': { icon: Wifi, label: 'Connecting', color: 'text-cyan-300', bar: 'bg-cyan-400' },
    'connected': { icon: Server, label: 'Connected', color: 'text-cyan-400', bar: 'bg-cyan-500' },
    'pre-generation': { icon: Zap, label: 'Preparing', color: 'text-yellow-400', bar: 'bg-yellow-500' },
    'pre_generation': { icon: Zap, label: 'Preparing', color: 'text-yellow-400', bar: 'bg-yellow-500' },
    'generating': { icon: Cpu, label: 'Generating', color: 'text-purple-400', bar: 'bg-purple-500' },
    'post-processing': { icon: Layers, label: 'Processing', color: 'text-green-300', bar: 'bg-green-400' },
    'post_processing': { icon: Layers, label: 'Processing', color: 'text-green-300', bar: 'bg-green-400' },
    'generating-blurhash': { icon: Image, label: 'Blurhash', color: 'text-green-400', bar: 'bg-green-500' },
    'generating_blurhash': { icon: Image, label: 'Blurhash', color: 'text-green-400', bar: 'bg-green-500' },
    'generating-thumbnails': { icon: Image, label: 'Thumbnails', color: 'text-emerald-400', bar: 'bg-emerald-500' },
    'generating_thumbnails': { icon: Image, label: 'Thumbnails', color: 'text-emerald-400', bar: 'bg-emerald-500' },
};

const PHASE_ORDER = ['pending', 'validating', 'sent-to-provider', 'connecting', 'connected', 'pre-generation', 'generating', 'post-processing', 'generating-blurhash', 'generating-thumbnails'];

function getJobPhase(job) {
    const status = job.status || 'pending';
    return PHASE_CONFIG[status] || { icon: Clock, label: status, color: 'text-gray-400', bar: 'bg-gray-600' };
}

const ElapsedTime = memo(function ElapsedTime({ createdAt, isProcessing }) {
    useGlobalClock(isProcessing);
    return (
        <span className="text-xs text-gray-600 flex items-center gap-1 flex-shrink-0">
            <Clock size={10} />
            {formatElapsed(createdAt)}
        </span>
    );
});

const JobCard = memo(function JobCard({ job: initialJob, onClick, onDelete }) {
    const { data: realtimeJob } = useJobStatus(initialJob.id);
    const job = useMemo(() => realtimeJob ? { ...initialJob, ...realtimeJob } : initialJob, [initialJob, realtimeJob]);

    const phase = useMemo(() => getJobPhase(job), [job]);
    const PhaseIcon = phase.icon;

    const isSuccess = job.status === 'completed';
    const isError = job.status === 'failed' || job.status === 'error';
    const isCancelled = job.status === 'cancelled';
    const isProcessing = ['sent-to-provider', 'sent_to_provider', 'connecting', 'connected', 'pre-generation', 'pre_generation', 'generating', 'post-processing', 'post_processing', 'generating-blurhash', 'generating_blurhash', 'generating-thumbnails', 'generating_thumbnails'].includes(job.status);
    const isPending = ['pending'].includes(job.status);

    // Extract metadata
    const meta = job.metadata || job.metadata_ || {};
    const checkpoint = typeof meta.checkpoint === 'object' ? meta.checkpoint?.name : meta.checkpoint;
    const checkpointShort = checkpoint ? checkpoint.replace('.safetensors', '').slice(0, 20) : null;
    const loraCount = (meta.loras || []).length;
    const dimensions = meta.width && meta.height ? `${meta.width}×${meta.height}` : null;
    const prompt = meta.prompt || '';
    const promptPreview = prompt.length > 60 ? prompt.slice(0, 60) + '...' : prompt;

    const providerName = getProviderDisplayName(job.provider_id) || (job.provider_id ? String(job.provider_id) : 'Auto/Queued');

    // ⚡ Bolt: Use a stable callback to prevent creating a new function on every render (especially when processing updates every second)
    const handleClick = useCallback(() => {
        onClick?.(job);
    }, [onClick, job]);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleClick();
        }
    }, [handleClick]);

    const handleDismiss = useCallback((e) => {
        e.stopPropagation();
        onDelete?.(job.id);
    }, [onDelete, job.id]);

    return (
        <div
            role="button"
            tabIndex={0}
            aria-label={`Job ${job.id || ''} - ${job.status}`}
            onClick={handleClick}
            onKeyDown={handleKeyDown}
            className="aspect-square bg-gray-800 rounded-xl overflow-hidden border border-gray-700 flex flex-col relative cursor-pointer hover:border-gray-500 transition-all card-elevated focus-visible:ring-2 focus-visible:ring-blue-500 outline-none group"
        >
            {/* Top Row: Provider + Status */}
            <div className="absolute top-0 left-0 right-0 flex justify-between items-start p-1.5 sm:p-2 z-10">
                {/* Provider Badge */}
                <div className="px-2 py-1 rounded text-[10px] sm:text-xs bg-purple-500/20 text-purple-400 flex items-center gap-1 backdrop-blur-sm">
                    <Server size={10} />
                    {providerName}
                </div>
                {/* Status Badge + Dismiss Button for terminal states */}
                <div className="flex items-center gap-1 ml-auto">
                    <div className={`px-2 py-1 rounded text-xs font-bold uppercase backdrop-blur-sm ${isSuccess ? 'bg-green-500/20 text-green-400' :
                        isError ? 'bg-red-500/20 text-red-400' :
                            isCancelled ? 'bg-gray-500/50 text-gray-300' :
                            'bg-blue-500/20 text-blue-400'
                        }`}>
                        {job.status}
                    </div>
                    {(isCancelled || isError) && onDelete && (
                        <button
                            onClick={handleDismiss}
                            className="p-1 rounded bg-black/40 hover:bg-red-600/80 text-gray-400 hover:text-white transition-colors backdrop-blur-sm opacity-0 group-hover:opacity-100"
                            title="Remove from history"
                            aria-label="Remove job from history"
                        >
                            <X size={12} aria-hidden="true" />
                        </button>
                    )}
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 flex flex-col items-center justify-center p-2 pt-10 sm:p-4 sm:pt-10 text-center">
                {isProcessing && !isPending ? (
                    <>
                        <PhaseIcon className={`animate-pulse ${phase.color} mb-1`} size={22} />

                        {/* Phase badge */}
                        <div className={`text-xs font-semibold uppercase tracking-wider ${phase.color} mb-2`}>
                            {phase.label}
                        </div>

                        {/* Job Info Row - Hidden on mobile to save vertical space */}
                        <div className="hidden sm:block w-full mb-2">
                            {checkpointShort && (
                                <p className="text-xs text-gray-400 truncate mb-1" title={checkpoint}>
                                    {checkpointShort}
                                </p>
                            )}
                            <div className="flex justify-center gap-2 text-xs text-gray-500 flex-wrap">
                                {dimensions && (
                                    <span className="flex items-center gap-1">
                                        <Box size={10} />
                                        {dimensions}
                                    </span>
                                )}
                                {meta.steps && (
                                    <span>{meta.steps} steps</span>
                                )}
                                {loraCount > 0 && (
                                    <span className="flex items-center gap-1">
                                        <Layers size={10} />
                                        {loraCount} LoRA{loraCount > 1 ? 's' : ''}
                                    </span>
                                )}
                            </div>
                        </div>

                        {/* Phase timeline dots - Hidden on mobile */}
                        <div className="hidden sm:flex items-center justify-center gap-1 mb-2">
                            {PHASE_ORDER.map((p, i) => {
                                const pIdx = PHASE_ORDER.indexOf(job.status);
                                const active = i <= pIdx && pIdx >= 0;
                                return (
                                    <div
                                        key={p}
                                        className={`h-1.5 rounded-full transition-all duration-300 ${
                                            active ? phase.bar + ' w-4' : 'bg-gray-700 w-1.5'
                                        }`}
                                    />
                                );
                            })}
                        </div>

                        {/* Progress Message */}
                        <p className="text-[10px] sm:text-sm font-medium text-white truncate w-full mb-1 sm:mb-2">
                            {job.message || 'Processing...'}
                        </p>

                        {/* Overall Progress */}
                        <div className="w-full">
                            <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                <div
                                    className="progress-gradient h-full transition-all duration-300 ease-out"
                                    style={{ width: `${job.overall_progress || 0}%` }}
                                />
                            </div>
                            <div className="flex justify-between text-[10px] sm:text-xs text-gray-500 mt-1">
                                <span>Workflow</span>
                                <span>{Math.round(job.overall_progress || 0)}%</span>
                            </div>
                        </div>

                        {/* Node Progress */}
                        {job.progress > 0 && (
                            <div className="w-full mt-1">
                                <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                    <div
                                        className="bg-gradient-to-r from-blue-500 to-cyan-400 h-full transition-all duration-300 ease-out"
                                        style={{ width: `${job.progress}%` }}
                                    />
                                </div>
                                <div className="flex justify-between text-[10px] sm:text-xs text-gray-500 mt-1">
                                    <span>Render</span>
                                    <span>{job.progress}%</span>
                                </div>
                            </div>
                        )}
                    </>
                ) : isSuccess ? (
                    <>
                        <div className="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center text-green-500 mb-2">
                            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        </div>
                        <p className="text-sm font-medium text-white">Complete</p>
                        {checkpointShort && (
                            <p className="text-xs text-gray-500 truncate mt-1" title={checkpoint}>
                                {checkpointShort}
                            </p>
                        )}
                    </>
                ) : isError ? (
                    <>
                        <div className="w-10 h-10 rounded-full bg-red-500/20 flex items-center justify-center text-red-500 mb-2">
                            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </div>
                        <p className="text-xs text-red-400 break-words">{job.message || job.error || "Failed"}</p>
                    </>
                ) : isCancelled ? (
                    /* Cancelled State */
                    <>
                        <div className="w-10 h-10 rounded-full bg-gray-700 flex items-center justify-center text-gray-400 mb-2">
                             <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line></svg>
                        </div>
                        <p className="text-sm font-medium text-gray-400">Cancelled</p>
                    </>
                ) : (
                    /* Pending/Queued State */
                    <>
                        <div className="w-10 h-10 rounded-full bg-gray-700 flex items-center justify-center text-gray-400 mb-2">
                            <Clock size={20} />
                        </div>
                        <p className="text-sm font-medium text-gray-300">Queued</p>

                        {/* Show job info even when queued */}
                        <div className="w-full mt-2 space-y-1">
                            {checkpointShort && (
                                <p className="text-xs text-gray-500 truncate" title={checkpoint}>
                                    {checkpointShort}
                                </p>
                            )}
                            <div className="flex justify-center gap-2 text-xs text-gray-600 flex-wrap">
                                {dimensions && (
                                    <span className="flex items-center gap-1">
                                        <Box size={10} />
                                        {dimensions}
                                    </span>
                                )}
                                {meta.steps && (
                                    <span>{meta.steps} steps</span>
                                )}
                            </div>
                        </div>

                        {job.queue_position && (
                            <p className="text-xs text-blue-400 font-bold mt-2">Position: #{job.queue_position}</p>
                        )}
                    </>
                )}
            </div>

            {/* Bottom Row: Prompt Preview + Elapsed Time */}
            {promptPreview && (
                <div className="absolute bottom-0 left-0 right-0 p-1.5 sm:p-2 bg-gradient-to-t from-gray-900/90 to-transparent">
                    <div className="flex items-center justify-between gap-2">
                        <p className="text-xs text-gray-500 truncate flex-1" title={prompt}>
                            {promptPreview}
                        </p>
                        {isProcessing && (
                            <ElapsedTime createdAt={job.created_at} isProcessing={isProcessing} />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
});

export default JobCard;
