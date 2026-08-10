import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import useSettingsStore from '../store/settingsStore';
import { useJobStatus } from './useJobStatus';

/**
 * useGeneratorJob — unified job-tracking state + shared generation flow for the
 * guided generator pages (Simple / Img2Img / Inpaint).
 *
 * Replaces the old `useTrackGenerationJob` (state + WebSocket->toast effect) and
 * the `handleGenerate` boilerplate that was copy-pasted across the three guided
 * generators. AdvancedGenerator consumes this hook for the shared state setters
 * only — its handler has a different UX (raw workflow editor) and is kept local.
 *
 * Behaviour is parameterised so each generator's *exact* queue-mode progress
 * behaviour is preserved:
 *  - Simple: `setGeneratingOnQueue === false`  -> queue mode is silent (no
 *    progress bar, no `finally` reset), matching its original handler.
 *  - Img2Img / Inpaint: `setGeneratingOnQueue === true` -> queue mode briefly
 *    shows the bar then resets via `finally`, matching their original handlers.
 *
 * @param {object}  opts
 * @param {() => Promise<{ok:boolean, submissionResult?:object}>} [opts.runSubmission]
 *   Builds the workflow+metadata for this generator and returns the
 *   `runWithPreflight` submission result. May receive a `{ setProgress,
 *   setGenerating }` bag so a variant can update progress mid-submission
 *   (e.g. Inpaint uploads a mask between progress steps).
 * @param {string}  [opts.type]                 idempotency-key prefix / label (default 'simple').
 * @param {boolean} [opts.setGeneratingOnQueue] queue-mode progress behaviour (default true).
 * @param {string}  [opts.startingNode]         progress node shown while submitting.
 * @param {() => string|undefined|null} [opts.validate]
 *   Return an error string to short-circuit, or falsy to proceed.
 * @param {() => void} [opts.randomizeSeed]
 * @param {boolean} [opts.autoRandomizeSeed]
 * @param {boolean} [opts.redirectAfterGenerate]  override settings redirect.
 * @returns {{currentJobId, setCurrentJobId, progress, setProgress,
 *            generating, setGenerating, handleGenerate}}
 */
export function useGeneratorJob(opts = {}) {
    const {
        runSubmission,
        type = 'simple',
        setGeneratingOnQueue = true,
        startingNode = 'Initializing...',
        validate,
        randomizeSeed,
        autoRandomizeSeed = false,
        redirectAfterGenerate: redirectOverride,
    } = opts;

    const navigate = useNavigate();
    const settingsRedirect = useSettingsStore((s) => s.settings?.generator?.redirectAfterGenerate);
    const redirectDelay = useSettingsStore((s) => s.settings?.generator?.redirectDelay);
    const redirectAfterGenerate =
        redirectOverride !== undefined ? redirectOverride : settingsRedirect;

    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [generating, setGenerating] = useState(false);
    const { data: jobData } = useJobStatus(currentJobId);
    const redirectTimerRef = useRef(null);

    // ---- WebSocket / REST job subscription -> toast + state (verbatim port) ----
    useEffect(() => {
        return () => {
            if (redirectTimerRef.current) {
                clearTimeout(redirectTimerRef.current);
                redirectTimerRef.current = null;
            }
        };
    }, []);

    useEffect(() => {
        if (!currentJobId || !jobData) return;

        const isQueued = jobData.status === 'pending' || jobData.status === 'queued';
        const progressValue = jobData.overall_progress ?? jobData.progress ?? 0;

        if (jobData.status === 'completed') {
            /* eslint-disable-next-line react-hooks/exhaustive-deps */
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.success('Generation complete!', { icon: '✨' });
            if (redirectAfterGenerate) {
                redirectTimerRef.current = setTimeout(() => navigate('/'), redirectDelay);
            }
            return;
        }

        if (jobData.status === 'failed') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.error(`Generation failed: ${jobData.error || jobData.message || 'Unknown error'}`);
            return;
        }

        if (jobData.status === 'cancelled') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast('Generation cancelled');
            return;
        }

        setGenerating(true);
        setProgress({
            value: progressValue,
            max: 100,
            status: isQueued ? 'queued' : jobData.status,
            node: jobData.message || (isQueued ? 'Job queued...' : `${progressValue}%`),
        });
    }, [jobData, currentJobId, navigate, redirectAfterGenerate, redirectDelay]);

    // ---- Shared generate handler (port of Simple/Img2Img/Inpaint handleGenerate) ----
    const handleGenerate = async ({ shouldRedirect = true, trackQueuedJob = true } = {}) => {
        const validationError = validate ? validate() : null;
        if (validationError) {
            toast.error(validationError);
            return;
        }

        if (trackQueuedJob) {
            setGenerating(true);
            setProgress({ value: 0, max: 100, status: 'starting', node: startingNode });
        } else if (setGeneratingOnQueue) {
            // Img2Img / Inpaint: brief progress flash in queue mode.
            setGenerating(true);
        }
        // Simple queue mode (setGeneratingOnQueue === false): intentionally silent.

        try {
            const submission = await (runSubmission
                ? runSubmission({ setProgress, setGenerating, type })
                : Promise.resolve({ ok: false }));

            if (!submission.ok) {
                if (trackQueuedJob) {
                    setGenerating(false);
                    setProgress(null);
                }
                return;
            }

            const data = submission.submissionResult;

            if (data && data.id) {
                if (trackQueuedJob) {
                    setCurrentJobId(data.id);
                    setGenerating(true);
                    setProgress({ value: 0, max: 100, status: 'queued', node: 'Job queued...' });
                    toast.success('Job queued!', { icon: '⏳' });
                } else {
                    toast.success('Added to queue!', { icon: '➕' });
                }

                if (shouldRedirect) navigate('/');
                if (autoRandomizeSeed) randomizeSeed?.();
            }
        } catch (e) {
            console.error(e);
            toast.error('Error: ' + (e?.message || e));
            if (trackQueuedJob) {
                setGenerating(false);
                setProgress(null);
            }
        } finally {
            if (!trackQueuedJob && setGeneratingOnQueue) {
                setGenerating(false);
            }
        }
    };

    return {
        currentJobId,
        setCurrentJobId,
        progress,
        setProgress,
        generating,
        setGenerating,
        handleGenerate,
    };
}
