import React from 'react';
import { Sparkles, Sliders } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import NumberInput from '../common/NumberInput';

export default function SettingsPanel({ upscalerModels, adetailerModels }) {
    const {
        seed, setSeed,
        steps, setSteps,
        cfg, setCfg,
        sampler, setSampler,
        scheduler, setScheduler,
        width, setWidth,
        height, setHeight,
        batchSize, setBatchSize,
        aspectRatioLocked, setAspectRatioLocked,

        hiresFix, setHiresFix,
        hiresUpscaler, setHiresUpscaler,
        hiresDenoise, setHiresDenoise,
        hiresUpscale, setHiresUpscale,
        hiresSteps, setHiresSteps,

        adetailer, setAdetailer,
        adetailerModel, setAdetailerModel,
        adetailerPrompt, setAdetailerPrompt,
        adetailerNegative, setAdetailerNegative,
        adetailerSteps, setAdetailerSteps,
        adetailerDenoise, setAdetailerDenoise,
        adetailerInpaintMasked, setAdetailerInpaintMasked
    } = useGeneratorStore();

    const handleDimensionChange = (type, value) => {
        const newVal = parseInt(value);
        if (isNaN(newVal)) return;

        if (aspectRatioLocked) {
            const ratio = width / height;
            if (type === 'width') {
                setWidth(newVal);
                setHeight(Math.round(newVal / ratio));
            } else {
                setHeight(newVal);
                setWidth(Math.round(newVal * ratio));
            }
        } else {
            if (type === 'width') setWidth(newVal);
            else setHeight(newVal);
        }
    };

    const setResolution = (w, h) => {
        setWidth(w);
        setHeight(h);
    };

    return (
        <div className="space-y-6">
            {/* Basic Settings */}
            <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 space-y-6 shadow-lg">
                <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                    <Sliders size={20} className="text-blue-400" />
                    Generation Settings
                </h3>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {/* Resolution */}
                    <div className="col-span-1 sm:col-span-2 space-y-2">
                        <div className="flex justify-between items-center">
                            <label className="text-xs font-medium text-gray-500 uppercase">Resolution</label>
                            <div className="flex gap-2">
                                <button onClick={() => setResolution(512, 512)} className="text-xs bg-gray-700 px-2 py-1 rounded hover:bg-gray-600">512x512</button>
                                <button onClick={() => setResolution(768, 768)} className="text-xs bg-gray-700 px-2 py-1 rounded hover:bg-gray-600">768x768</button>
                                <button onClick={() => setResolution(1024, 1024)} className="text-xs bg-gray-700 px-2 py-1 rounded hover:bg-gray-600">1024x1024</button>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="flex-1 relative">
                                <input
                                    type="number"
                                    inputMode="numeric"
                                    value={width}
                                    onChange={(e) => handleDimensionChange('width', e.target.value)}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-center text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                />
                                <span className="absolute right-2 top-2 text-xs text-gray-500">W</span>
                            </div>
                            <span className="text-gray-500">x</span>
                            <div className="flex-1 relative">
                                <input
                                    type="number"
                                    inputMode="numeric"
                                    value={height}
                                    onChange={(e) => handleDimensionChange('height', e.target.value)}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-center text-white focus:ring-1 focus:ring-blue-500 outline-none"
                                />
                                <span className="absolute right-2 top-2 text-xs text-gray-500">H</span>
                            </div>
                            <button
                                onClick={() => setAspectRatioLocked(!aspectRatioLocked)}
                                className={`p-2 rounded-lg border ${aspectRatioLocked ? 'bg-blue-500/20 border-blue-500 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-500'}`}
                                title="Lock Aspect Ratio"
                            >
                                {aspectRatioLocked ? "🔒" : "🔓"}
                            </button>
                        </div>
                    </div>

                    {/* Batch Size */}
                    <NumberInput
                        label="Batch Size"
                        value={batchSize}
                        onChange={setBatchSize}
                        min={1}
                        max={8}
                    />

                    {/* Seed */}
                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1 uppercase">Seed</label>
                        <div className="flex gap-2">
                            <input
                                type="number"
                                inputMode="numeric"
                                pattern="[0-9]*"
                                value={seed}
                                onChange={(e) => setSeed(parseInt(e.target.value))}
                                className="flex-1 bg-gray-900 border border-gray-700 rounded-lg p-2 text-white focus:ring-1 focus:ring-blue-500 outline-none"
                            />
                            <button
                                onClick={() => setSeed(Math.floor(Math.random() * 1000000000))}
                                className="p-2 bg-gray-700 rounded-lg hover:bg-gray-600 text-white"
                                title="Randomize Seed"
                            >
                                🎲
                            </button>
                        </div>
                    </div>

                    {/* Steps */}
                    <NumberInput
                        label="Steps"
                        value={steps}
                        onChange={setSteps}
                        min={1}
                        max={100}
                    />

                    {/* CFG */}
                    <NumberInput
                        label="CFG Scale"
                        value={cfg}
                        onChange={setCfg}
                        min={1}
                        max={30}
                        step={0.5}
                    />

                    {/* Sampler */}
                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1 uppercase">Sampler</label>
                        <select
                            value={sampler}
                            onChange={(e) => setSampler(e.target.value)}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-1 focus:ring-blue-500 outline-none"
                        >
                            {["euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde", "ddim", "uni_pc", "uni_pc_bh2"].map(s => (
                                <option key={s} value={s}>{s}</option>
                            ))}
                        </select>
                    </div>

                    {/* Scheduler */}
                    <div>
                        <label className="block text-xs font-medium text-gray-500 mb-1 uppercase">Scheduler</label>
                        <select
                            value={scheduler}
                            onChange={(e) => setScheduler(e.target.value)}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-1 focus:ring-blue-500 outline-none"
                        >
                            {["normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform"].map(s => (
                                <option key={s} value={s}>{s}</option>
                            ))}
                        </select>
                    </div>
                </div>
            </div>

            {/* Enhancements */}
            <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 space-y-6 shadow-lg">
                <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                    <Sparkles size={20} className="text-yellow-400" />
                    Enhancements
                </h3>

                <div className="grid grid-cols-1 gap-6">
                    {/* Hi-Res Fix */}
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
                                <NumberInput
                                    label="Scale"
                                    value={hiresUpscale}
                                    onChange={setHiresUpscale}
                                    min={1}
                                    max={4}
                                    step={0.1}
                                />
                                <NumberInput
                                    label="Denoise"
                                    value={hiresDenoise}
                                    onChange={setHiresDenoise}
                                    min={0}
                                    max={1}
                                    step={0.05}
                                />
                            </div>
                            <NumberInput
                                label="Steps"
                                value={hiresSteps}
                                onChange={setHiresSteps}
                                min={0}
                                max={50}
                            />
                        </div>
                    </div>

                    {/* ADetailer */}
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
                            <div>
                                <label className="block text-xs text-gray-500 mb-1">Negative (Optional)</label>
                                <input
                                    type="text"
                                    value={adetailerNegative}
                                    onChange={(e) => setAdetailerNegative(e.target.value)}
                                    placeholder="e.g. bad eyes, blur"
                                    className="w-full bg-gray-800 rounded p-2 text-xs text-white border border-gray-600"
                                />
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                                <NumberInput
                                    label="Steps"
                                    value={adetailerSteps}
                                    onChange={setAdetailerSteps}
                                    min={1}
                                    max={100}
                                />
                                <NumberInput
                                    label="Denoise"
                                    value={adetailerDenoise}
                                    onChange={setAdetailerDenoise}
                                    min={0}
                                    max={1}
                                    step={0.05}
                                />
                            </div>
                            <div className="flex items-center gap-2 pt-1">
                                <input
                                    type="checkbox"
                                    checked={adetailerInpaintMasked}
                                    onChange={(e) => setAdetailerInpaintMasked(e.target.checked)}
                                    className="rounded bg-gray-700 border-gray-600 w-3 h-3 text-blue-600"
                                    id="adInpaint"
                                />
                                <label htmlFor="adInpaint" className="text-xs text-gray-400 cursor-pointer">Inpaint Masked Only</label>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
