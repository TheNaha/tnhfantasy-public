import { useEffect, useRef, useState } from 'react';
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

export default function SimpleGenerator() {
    const navigate = useNavigate();
    const { store: { prompt, randomizeSeed, selectedCheckpoint } } = useGeneratorCore();
    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const redirectAfterGenerate = useSettingsStore(state => state.settings.generator.redirectAfterGenerate);
    const redirectDelay = useSettingsStore(state => state.settings.generator.redirectDelay);

    // Simple mode hides advanced sampling parameters (steps, CFG, sampler,
    // scheduler, clip skip, seed) behind a toggle. Locking on those parameters
    // (`lockedParams` / `toggleParamLock` in SamplingSettings) is untouched:
    // when advanced mode is shown, every lock control works exactly as before.
    const [isSimpleMode, setIsSimpleMode] = useState(true);
    
    const { buildPayload, runSubmission, runWithPreflight } = useWorkflowBuilder('t2i');

    useKeyboardShortcuts();

    const {
        progress,
        generating,
        setGenerating,
        handleGenerate,
    } = useGeneratorJob({
        runSubmission,
        type: 'simple',
        setGeneratingOnQueue: false,
        randomizeSeed,
        autoRandomizeSeed,
    });

    // The variations path used to `navigate('/gallery')` the instant the queue
    // acknowledged, ignoring both `redirectAfterGenerate` and `redirectDelay`:
    // the two settings that are documented to control exactly this, and the two
    // every other generate button on the page honours. It also bypassed
    // `useGeneratorJob` entirely, so it got none of the redirect-timer
    // handling — including the unmount cleanup, which is what makes a delayed
    // navigation actually fire instead of being cancelled by the page it
    // unmounts.
    //
    // Duplicated from `useGeneratorJob` rather than imported: that hook owns
    // its timer privately and `src/hooks/` belongs to another workstream. The
    // two blocks should collapse into one when that file is next touched.
    const redirectTimerRef = useRef(null);
    useEffect(() => () => {
        if (redirectTimerRef.current) {
            clearTimeout(redirectTimerRef.current);
            redirectTimerRef.current = null;
        }
    }, []);

    const scheduleGalleryRedirect = () => {
        if (!redirectAfterGenerate) return;
        const delayMs = Number.isFinite(Number(redirectDelay))
            ? Math.max(0, Number(redirectDelay))
            : 0;
        if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
        redirectTimerRef.current = setTimeout(() => {
            redirectTimerRef.current = null;
            navigate('/gallery');
        }, delayMs);
    };

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
            scheduleGalleryRedirect();
        } catch (e) {
            toast.error("Error: " + e.message);
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="max-w-6xl mx-auto">
            {/* Simple / Advanced mode toggle */}
            <div className="mb-4 flex items-center justify-between px-2">
                <div className="flex items-center gap-2">
                    <Settings2 className="w-4 h-4 text-gray-400" />
                    <span className="text-sm font-medium text-gray-300">
                        {isSimpleMode ? 'Simple mode' : 'Advanced mode'}
                    </span>
                </div>
                <button
                    onClick={() => setIsSimpleMode(prev => !prev)}
                    className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${isSimpleMode ? 'bg-blue-600' : 'bg-gray-700'}`}
                    aria-label="Toggle simple/advanced mode"
                >
                    <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ${isSimpleMode ? 'translate-x-6' : 'translate-x-1'}`}
                        aria-hidden="true"
                    />
                </button>
            </div>

            {/* Checkpoint hint when no model is selected */}
            {!selectedCheckpoint?.name && (
                <div className="mb-4 p-3 bg-amber-900/20 border border-amber-500/30 rounded-lg">
                    <div className="flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
                        <div>
                            <p className="text-sm text-amber-200 font-medium">No checkpoint selected</p>
                            <p className="text-xs text-amber-300 mt-0.5 leading-relaxed">
                                Pick a model on the <strong>Installed Models</strong> page, or select one from the
                                Checkpoint dropdown below, before generating. The Generate button stays disabled until
                                a checkpoint is chosen.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            <UnifiedGeneratorLayout
                mode="t2i"
                accentClass="from-blue-400 to-purple-500"
                runwayTitle="Generation Runway"
                runwayHint="Provider health and model checks before you commit a generation."
                rightColumnMiddle={<ResolutionSettings />}
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
            />
        </div>
    );
}
