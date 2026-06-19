import { useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useGeneratorStore } from '../store/generatorStore';
import useProvidersPageData from './useProvidersPageData';
import useGenerationPreflight from './useGenerationPreflight';

export const generatorCoreSelector = (state) => ({
    prompt: state.prompt,
    negativePrompt: state.negativePrompt,
    seed: state.seed,
    steps: state.steps,
    cfg: state.cfg,
    sampler: state.sampler,
    scheduler: state.scheduler,
    width: state.width,
    height: state.height,
    batchSize: state.batchSize,
    selectedCheckpoint: state.selectedCheckpoint,
    selectedVae: state.selectedVae,
    selectedClip: state.selectedClip,
    selectedClip2: state.selectedClip2,
    selectedLoras: state.selectedLoras,
    controlnets: state.controlnets,
    hiresFix: state.hiresFix,
    hiresUpscaler: state.hiresUpscaler,
    hiresDenoise: state.hiresDenoise,
    hiresUpscale: state.hiresUpscale,
    hiresSteps: state.hiresSteps,
    adetailer: state.adetailer,
    adetailerModel: state.adetailerModel,
    adetailerPrompt: state.adetailerPrompt,
    adetailerSteps: state.adetailerSteps,
    adetailerDenoise: state.adetailerDenoise,
    adetailerInpaintMasked: state.adetailerInpaintMasked,
    sourceImage: state.sourceImage,
    denoise: state.denoise,
    maskImage: state.maskImage,
    maskBlur: state.maskBlur,
    setPrompt: state.setPrompt,
    setNegativePrompt: state.setNegativePrompt,
    setSeed: state.setSeed,
    setSteps: state.setSteps,
    setCfg: state.setCfg,
    setSampler: state.setSampler,
    setScheduler: state.setScheduler,
    setWidth: state.setWidth,
    setHeight: state.setHeight,
    setBatchSize: state.setBatchSize,
    setAspectRatioLocked: state.setAspectRatioLocked,
    setSelectedCheckpoint: state.setSelectedCheckpoint,
    setSelectedVae: state.setSelectedVae,
    setSelectedClip: state.setSelectedClip,
    setSelectedClip2: state.setSelectedClip2,
    setHiresFix: state.setHiresFix,
    setHiresUpscaler: state.setHiresUpscaler,
    setHiresDenoise: state.setHiresDenoise,
    setHiresUpscale: state.setHiresUpscale,
    setHiresSteps: state.setHiresSteps,
    setAdetailer: state.setAdetailer,
    setAdetailerModel: state.setAdetailerModel,
    setAdetailerPrompt: state.setAdetailerPrompt,
    setAdetailerSteps: state.setAdetailerSteps,
    setAdetailerDenoise: state.setAdetailerDenoise,
    setAdetailerInpaintMasked: state.setAdetailerInpaintMasked,
    setSourceImage: state.setSourceImage,
    setDenoise: state.setDenoise,
    setMaskImage: state.setMaskImage,
    setMaskBlur: state.setMaskBlur,
    clearSourceImage: state.clearSourceImage,
    randomizeSeed: state.randomizeSeed,
    addLora: state.addLora,
    removeLora: state.removeLora,
    updateLora: state.updateLora,
    addControlNet: state.addControlNet,
    removeControlNet: state.removeControlNet,
    updateControlNet: state.updateControlNet,
    addTriggerWords: state.addTriggerWords,
    aspectRatioLocked: state.aspectRatioLocked,
});

export function useGeneratorCore() {
    const store = useGeneratorStore(useShallow(generatorCoreSelector));
    const [generating, setGenerating] = useState(false);
    
    const { providers, isLoading: providersLoading } = useProvidersPageData();
    const preflight = useGenerationPreflight();

    return {
        store,
        generating,
        setGenerating,
        providers,
        providersLoading,
        preflight,
    };
}
