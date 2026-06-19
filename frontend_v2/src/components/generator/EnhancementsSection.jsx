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
            icon={<Sparkles size={20} className="text-yellow-400" />}
            defaultOpen={hiresFix || adetailer}
        >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <input
                            type="checkbox"
                            checked={hiresFix}
                            onChange={(e) => setHiresFix(e.target.checked)}
                            className="rounded bg-gray-700 border-gray-600 w-4 h-4 text-blue-600 focus:ring-blue-500"
                            id="hiresFix"
                        />
                        <label htmlFor="hiresFix" className="text-sm font-medium text-white cursor-pointer select-none">Hi-Res Fix</label>
                    </div>

                    <div className={`space-y-3 pl-6 border-l-2 border-gray-700 ml-2 transition-all ${hiresFix ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Upscaler</label>
                            <select
                                value={hiresUpscaler}
                                onChange={(e) => setHiresUpscaler(e.target.value)}
                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                            >
                                <option value="Latent">Latent (Default)</option>
                                {upscalerModels.map(m => (
                                    <option key={m.name} value={m.name}>{m.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Scale</label>
                                <input
                                    type="number"
                                    step="0.1"
                                    value={hiresUpscale}
                                    onChange={(e) => setHiresUpscale(parseFloat(e.target.value))}
                                    className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Denoise</label>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={hiresDenoise}
                                    onChange={(e) => setHiresDenoise(parseFloat(e.target.value))}
                                    className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                />
                            </div>
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Steps</label>
                            <input
                                type="number"
                                value={hiresSteps}
                                onChange={(e) => setHiresSteps(parseInt(e.target.value))}
                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                            />
                        </div>
                    </div>
                </div>

                <div className="space-y-4">
                    <div className="flex items-center gap-2">
                        <input
                            type="checkbox"
                            checked={adetailer}
                            onChange={(e) => setAdetailer(e.target.checked)}
                            className="rounded bg-gray-700 border-gray-600 w-4 h-4 text-blue-600 focus:ring-blue-500"
                            id="adetailer"
                        />
                        <label htmlFor="adetailer" className="text-sm font-medium text-white cursor-pointer select-none">ADetailer</label>
                    </div>

                    <div className={`space-y-3 pl-6 border-l-2 border-gray-700 ml-2 transition-all ${adetailer ? 'opacity-100' : 'opacity-50 pointer-events-none'}`}>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Model</label>
                            <select
                                value={adetailerModel}
                                onChange={(e) => setAdetailerModel(e.target.value)}
                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                            >
                                {adetailerModels.map(m => (
                                    <option key={m.name} value={m.name}>{m.name}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs text-gray-500 mb-1">Prompt (Optional)</label>
                            <input
                                type="text"
                                value={adetailerPrompt}
                                onChange={(e) => setAdetailerPrompt(e.target.value)}
                                placeholder="e.g. detailed face, blue eyes"
                                className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                            />
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Steps</label>
                                <input
                                    type="number"
                                    value={adetailerSteps}
                                    onChange={(e) => setAdetailerSteps(parseInt(e.target.value))}
                                    className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Denoise</label>
                                <input
                                    type="number"
                                    step="0.05"
                                    value={adetailerDenoise}
                                    onChange={(e) => setAdetailerDenoise(parseFloat(e.target.value))}
                                    className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                />
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <input
                                type="checkbox"
                                checked={adetailerInpaintMasked}
                                onChange={(e) => setAdetailerInpaintMasked(e.target.checked)}
                                className="rounded bg-gray-700 border-gray-600"
                                id="inpaintMasked"
                            />
                            <label htmlFor="inpaintMasked" className="text-xs text-gray-400 select-none cursor-pointer">Inpaint Masked Only</label>
                        </div>
                    </div>
                </div>
            </div>
        </CollapsibleSection>
    );
});

export default EnhancementsSection;
