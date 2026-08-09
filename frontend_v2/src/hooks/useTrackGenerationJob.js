import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import useSettingsStore from '../store/settingsStore';
import { useJobStatus } from './useJobStatus';

export function useTrackGenerationJob() {
    const navigate = useNavigate();
    const redirectAfterGenerate = useSettingsStore((s) => s.settings?.generator?.redirectAfterGenerate);
    const redirectDelay = useSettingsStore((s) => s.settings?.generator?.redirectDelay);
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [generating, setGenerating] = useState(false);
    const { data: jobData } = useJobStatus(currentJobId);
    const redirectTimerRef = useRef(null);

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
            // syncing state from external WebSocket job subscription
            /* eslint-disable-next-line react-hooks/set-state-in-effect */
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
    }, [
        jobData, currentJobId,
        navigate, redirectAfterGenerate, redirectDelay,
    ]);    return {
        currentJobId,
        setCurrentJobId,
        progress,
        setProgress,
        generating,
        setGenerating,
    };
}
