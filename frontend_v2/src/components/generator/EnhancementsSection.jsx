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
}) {
    return (
        <CollapsibleSection
            title="Enhancements"
            icon={<Sparkles size={20} className="text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.6)]" />}
            defaultOpen={hiresFix || adetailer}
        >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${hiresFix ? 'border-yellow-500/30 ring-1 ring-yellow-500/20' : 'border-white/5'}`}>
                    <div className="flex items-center gap-3">
                        <div className="relative flex items-center justify-center w-5 h-5">
                            <input
                                type="checkbox"
                                checked={hiresFix}
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
                        <div className="space-y-1.5">
                            <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Upscaler</label>
                            <select
                                value={hiresUpscaler}
                                onChange={(e) => setHiresUpscaler(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                            >
                                <option value="Latent">Latent (Default)</option>
                                {upscalerModels.map(m => (
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
                                    value={hiresUpscale}
                                    onChange={(e) => setHiresUpscale(parseFloat(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Denoise</label>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={hiresDenoise}
                                    onChange={(e) => setHiresDenoise(parseFloat(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <label className="block text-[11px] font-bold text-yellow-400 uppercase tracking-widest px-1">Steps</label>
                            <input
                                type="number"
                                value={hiresSteps}
                                onChange={(e) => setHiresSteps(parseInt(e.target.value))}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-yellow-500/50 focus:border-yellow-500/50 outline-none transition-all glow-focus"
                            />
                        </div>
                    </div>
                </div>

                <div className={`space-y-4 bg-[#0B0E14]/80 p-5 rounded-2xl border transition-colors shadow-inner ${adetailer ? 'border-orange-500/30 ring-1 ring-orange-500/20' : 'border-white/5'}`}>
                    <div className="flex items-center gap-3">
                        <div className="relative flex items-center justify-center w-5 h-5">
                            <input
                                type="checkbox"
                                checked={adetailer}
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
                        <div className="space-y-1.5">
                            <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Model</label>
                            <select
                                value={adetailerModel}
                                onChange={(e) => setAdetailerModel(e.target.value)}
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                            >
                                {adetailerModels.map(m => (
                                    <option key={m.name} value={m.name}>{m.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="space-y-1.5">
                            <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Prompt (Optional)</label>
                            <input
                                type="text"
                                value={adetailerPrompt}
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
                                    value={adetailerSteps}
                                    onChange={(e) => setAdetailerSteps(parseInt(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="block text-[11px] font-bold text-orange-400 uppercase tracking-widest px-1">Denoise</label>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={adetailerDenoise}
                                    onChange={(e) => setAdetailerDenoise(parseFloat(e.target.value))}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-sm text-white focus:ring-2 focus:ring-orange-500/50 focus:border-orange-500/50 outline-none transition-all glow-focus"
                                />
                            </div>
                        </div>
                        <div className="flex items-center gap-2 pt-2">
                            <input
                                type="checkbox"
                                checked={adetailerInpaintMasked}
                                onChange={(e) => setAdetailerInpaintMasked(e.target.checked)}
                                className="rounded bg-black/40 border-gray-600 text-orange-500 focus:ring-orange-500 focus:ring-offset-gray-900"
                                id="inpaintMasked"
                            />
                            <label htmlFor="inpaintMasked" className="text-xs text-gray-400 select-none cursor-pointer font-medium hover:text-gray-300">Inpaint Masked Only</label>
                        </div>
                    </div>
                </div>
            </div>
        </CollapsibleSection>
    );
});

export default EnhancementsSection;
