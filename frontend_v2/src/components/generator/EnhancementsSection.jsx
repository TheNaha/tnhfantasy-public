import { memo } from 'react';
import { Sparkles } from 'lucide-react';
import CollapsibleSection from '../CollapsibleSection';

const EnhancementsSection = memo(function EnhancementsSection({
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
                                Performs a second pass to upscale the image and add finer details. Use Latent for hallucinated details or a Pixel upscaler for structural preservation.
                            </p>
                            <div className="space-y-1.5">
                                <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Upscaler</label>
                                <select
                                    value={hiresUpscaler || 'Latent'}
                                    onChange={(e) => setHiresUpscaler(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                >
                                    <option value="Latent">Latent (Default)</option>
                                    {(upscalerModels || []).map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="space-y-1.5">
                                    <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Scale</label>
                                    <input
                                        type="number"
                                        step="0.1"
                                        value={hiresUpscale || 1.5}
                                        onChange={(e) => setHiresUpscale(parseFloat(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Denoise</label>
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
                                <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Steps</label>
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
                                    checked={adetailer || false}
                                    onChange={(e) => setAdetailer(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer"
                                    id="adetailer"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-orange-500 peer-checked:border-orange-500 transition-colors flex items-center justify-center shadow-inner">
                                    {adetailer && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="adetailer" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">ADetailer</label>
                        </div>

                        <div className={`space-y-4 transition-all duration-300 ${adetailer ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Automatically detects faces, hands, or other objects to fix structural issues by performing localized inpainting.
                            </p>
                            <div className="space-y-1.5">
                                <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Model</label>
                                <select
                                    value={adetailerModel || ''}
                                    onChange={(e) => setAdetailerModel(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                >
                                    {(adetailerModels || []).map(m => (
                                        <option key={m.name} value={m.name}>{m.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Prompt (Optional)</label>
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
                                    <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Steps</label>
                                    <input
                                        type="number"
                                        value={adetailerSteps || 20}
                                        onChange={(e) => setAdetailerSteps(parseInt(e.target.value))}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                    />
                                </div>
                                <div className="space-y-1.5">
                                    <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Denoise</label>
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
                                    checked={enableFreeU}
                                    onChange={(e) => setEnableFreeU(e.target.checked)}
                                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer"
                                    id="enableFreeU"
                                />
                                <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-blue-500 peer-checked:border-blue-500 transition-colors flex items-center justify-center shadow-inner">
                                    {enableFreeU && <Sparkles size={12} className="text-white drop-shadow-md" />}
                                </div>
                            </div>
                            <label htmlFor="enableFreeU" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">FreeU (v2)</label>
                        </div>
                    </div>
                    <div className={`transition-all duration-300 ${enableFreeU ? 'opacity-100 max-h-[500px] mt-4' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden mt-0'}`}>
                        <p className="text-xs text-gray-400 leading-relaxed">
                            Substantially improves image quality by adjusting U-Net skip connections. (Ignored for Flux models)
                        </p>
                    </div>
                </div>

                <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${enablePAG ? 'border-purple-500/30 ring-1 ring-purple-500/20' : 'border-white/5'}`}>
                    <div className="flex items-center gap-3">
                        <div className="relative flex items-center justify-center w-5 h-5">
                            <input
                                type="checkbox"
                                checked={enablePAG}
                                onChange={(e) => setEnablePAG(e.target.checked)}
                                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10 peer"
                                id="enablePAG"
                            />
                            <div className="w-5 h-5 rounded border-2 border-gray-600 bg-black/40 peer-checked:bg-purple-500 peer-checked:border-purple-500 transition-colors flex items-center justify-center shadow-inner">
                                {enablePAG && <Sparkles size={12} className="text-white drop-shadow-md" />}
                            </div>
                        </div>
                        <label htmlFor="enablePAG" className="text-sm font-bold text-white cursor-pointer select-none tracking-wide">PAG (Perturbed Attention Guidance)</label>
                    </div>

                    <div className={`space-y-4 transition-all duration-300 ${enablePAG ? 'opacity-100 max-h-[500px]' : 'opacity-30 pointer-events-none max-h-0 overflow-hidden'}`}>
                        <p className="text-xs text-gray-400 leading-relaxed">
                            Enhances structural coherence and overall image quality without requiring additional training or prompt changes. (Ignored for Flux)
                        </p>
                        <div className="space-y-1.5">
                            <label className="block text-[11px] font-bold text-purple-400 uppercase tracking-widest px-1">PAG Scale</label>
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
                                <label className="block text-[11px] font-bold text-pink-400 uppercase tracking-widest px-1">Scale Multiplier</label>
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
