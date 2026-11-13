import { useEffect, useState } from 'react';
import { FolderOpen, Settings2, AlertCircle } from 'lucide-react';
import { useGeneratorCore } from '../hooks/useGeneratorCore';
import toast from 'react-hot-toast';
import useSettingsStore from '../store/settingsStore';
import { generateApi, createIdempotencyKey } from '../api';

import { useWorkflowBuilder } from '../hooks/useWorkflowBuilder';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import { useNavigate } from 'react-router-dom';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';
import ResolutionSettings from '../components/generator/ResolutionSettings';
import GenerateButtonBar from '../components/generator/GenerateButtonBar';
import GenerationTelemetry from '../components/common/GenerationTelemetry';

export default function SimpleGenerator() {
    const navigate = useNavigate();
    const { store: { prompt, randomizeSeed, selectedCheckpoint } } = useGeneratorCore();
    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);

    // Simple mode hides advanced sampling parameters (steps, CFG, sampler,
    // scheduler, clip skip, seed) behind a toggle. Locking on those parameters
    // (`lockedParams` / `toggleParamLock` in SamplingSettings) is untouched:
    // when advanced mode is shown, every lock control works exactly as before.
    const [isSimpleMode, setIsSimpleMode] = useState(() => {
        if (typeof window === 'undefined') return true;
        try {
            const saved = localStorage.getItem('simple-generator-mode');
            return saved !== null ? saved === 'simple' : true;
        } catch {
            return true;
        }
    });

    useEffect(() => {
        try {
            localStorage.setItem('simple-generator-mode', isSimpleMode ? 'simple' : 'advanced');
        } catch {
            // localStorage may be unavailable (e.g. private browsing)
        }
    }, [isSimpleMode]);

    const { buildPayload, runSubmission, runWithPreflight } = useWorkflowBuilder('t2i');

    useKeyboardShortcuts();

    const {
        progress,
        generating,
        setGenerating,
        handleGenerate,
        lastCompletedJob,
        scheduleRedirect,
    } = useGeneratorJob({
        runSubmission,
        type: 'simple',
        setGeneratingOnQueue: false,
        randomizeSeed,
        autoRandomizeSeed,
    });


    const handleGenerateVariations = async (count) => {
        setGenerating(true);

        try {
            const payloads = [];
            for (let i = 0; i < count; i++) {
                const variationSeed = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
                payloads.push({
                    ...buildPayload(variationSeed),
                    variationSeed,
                    index: i,
                });
            }

            const validation = await runWithPreflight(payloads[0]?.options);
            if (!validation.ok) return;

            const jobs = payloads.map(({ options, metadata, index }) => (
                generateApi.workflow(options, metadata, {
                    idempotencyKey: createIdempotencyKey(`generate-variation-${index}`)
                })
            ));

            await Promise.all(jobs);
            toast.success(`Queued ${count} variations!`, { icon: '🎲' });
            if (autoRandomizeSeed) randomizeSeed();
            scheduleRedirect();
        } catch (e) {
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="max-w-6xl mx-auto">
            {/* Checkpoint hint when no model is selected */}
            {!selectedCheckpoint?.name && (
                <div className="mb-4 p-3 bg-amber-900/20 border border-amber-500/30 rounded-lg">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                        <div>
                            <p className="text-sm text-amber-200 font-medium">No checkpoint selected</p>
                            <p className="text-xs text-amber-300 mt-0.5 leading-relaxed">
                                Select a model in the <strong>Models</strong> card below before generating. The Generate button stays disabled until a checkpoint is chosen.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            {/* Simple / Advanced mode toggle */}
            <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Settings2 className="w-4 h-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-300">
                        {isSimpleMode ? 'Simple mode' : 'Advanced mode'}
                    </span>
                </div>
                <button
                    type="button"
                    role="switch"
                    aria-checked={!isSimpleMode}
                    aria-label={`Switch to ${isSimpleMode ? 'advanced' : 'simple'} mode`}
                    onClick={() => setIsSimpleMode(prev => !prev)}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${
                        !isSimpleMode ? 'bg-blue-600' : 'bg-gray-700'
                    }`}
                >
                    <span
                        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                            !isSimpleMode ? 'translate-x-5' : 'translate-x-0'
                        }`}
                        aria-hidden="true"
                    />
                </button>
            </div>

            <UnifiedGeneratorLayout
                mode="t2i"
                accentClass="from-blue-400 to-purple-500"
                runwayTitle="Generation Runway"
                runwayHint="Provider health and model checks before you commit a generation."
                rightColumnMiddle={<ResolutionSettings />}
                rightColumnExtra={
                    (() => {
                        const lastTimings = lastCompletedJob?.timings
                            || lastCompletedJob?.diagnostics?.timings
                            || lastCompletedJob?.metadata_?.diagnostics?.timings;
                        if (!lastTimings) return null;
                        return (
                            <div className="space-y-2">
                                <GenerationTelemetry
                                    timings={lastTimings}
                                    title="Last Generation Speed"
                                    collapsible={true}
                                    defaultExpanded={true}
                                />
                                <button
                                    type="button"
                                    onClick={() => navigate('/gallery')}
                                    className="w-full py-2 px-3 bg-gray-800/80 hover:bg-gray-700/80 border border-white/10 rounded-xl text-xs font-semibold text-gray-300 hover:text-white flex items-center justify-center gap-1.5 transition-colors"
                                >
                                    <span>View Result in Gallery →</span>
                                </button>
                            </div>
                        );
                    })()
                }
                rightColumnBottom={
                    <GenerateButtonBar
                        generating={generating}
                        progress={progress}
                        prompt={prompt}
                        // Nothing selects a checkpoint for you — `selectedCheckpoint`
                        // is null in the store until you pick one — so the form used
                        // to submit `ckpt_name: ""` and fail on the provider a
                        // minute later with a message that named the provider. On a
                        // phone this is likelier still: the model picker sits well
                        // below the fold of a 3-screen form.
                        blockingReason={!selectedCheckpoint?.name
                            ? 'Select a checkpoint first'
                            : null}
                        onGenerate={() => handleGenerate({ trackQueuedJob: true })}
                        onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                        onGenerateVariations={handleGenerateVariations}
                    />
                }
                showAdvancedSampling={!isSimpleMode}
                showAdvancedSections={!isSimpleMode}
            />
        </div>
    );
}
