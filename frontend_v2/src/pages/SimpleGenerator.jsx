import { useEffect, useRef } from 'react';
import { FolderOpen } from 'lucide-react';
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
        />
    );
}
