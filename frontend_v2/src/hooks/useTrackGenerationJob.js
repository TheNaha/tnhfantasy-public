import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useSettings } from '../store/settingsStore';
import { useTrackJob } from './useTrackJob';

export function useTrackGenerationJob() {
    const navigate = useNavigate();
    const settings = useSettings();
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [generating, setGenerating] = useState(false);
    const { data: trackedJob } = useTrackJob(currentJobId);

    // legitimate: syncing state from external WebSocket subscription
    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        if (!currentJobId || !trackedJob) return;

        const isQueued = trackedJob.status === 'pending' || trackedJob.status === 'queued';
        const progressValue = trackedJob.overall_progress ?? trackedJob.progress ?? 0;

        if (trackedJob.status === 'completed') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.success('Generation complete!', { icon: '✨' });
            if (settings.generator.redirectAfterGenerate) {
                setTimeout(() => navigate('/'), settings.generator.redirectDelay);
            }
            return;
        }

        if (trackedJob.status === 'failed') {
            setGenerating(false);
            setProgress(null);
            setCurrentJobId(null);
            toast.error(`Generation failed: ${trackedJob.error || 'Unknown error'}`);
            return;
        }

        if (trackedJob.status === 'cancelled') {
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
            status: isQueued ? 'queued' : trackedJob.status,
            node: trackedJob.message || (isQueued ? 'Job queued...' : `${progressValue}%`),
        });
    }, [
        trackedJob, currentJobId,
        navigate, settings.generator.redirectAfterGenerate, settings.generator.redirectDelay,
    ]);
    /* eslint-enable react-hooks/set-state-in-effect */

    return {
        currentJobId,
        setCurrentJobId,
        progress,
        setProgress,
        generating,
        setGenerating,
    };
}
