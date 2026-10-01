import { memo, useCallback, useMemo } from 'react';
import { Loader2, Server, Cpu, Layers, Box, Clock, X, Send, Zap, RefreshCw } from 'lucide-react';
import { getProviderDisplayName } from '../../utils/providerUtils';
import { formatElapsed } from '../../utils/dateTime';
import { useJobStatus } from '../../hooks/useJobStatus';
import useGlobalClock from '../../hooks/useGlobalClock';
import {
    JOB_STATUS,
    JOB_PHASE_ORDER,
    isActiveJobStatus,
    isJobCancelled,
    isJobComplete,
    isJobFailed,
    jobMetadata,
} from '../../utils/jobStatus';

/**
 * The six live phases, plus `pending` so the order stays in step with the
 * backend lifecycle (it renders its own queued branch below). The three
 * terminal states deliberately have no entry — they render their own summary.
 *
 * The previous map also carried six snake_case twins and four reconciliation
 * phases ('validating', 'connecting', 'generating-blurhash',
 * 'generating-thumbnails'). None of those are job statuses, so the map was
 * twice the size it needed to be, and `PHASE_ORDER.indexOf(job.status)`
 * returned a wrong index for every real status because the phantom entries
 * shifted the timeline dots along.
 */
const PHASE_CONFIG = {
    [JOB_STATUS.PENDING]: { icon: Clock, label: 'Queued', color: 'text-gray-400', bar: 'bg-gray-600' },
    [JOB_STATUS.RETRYING]: { icon: RefreshCw, label: 'Retrying', color: 'text-orange-400', bar: 'bg-orange-500' },
    [JOB_STATUS.SENT_TO_PROVIDER]: { icon: Send, label: 'Sending', color: 'text-blue-400', bar: 'bg-blue-500' },
    [JOB_STATUS.CONNECTED]: { icon: Server, label: 'Connected', color: 'text-cyan-400', bar: 'bg-cyan-500' },
    [JOB_STATUS.PRE_GENERATION]: { icon: Zap, label: 'Preparing', color: 'text-yellow-400', bar: 'bg-yellow-500' },
    [JOB_STATUS.GENERATING]: { icon: Cpu, label: 'Generating', color: 'text-purple-400', bar: 'bg-purple-500' },
    [JOB_STATUS.POST_PROCESSING]: { icon: Layers, label: 'Processing', color: 'text-green-300', bar: 'bg-green-400' },
};

const PHASE_ORDER = JOB_PHASE_ORDER;

function getJobPhase(status) {
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

    const status = job.status || JOB_STATUS.PENDING;
    const phase = useMemo(() => getJobPhase(status), [status]);
    const PhaseIcon = phase.icon;

    const isSuccess = isJobComplete(status);
    const isError = isJobFailed(status);
    const isCancelled = isJobCancelled(status);
    // `pending` has its own queued branch, so it is not a processing phase.
    const isPending = status === JOB_STATUS.PENDING;
    const isProcessing = isActiveJobStatus(status) && !isPending;
    // -1 for terminal/unknown states, so the timeline stays empty rather than
    // lighting every dot up.
    const phaseIndex = PHASE_ORDER.indexOf(status);

    // Extract metadata
    const meta = jobMetadata(job);
    const checkpoint = typeof meta.checkpoint === 'object' ? meta.checkpoint?.name : meta.checkpoint;
    const checkpointShort = checkpoint ? checkpoint.replace('.safetensors', '').slice(0, 20) : null;
    const loraCount = (meta.loras || []).length;

    // `progress` is the sampler's own percentage and moves during the expensive
    // part; `overall_progress` counts completed nodes and is frozen while a
    // checkpoint sampler runs. Show whichever is actually moving, so the headline
    // number never sits still while the job visibly progresses. See the render
    // block below for the measured behaviour.
    const isSampling = job.progress > 0;
    const samplingProgress = isSampling ? job.progress : (job.overall_progress || 0);
    const nodeProgress = job.overall_progress || 0;
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
            aria-label={`Job ${job.id || ''} - ${status}`}
            onClick={handleClick}
            onKeyDown={handleKeyDown}
            className="aspect-square bg-gray-800 rounded-xl overflow-hidden border border-gray-700 flex flex-col relative cursor-pointer hover:border-gray-500 transition-all card-elevated focus-visible:ring-2 focus-visible:ring-blue-500 outline-none group"
        >
            {/* Top Row: Provider + Status */}
            <div className="absolute top-0 left-0 right-0 flex justify-between items-start p-1.5 sm:p-2 z-10">
                {/* Provider Badge */}
                <div className="px-2 py-1 rounded text-xs sm:text-xs bg-purple-500/20 text-purple-400 flex items-center gap-1 backdrop-blur-sm">
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
                        {status}
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
                                const active = i <= phaseIndex;
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
                        <p className="text-xs sm:text-sm font-medium text-white truncate w-full mb-1 sm:mb-2">
                            {job.message || 'Processing...'}
                        </p>

                        {/* Overall Progress */}
                        {/* Two progress fields, and they are not interchangeable.

                            `progress`          the SAMPLER's own percentage. Emitted
                                                on every ComfyUI `progress` frame and
                                                labelled server-side "Rendering: N%".
                                                Smooth, and it moves *during* the
                                                expensive part.
                            `overall_progress`  nodes executed / total nodes
                                                (services/provider_client.py:228).
                                                Coarse: a checkpoint sampler is one
                                                node and can run for a minute, so
                                                this is frozen for the whole time
                                                anything is actually happening and
                                                then jumps.

                            They were labelled the other way round — the node
                            counter was captioned "Workflow" and the sampler
                            percentage "Node" — and the frozen node counter was
                            the prominent one. That is what "progress is pooled"
                            looked like: the number sat still at 83% for fifteen
                            seconds while the bar underneath it, showing the
                            sampler, was the only thing moving.

                            Measured over a real 20-step generation: 24 socket
                            events in 40s at a 1.25s median — genuinely live — while
                            the node counter read 0, 58, 83, 83, 83, 100. */}
                        <div className="w-full">
                            <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                <div
                                    // Was `progress-gradient`, a hand-written class defined in no
                                    // stylesheet and not a Tailwind utility — so the fill was
                                    // transparent and this bar never painted, at any progress value.
                                    // Same class of loss as `.glass-panel`. Now a real utility.
                                    className="bg-gradient-to-r from-blue-500 to-cyan-400 h-full transition-all duration-300 ease-out"
                                    style={{ width: `${Math.round(samplingProgress)}%` }}
                                />
                            </div>
                            <div className="flex justify-between text-xs sm:text-xs text-gray-500 mt-1">
                                <span>{isSampling ? 'Sampling' : 'Workflow'}</span>
                                <span>{Math.round(samplingProgress)}%</span>
                            </div>
                        </div>

                        {/* Node counter. `> 0` rather than `!= null` is deliberate: progress is a
                            non-nullable float defaulting to 0, and both progress reducers coerce a
                            null/NaN/out-of-range event to 0, so 0 is the honest "nothing yet" value.
                            The bar is suppressed at 0 rather than showing an empty track. */}
                        {/* Only while the sampler is also reporting. Before that
                            the headline IS the node counter, so a second bar
                            would print the same number twice. */}
                        {isSampling && nodeProgress > 0 && (
                            <div className="w-full mt-1">
                                <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
                                    <div
                                        className="bg-gradient-to-r from-blue-500 to-cyan-400 h-full transition-all duration-300 ease-out"
                                        style={{ width: `${Math.round(nodeProgress)}%` }}
                                    />
                                </div>
                                <div className="flex justify-between items-center text-xs sm:text-xs text-blue-400 mt-1">
                                    <div className="flex items-center gap-1">
                                        <Loader2 size={10} className="animate-spin" />
                                        <span>Nodes</span>
                                    </div>
                                    <span>{Math.round(nodeProgress)}%</span>
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
