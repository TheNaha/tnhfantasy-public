import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Play, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import MissingModelsDialog from '../components/generator/MissingModelsDialog';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import useGenerationPreflight from '../hooks/useGenerationPreflight';
import useProvidersPageData from '../hooks/useProvidersPageData';
import { useTrackJob } from '../hooks/useTrackJob';
import useSettingsStore from '../store/settingsStore';
import { generateApi, createIdempotencyKey } from '../api';

export default function AdvancedGenerator() {
    const navigate = useNavigate();
    const [workflowJson, setWorkflowJson] = useState("");
    const [generating, setGenerating] = useState(false);
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const { data: trackedJob } = useTrackJob(currentJobId);
    const redirectAfterGenerate = useSettingsStore(state => state.settings.generator.redirectAfterGenerate);
    const redirectDelay = useSettingsStore(state => state.settings.generator.redirectDelay);
    const { providers, isLoading: providersLoading } = useProvidersPageData();
    const {
        isChecking: preflightChecking,
        validationResult,
        summary: validationSummary,
        isMissingModelsOpen,
        setIsMissingModelsOpen,
        runWithPreflight,
    } = useGenerationPreflight();

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
            if (redirectAfterGenerate) {
                setTimeout(() => navigate('/'), redirectDelay);
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
    }, [trackedJob, currentJobId, navigate, redirectAfterGenerate, redirectDelay]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const handleGenerate = async () => {
        try {
            const workflow = JSON.parse(workflowJson);
            setGenerating(true);
            setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });

            const submission = await runWithPreflight(workflow, {
                onValid: async () => generateApi.workflow(workflow, {}, {
                    idempotencyKey: createIdempotencyKey('generate-advanced')
                }),
            });
            if (!submission.ok) {
                setGenerating(false);
                setProgress(null);
                return;
            }

            const data = submission.submissionResult;
            if (data && data.id) {
                setCurrentJobId(data.id);
                setProgress({ value: 0, max: 100, status: 'queued', node: 'Job queued...' });
                toast.success('Job queued!', { icon: '⏳' });
            } else {
                toast.success("Job queued!");
                setGenerating(false);
                setProgress(null);
            }
        } catch (e) {
            toast.error(e instanceof SyntaxError ? "Error: Invalid JSON" : `Error: ${e.message}`);
            setGenerating(false);
            setProgress(null);
        }
    };

    return (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="h-[calc(100vh-140px)] flex flex-col">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
                <h2 className="text-2xl font-bold">Advanced Workflow</h2>
                <button
                    onClick={handleGenerate}
                    disabled={generating || !workflowJson}
                    className="px-6 py-2 bg-green-600 rounded-lg font-medium text-white hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {generating ? <Loader2 className="animate-spin" size={18} /> : <Play size={18} />}
                    Run Workflow
                </button>
            </div>

            {progress && (
                <div className="mb-4 bg-gray-900 rounded-lg border border-gray-800 p-3">
                    <div className="flex items-center justify-between text-xs text-gray-400 mb-2">
                        <span>{progress.node}</span>
                        <span>{progress.value}%</span>
                    </div>
                    <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
                        <div
                            className="h-full bg-green-500 rounded-full transition-all duration-300"
                            style={{ width: `${progress.value}%` }}
                        />
                    </div>
                </div>
            )}

            <div className="flex-1 bg-gray-950 rounded-xl border border-gray-800 overflow-hidden flex flex-col">
                <div className="bg-gray-900 px-4 py-2 border-b border-gray-800 text-xs text-gray-400 font-mono">
                    WORKFLOW JSON
                </div>
                <textarea
                    className="flex-1 w-full bg-gray-950 p-4 font-mono text-sm text-green-400 outline-none resize-none"
                    placeholder="Paste ComfyUI API Format JSON here..."
                    value={workflowJson}
                    onChange={(e) => setWorkflowJson(e.target.value)}
                />
            </div>

            <MissingModelsDialog
                isOpen={isMissingModelsOpen}
                onClose={() => setIsMissingModelsOpen(false)}
                validationResult={validationResult}
            />
            </div>

            <div className="space-y-4">
                <GeneratorReadinessPanel
                    providers={providers}
                    providersLoading={providersLoading}
                    validationSummary={validationSummary}
                    isChecking={preflightChecking}
                    title="Advanced Runway"
                    hint="Use the same preflight checks as the guided generators before running raw workflow JSON."
                />
                <div className="rounded-2xl border border-gray-800 bg-gray-950/70 p-4 text-sm text-gray-400">
                    Advanced mode preserves the raw ComfyUI workflow path, but validation still checks whether the referenced models exist on any enabled provider before queueing the job.
                </div>
            </div>
        </div>
    );
}
