import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderOpen } from 'lucide-react';
import { useGeneratorCore } from '../../hooks/useGeneratorCore';
import { useActiveJobs } from '../../hooks/useActiveJobs';
import { useModelDirectories } from '../../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../../constants/modelDirectories';
import GeneratorShell from './GeneratorShell';
import PromptPanel from './PromptPanel';
import ModelSection from './ModelSection';
import ControlNetSection from './ControlNetSection';
import IPAdapterSection from './IPAdapterSection';
import EnhancementsSection from './EnhancementsSection';
import GeneratorReadinessPanel from './GeneratorReadinessPanel';
import SamplingSettings from './SamplingSettings';
import ModelMetadataModal from '../ModelMetadataModal';

/**
 * Unified Layout for Generator Pages
 * Consolidates the shared UI states and components across Simple, Img2Img, and Inpaint.
 */
export default function UnifiedGeneratorLayout({
    mode = 't2i', // 't2i', 'img2img', 'inpaint', 'advanced'
    accentClass,
    runwayTitle = 'Generation Runway',
    runwayHint = 'Provider health and model checks before you commit a generation.',
    leftColumnTop,
    leftColumnBottom,
    rightColumnMiddle,
    rightColumnBottom,
    mobileActionBar
}) {
    const navigate = useNavigate();
    const [viewingMetadata, setViewingMetadata] = useState(null);
    const [autoOpenLoraIndex, setAutoOpenLoraIndex] = useState(null);

    const {
        store: {
            prompt, negativePrompt,
            selectedCheckpoint, selectedVae, selectedClip, selectedClip2, selectedLoras, controlnets,
            hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
            adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise, adetailerInpaintMasked,
            setPrompt, setNegativePrompt,
            setSelectedCheckpoint, setSelectedVae, setSelectedClip, setSelectedClip2,
            setHiresFix, setHiresUpscaler, setHiresDenoise, setHiresUpscale, setHiresSteps,
            setAdetailer, setAdetailerModel, setAdetailerPrompt, setAdetailerSteps, setAdetailerDenoise, setAdetailerInpaintMasked,
            enableFreeU, setEnableFreeU, enablePAG, setEnablePAG, pagScale, setPagScale,
            enableLatentUpscale, setEnableLatentUpscale, latentUpscaleMultiplier, setLatentUpscaleMultiplier,
            addLora, removeLora, updateLora, addControlNet, removeControlNet, updateControlNet,
            ipAdapters, addIpAdapter, removeIpAdapter, updateIpAdapter,
            addTriggerWords
        },
        providers, providersLoading,
        preflight: {
            isChecking: preflightChecking,
            validationResult,
            summary: validationSummary,
            isMissingModelsOpen,
            setIsMissingModelsOpen,
        }
    } = useGeneratorCore();

    const { modelsByKey } = useModelDirectories(GENERATOR_MODEL_REQUESTS);
    const checkpoints = modelsByKey.checkpoints || [];
    const controlNetModels = modelsByKey.controlNetModels || [];
    const upscalerModels = modelsByKey.upscalerModels || [];
    const vaeModels = modelsByKey.vaeModels || [];
    const unetModels = modelsByKey.unetModels || [];
    const clipModels = modelsByKey.clipModels || [];
    const embeddingModels = modelsByKey.embeddingModels || [];
    const adetailerModels = modelsByKey.adetailerModels || [];

    const { data: activeJobs = [] } = useActiveJobs();
    const activeJobCount = activeJobs.length;

    // Advanced mode uses entirely its own inner structure in GeneratorShell
    if (mode === 'advanced') {
        return (
            <GeneratorShell
                accentClass={accentClass}
                activeJobCount={activeJobCount}
                isMissingModelsOpen={isMissingModelsOpen}
                setIsMissingModelsOpen={setIsMissingModelsOpen}
                validationResult={validationResult}
                leftColumn={leftColumnTop}
                rightColumn={rightColumnBottom}
            />
        );
    }

    return (
        <>
            <GeneratorShell
                accentClass={accentClass}
                activeJobCount={activeJobCount}
                gapClass="gap-3 lg:gap-8"
                leftColumnClass="order-last lg:order-none"
                rightColumnClass="order-first lg:order-none"
                isMissingModelsOpen={isMissingModelsOpen}
                setIsMissingModelsOpen={setIsMissingModelsOpen}
                validationResult={validationResult}
                leftColumn={(
                    <>
                        {leftColumnTop}
                        
                        <PromptPanel />

                        <div className="space-y-4 pb-4 border-b border-gray-800">
                            <ModelSection
                                selectedCheckpoint={selectedCheckpoint}
                                setSelectedCheckpoint={setSelectedCheckpoint}
                                selectedVae={selectedVae}
                                setSelectedVae={setSelectedVae}
                                selectedClip={selectedClip}
                                setSelectedClip={setSelectedClip}
                                selectedClip2={selectedClip2}
                                setSelectedClip2={setSelectedClip2}
                                selectedLoras={selectedLoras}
                                addLora={addLora}
                                removeLora={removeLora}
                                updateLora={updateLora}
                                addTriggerWords={addTriggerWords}
                                prompt={prompt}
                                negativePrompt={negativePrompt}
                                setPrompt={setPrompt}
                                setNegativePrompt={setNegativePrompt}
                                checkpoints={checkpoints}
                                unetModels={unetModels}
                                vaeModels={vaeModels}
                                clipModels={clipModels}
                                embeddingModels={embeddingModels}
                                setViewingMetadata={setViewingMetadata}
                                providers={providers}
                                providersLoading={providersLoading}
                                autoOpenLoraIndex={autoOpenLoraIndex}
                                setAutoOpenLoraIndex={setAutoOpenLoraIndex}
                            />

                            <ControlNetSection
                                controlnets={controlnets}
                                addControlNet={addControlNet}
                                removeControlNet={removeControlNet}
                                updateControlNet={updateControlNet}
                                controlNetModels={controlNetModels}
                            />

                            <IPAdapterSection
                                ipAdapters={ipAdapters}
                                addIpAdapter={addIpAdapter}
                                removeIpAdapter={removeIpAdapter}
                                updateIpAdapter={updateIpAdapter}
                            />

                            <EnhancementsSection
                                hiresFix={mode === 't2i' ? hiresFix : undefined}
                                setHiresFix={setHiresFix}
                                hiresUpscaler={hiresUpscaler}
                                setHiresUpscaler={setHiresUpscaler}
                                hiresDenoise={hiresDenoise}
                                setHiresDenoise={setHiresDenoise}
                                hiresUpscale={hiresUpscale}
                                setHiresUpscale={setHiresUpscale}
                                hiresSteps={hiresSteps}
                                setHiresSteps={setHiresSteps}
                                upscalerModels={upscalerModels}
                                adetailer={adetailer}
                                setAdetailer={setAdetailer}
                                adetailerModel={adetailerModel}
                                setAdetailerModel={setAdetailerModel}
                                adetailerPrompt={adetailerPrompt}
                                setAdetailerPrompt={setAdetailerPrompt}
                                adetailerSteps={adetailerSteps}
                                setAdetailerSteps={setAdetailerSteps}
                                adetailerDenoise={adetailerDenoise}
                                setAdetailerDenoise={setAdetailerDenoise}
                                adetailerInpaintMasked={adetailerInpaintMasked}
                                setAdetailerInpaintMasked={setAdetailerInpaintMasked}
                                adetailerModels={adetailerModels}
                                enableFreeU={enableFreeU}
                                setEnableFreeU={setEnableFreeU}
                                enablePAG={enablePAG}
                                setEnablePAG={setEnablePAG}
                                pagScale={pagScale}
                                setPagScale={setPagScale}
                                enableLatentUpscale={enableLatentUpscale}
                                setEnableLatentUpscale={setEnableLatentUpscale}
                                latentUpscaleMultiplier={latentUpscaleMultiplier}
                                setLatentUpscaleMultiplier={setLatentUpscaleMultiplier}
                            />
                        </div>
                        {leftColumnBottom}
                    </>
                )}
                rightColumn={(
                    <>
                        <GeneratorReadinessPanel
                            providers={providers}
                            providersLoading={providersLoading}
                            validationSummary={validationSummary}
                            isChecking={preflightChecking}
                            title={runwayTitle}
                            hint={runwayHint}
                        />

                        {rightColumnMiddle}
                        
                        <SamplingSettings />

                        <div className="hidden md:block">
                            {rightColumnBottom}
                        </div>
                    </>
                )}
            />

            <div className="h-20 md:hidden"></div>

            <div className="fixed bottom-0 left-0 right-0 p-3 bg-gray-900/95 backdrop-blur-xl border-t border-gray-800 md:hidden z-30 pb-safe">
                {mobileActionBar || rightColumnBottom}
            </div>

            {viewingMetadata && (
                <ModelMetadataModal
                    metadata={viewingMetadata}
                    providers={providers}
                    providersLoading={providersLoading}
                    onClose={() => setViewingMetadata(null)}
                />
            )}

            <button
                onClick={() => navigate('/gallery')}
                className="fixed bottom-6 right-6 z-40 md:hidden bg-purple-600 hover:bg-purple-500 text-white p-4 rounded-full shadow-lg transition-all transform hover:scale-110 flex items-center gap-2"
                title="Go to Gallery"
            >
                <FolderOpen size={24} />
            </button>
        </>
    );
}
