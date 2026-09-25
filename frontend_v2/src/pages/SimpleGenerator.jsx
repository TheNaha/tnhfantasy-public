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
    const { store: { prompt, randomizeSeed } } = useGeneratorCore();
    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    
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
            navigate('/gallery');
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
                    onGenerate={() => handleGenerate({ trackQueuedJob: true })}
                    onQueue={() => handleGenerate({ shouldRedirect: false, trackQueuedJob: false })}
                    onGenerateVariations={handleGenerateVariations}
                />
            }
        />
    );
}
