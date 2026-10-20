import { memo } from 'react';
import { Sparkles } from 'lucide-react';
import CollapsibleSection from '../CollapsibleSection';

/**
 * A short note about what the provider can do.
 *
 * `capabilities` is the answer from `GET /api/nodes/capabilities` for the
 * provider the job will run on: which node classes it has, and which files
 * it has for each of them.
 *
 * The panel used to hardcode the provider's node vocabulary in Python and
 * offer a FreeU toggle to a provider with no FreeU node - and the request
 * failed at dispatch with "node type not found", after the user had picked
 * the enhancement and waited for the job.
 *
 * `known: false` means the answer could not be obtained (the provider is
 * down, or has never been introspected). That is NOT the same as "not
 * supported": a provider that is down must not be read as a provider that
 * cannot do FreeU, so the control stays live and nothing is claimed.
 */
function capabilityNote(capabilities, key, what) {
    if (!capabilities || !capabilities.known) return null;
    if (capabilities.nodes?.[key] !== false) return null;
    return `The provider does not have the ${what} node, so this cannot be applied.`;
}

function UnsupportedHint({ children }) {
    if (!children) return null;
    return (
        <p className="text-xs text-amber-400/90 leading-relaxed" role="note">
            {children}
        </p>
    );
}

const EnhancementsSection = memo(function EnhancementsSection({
    capabilities = null,
    modelType = 'sd15',
    hiresFix,
    setHiresFix,
    hiresUpscaler,
    setHiresUpscaler,
    hiresDenoise,
    setHiresDenoise,
    hiresUpscale,
    setHiresUpscale,
    hiresSteps,
    setHiresSteps,
    upscalerModels,
    adetailer,
    setAdetailer,
    adetailerModel,
    setAdetailerModel,
    adetailerPrompt,
    setAdetailerPrompt,
    adetailerSteps,
    setAdetailerSteps,
    adetailerDenoise,
    setAdetailerDenoise,
    adetailerInpaintMasked,
    setAdetailerInpaintMasked,
    adetailerModels,
    enableFreeU,
    setEnableFreeU,
    enablePAG,
    setEnablePAG,
    pagScale,
    setPagScale,
    enableLatentUpscale,
    setEnableLatentUpscale,
    latentUpscaleMultiplier,
    setLatentUpscaleMultiplier
}) {
    // What the provider can do.
    //
    // "Not known" and "not supported" are different: a provider that is
    // down is not a provider that cannot do FreeU, so an unavailable
    // answer leaves the control live and claims nothing.
    const freeUAvailable = capabilities?.nodes?.freeu !== false && modelType !== 'flux';
    const pagAvailable = capabilities?.nodes?.pag !== false && modelType !== 'flux';
    const adetailerAvailable = capabilities?.nodes?.adetailer !== false
        && capabilities?.nodes?.detector !== false;
    const hiresModelAvailable = capabilities?.nodes?.upscale_model !== false;

    const freeUNote = capabilities?.nodes?.freeu === false
        ? capabilityNote(capabilities, 'freeu', 'FreeU')
        : (modelType === 'flux'
            ? 'FreeU is not applied to Flux models - the model does not use U-Net skip connections the way it does.'
            : null);
    const pagNote = capabilities?.nodes?.pag === false
        ? capabilityNote(capabilities, 'pag', 'Perturbed Attention Guidance')
        : (modelType === 'flux'
            ? 'PAG is not applied to Flux models.'
            : null);
    const adetailerNote = capabilities?.nodes?.adetailer === false
        ? capabilityNote(capabilities, 'adetailer', 'ADetailer')
        : (capabilities?.nodes?.detector === false
            ? capabilityNote(capabilities, 'detector', 'detector')
            : null);

    // The provider's OWN list of models for each input, when it has one.
    // The panel used to offer the union catalogue - models from the server
    // and from every provider - so it offered files the target provider did
    // not have, and the job failed on the missing file.
    const providerUpscalerModels = capabilities?.models?.upscale_model || null;
    const providerDetectorModels = capabilities?.models?.detector || null;
    // With no loader node on the provider, a MODEL upscaler cannot run at
    // all - so the dropdown offers only Latent, rather than offering files
    // that would fail at dispatch.
    const upscalerChoices = !hiresModelAvailable
        ? []
        : (providerUpscalerModels
            ? providerUpscalerModels.map((name) => ({ name }))
            : (upscalerModels || []));
    const detectorChoices = providerDetectorModels
        ? providerDetectorModels.map((name) => ({ name }))
        : (adetailerModels || []);

    return (
        <CollapsibleSection
            title="Enhancements"
            icon={<Sparkles size={20} className="text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.6)]" />}
            defaultOpen={hiresFix || adetailer || enableFreeU || enablePAG || enableLatentUpscale}
        >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                {setHiresFix && (
                    <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${hiresFix ? 'border-yellow-500/30 ring-1 ring-yellow-500/20' : 'border-white/5'}`}>
                        <div className="flex items-center gap-3">
                            <div className="relative flex items-center justify-center w-5 h-5">
                                <input
                                    type="checkbox"
                                    checked={hiresFix || false}
                                    onChange={(e) => setHiresFix(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer"
                                    id="hiresFix"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-yellow-500 peer-checked:border-yellow-500 transition-colors flex items-center justify-center shadow-inner">
                                    {hiresFix && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="hiresFix" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">Hi-Res Fix</label>
                        </div>

                        <div className={`space-y-4 transition-all duration-300 ${hiresFix ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Performs a second pass to upscale the image and add finer details. Use Latent for hallucinated details, or a model upscaler for structural preservation.
                            </p>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-yellow-400 uppercase tracking-widest px-1">Upscaler</label>
                                <select
                                    value={hiresUpscaler || 'Latent'}
                                    onChange={(e) => setHiresUpscaler(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                >
                                    <option value="Latent">Latent (Default)</option>
                                    {upscalerChoices.map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-1.5">
                                    <label className="block text-2xs font-bold text-yellow-400 uppercase tracking-widest px-1">Scale</label>
                                    <input
                                        type="number"
                                        step="0.1"
                                        value={hiresUpscale || 1.5}
                                        onChange={(e) => setHiresUpscale(parseFloat(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-2xs font-bold text-yellow-400 uppercase tracking-widest px-1">Denoise</label>
                                    <input
                                        type="number"
                                        step="0.05"
                                        value={hiresDenoise || 0.5}
                                        onChange={(e) => setHiresDenoise(parseFloat(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-yellow-400 uppercase tracking-widest px-1">Steps</label>
                                <input
                                    type="number"
                                    value={hiresSteps || 20}
                                    onChange={(e) => setHiresSteps(parseInt(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                        </div>
                    </div>
                )}

                {setAdetailer && (
                    <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${adetailer ? 'border-orange-500/30 ring-1 ring-orange-500/20' : 'border-white/5'}`}>
                        <div className="flex items-center gap-3">
                            <div className="relative flex items-center justify-center w-5 h-5">
                                <input
                                    type="checkbox"
                                    checked={adetailerAvailable ? (adetailer || false) : false}
                                    disabled={!adetailerAvailable}
                                    onChange={(e) => setAdetailer(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer disabled:cursor-not-allowed"
                                    id="adetailer"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-orange-500 peer-checked:border-orange-500 transition-colors flex items-center justify-center shadow-inner">
                                    {adetailerAvailable && adetailer && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="adetailer" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">ADetailer</label>
                        </div>

                        <div className={`space-y-4 transition-all duration-300 ${adetailer ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Automatically detects faces, hands, or other objects to fix structural issues by performing localized inpainting.
                            </p>
                            <UnsupportedHint>{adetailerNote}</UnsupportedHint>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-orange-400 uppercase tracking-widest px-1">Model</label>
                                <select
                                    value={adetailerModel || ''}
                                    onChange={(e) => setAdetailerModel(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                >
                                    {detectorChoices.map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-orange-400 uppercase tracking-widest px-1">Prompt (Optional)</label>
                                <input
                                    type="text"
                                    value={adetailerPrompt || ''}
                                    onChange={(e) => setAdetailerPrompt(e.target.value)}
                                    placeholder="e.g. detailed face, blue eyes"
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus placeholder-gray-600"
                                />
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-1.5">
                                    <label className="block text-2xs font-bold text-orange-400 uppercase tracking-widest px-1">Steps</label>
                                    <input
                                        type="number"
                                        value={adetailerSteps || 20}
                                        onChange={(e) => setAdetailerSteps(parseInt(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-2xs font-bold text-orange-400 uppercase tracking-widest px-1">Denoise</label>
                                    <input
                                        type="number"
                                        step="0.05"
                                        value={adetailerDenoise || 0.4}
                                        onChange={(e) => setAdetailerDenoise(parseFloat(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                            </div>
                            <div className="flex items-center gap-2 pt-2">
                                <input
                                    type="checkbox"
                                    checked={adetailerInpaintMasked || false}
                                    onChange={(e) => setAdetailerInpaintMasked(e.target.checked)}
                                    className="rounded bg-black/40 border-gray-600 text-orange-500 focus:ring-orange-500 focus:ring-offset-gray-900"
                                    id="inpaintMasked"
                                />
                                <label htmlFor="inpaintMasked" className="text-xs text-gray-400 select-none cursor-pointer font-medium hover:text-gray-300">Inpaint Masked Only</label>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-6">
                <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${enableFreeU ? 'border-blue-500/30 ring-1 ring-blue-500/20' : 'border-white/5'}`}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="relative flex items-center justify-center w-5 h-5">
                                <input
                                    type="checkbox"
                                    checked={freeUAvailable ? enableFreeU : false}
                                    disabled={!freeUAvailable}
                                    onChange={(e) => setEnableFreeU(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer disabled:cursor-not-allowed"
                                    id="enableFreeU"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-blue-500 peer-checked:border-blue-500 transition-colors flex items-center justify-center shadow-inner">
                                    {freeUAvailable && enableFreeU && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="enableFreeU" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">FreeU (v2)</label>
                        </div>
                    </div>
                    <div className={`transition-all duration-300 ${enableFreeU && freeUAvailable ? 'opacity-100 max-h-[500px] mt-4' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden mt-0'}`}>
                        <p className="text-xs text-gray-400 leading-relaxed">
                            Substantially improves image quality by adjusting U-Net skip connections.
                        </p>
                        <UnsupportedHint>{freeUNote}</UnsupportedHint>
                    </div>
                </div>

                <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${enablePAG ? 'border-purple-500/30 ring-1 ring-purple-500/20' : 'border-white/5'}`}>
                    <div className="flex items-center gap-3">
                        <div className="relative flex items-center justify-center w-5 h-5">
                            <input
                                type="checkbox"
                                checked={pagAvailable ? enablePAG : false}
                                disabled={!pagAvailable}
                                onChange={(e) => setEnablePAG(e.target.checked)}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer disabled:cursor-not-allowed"
                                id="enablePAG"
                            />
                            <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-purple-500 peer-checked:border-purple-500 transition-colors flex items-center justify-center shadow-inner">
                                {pagAvailable && enablePAG && <Sparkles size={12} className="text-white drop-shadow-md" />}
                            </div>
                        </div>
                        <label htmlFor="enablePAG" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">PAG (Perturbed Attention Guidance)</label>
                    </div>

                    <div className={`space-y-4 transition-all duration-300 ${enablePAG ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                        <p className="text-xs text-gray-400 leading-relaxed">
                            Enhances structural coherence and overall image quality without requiring additional training or prompt changes.
                        </p>
                        <UnsupportedHint>{pagNote}</UnsupportedHint>
                        <div className="space-y-1.5">
                            <label className="block text-2xs font-bold text-purple-400 uppercase tracking-widest px-1">PAG Scale</label>
                            <input
                                type="number"
                                step="0.1"
                                value={pagScale}
                                onChange={(e) => setPagScale(parseFloat(e.target.value))}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500/50 outline-none transition-all glow-focus"
                            />
                        </div>
                    </div>
                </div>
            </div>

            {setEnableLatentUpscale && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-6 border-t border-white/5">
                    <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${enableLatentUpscale ? 'border-pink-500/30 ring-1 ring-pink-500/20' : 'border-white/5'}`}>
                        <div className="flex items-center gap-3">
                            <div className="relative flex items-center justify-center w-5 h-5">
                                <input
                                    type="checkbox"
                                    checked={enableLatentUpscale || false}
                                    onChange={(e) => setEnableLatentUpscale(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer"
                                    id="enableLatentUpscale"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-pink-500 peer-checked:border-pink-500 transition-colors flex items-center justify-center shadow-inner">
                                    {enableLatentUpscale && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="enableLatentUpscale" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">Latent Upscale</label>
                        </div>

                        <div className={`space-y-4 transition-all duration-300 ${enableLatentUpscale ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                            <div className="space-y-1.5">
                                <label className="block text-2xs font-bold text-pink-400 uppercase tracking-widest px-1">Scale Multiplier</label>
                                <input
                                    type="number"
                                    step="0.1"
                                    value={latentUpscaleMultiplier || 1.5}
                                    onChange={(e) => setLatentUpscaleMultiplier(parseFloat(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-pink-500/50 focus:border-pink-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                            <p className="text-xs text-gray-400 leading-relaxed px-1">
                                Upscales the image directly in the latent space before sampling. This creates hallucinated details but changes the composition.
                            </p>
                        </div>
                    </div>
                </div>
            )}
        </CollapsibleSection>
    );
});

export default EnhancementsSection;
