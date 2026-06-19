import { memo } from 'react';
import { Lock, Unlock, RefreshCw } from 'lucide-react';
import NumberInput from '../common/NumberInput';
import PresetManager from './PresetManager';
import useSettingsStore from '../../store/settingsStore';
import toast from 'react-hot-toast';

const SAMPLER_OPTIONS = [
    "euler", "euler_ancestral", "heun", "heunpp2",
    "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive",
    "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_sde_gpu",
    "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu",
    "dpmpp_3m_sde", "dpmpp_3m_sde_gpu",
    "ddpm", "lcm", "ddim", "uni_pc", "uni_pc_bh2"
];

const SCHEDULER_OPTIONS = [
    "normal", "karras", "exponential", "sgm_uniform", "simple", "ddim_uniform"
];

const RESOLUTION_PRESETS = [
    { w: 1024, h: 1024, label: "1:1" },
    { w: 832, h: 1216, label: "2:3" },
    { w: 1216, h: 832, label: "3:2" },
    { w: 896, h: 1152, label: "3:4" },
    { w: 1152, h: 896, label: "4:3" },
    { w: 1344, h: 768, label: "16:9" },
    { w: 768, h: 1344, label: "9:16" },
    { w: 1536, h: 640, label: "21:9" },
];

const ParametersPanel = memo(function ParametersPanel({
    width,
    height,
    setWidth,
    setHeight,
    batchSize,
    setBatchSize,
    steps,
    setSteps,
    cfg,
    setCfg,
    seed,
    setSeed,
    sampler,
    setSampler,
    scheduler,
    setScheduler,
    aspectRatioLocked,
    setAspectRatioLocked,
    autoRandomizeSeed,
}) {
    const updateSetting = useSettingsStore(state => state.updateSetting);

    const setResolution = (w, h) => {
        setWidth(w);
        setHeight(h);
    };

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

    return (
        <div className="space-y-4 lg:space-y-6 pb-4 border-b border-gray-800 lg:border-0">
            <div className="flex justify-between items-center">
                <h3 className="text-base lg:text-lg font-semibold">Parameters</h3>
                <PresetManager />
            </div>

            <div className="space-y-3 lg:space-y-4">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wider">Resolution</label>

                <div className="grid grid-cols-4 gap-1.5">
                    {RESOLUTION_PRESETS.map((p) => (
                        <button
                            key={p.label}
                            onClick={() => setResolution(p.w, p.h)}
                            aria-label={`Set aspect ratio ${p.label}, ${p.w}x${p.h} pixels`}
                            title={`Set aspect ratio ${p.label} (${p.w}x${p.h})`}
                            aria-pressed={width === p.w && height === p.h}
                            className={`flex flex-col items-center justify-center gap-0.5 p-1.5 rounded-lg transition-all border focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none ${width === p.w && height === p.h ? 'bg-blue-600/20 border-blue-500 text-blue-400' : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700 hover:text-gray-300'}`}
                        >
                            <div className="w-5 h-5 flex items-center justify-center">
                                <div
                                    className="border-2 border-current rounded-sm transition-all"
                                    style={{
                                        width: p.w >= p.h ? '14px' : `${(p.w / p.h) * 14}px`,
                                        height: p.h >= p.w ? '14px' : `${(p.h / p.w) * 14}px`
                                    }}
                                />
                            </div>
                            <span className="text-[10px] font-bold">{p.label}</span>
                        </button>
                    ))}
                </div>

                <div className="flex items-end gap-2">
                    <div className="flex-1">
                        <label htmlFor="width-input" className="block text-xs font-medium text-gray-500 mb-1">Width</label>
                        <input
                            id="width-input"
                            type="number"
                            value={width}
                            onChange={(e) => handleDimensionChange('width', e.target.value)}
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>
                    <button
                        onClick={() => setAspectRatioLocked(!aspectRatioLocked)}
                        className={`no-touch-padding px-2.5 py-1.5 rounded-lg border transition-colors flex items-center justify-center ${aspectRatioLocked ? 'bg-blue-600 text-white border-blue-500' : 'bg-gray-800 text-gray-400 hover:text-white border-gray-700'}`}
                        title={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                        aria-label={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                        aria-pressed={aspectRatioLocked}
                    >
                        {aspectRatioLocked ? <Lock size={16} /> : <Unlock size={16} />}
                    </button>
                    <div className="flex-1">
                        <label htmlFor="height-input" className="block text-xs font-medium text-gray-500 mb-1">Height</label>
                        <input
                            id="height-input"
                            type="number"
                            value={height}
                            onChange={(e) => handleDimensionChange('height', e.target.value)}
                            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-white text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>
                </div>
            </div>

            <NumberInput
                label="Batch Size"
                value={batchSize}
                onChange={(val) => setBatchSize(Math.max(1, val))}
                min={1}
                max={16}
            />

            <div className="grid grid-cols-2 gap-2">
                <NumberInput
                    label="Steps"
                    value={steps}
                    onChange={(val) => setSteps(Math.max(1, val))}
                    min={1}
                    max={100}
                />
                <NumberInput
                    label="CFG"
                    value={cfg}
                    onChange={(val) => setCfg(Math.max(0, val))}
                    min={1}
                    max={30}
                    step={0.5}
                />
            </div>

            <div className="space-y-1">
                <label className="text-xs font-medium text-gray-500">Seed</label>
                <div className="flex gap-1.5 items-stretch">
                    <input
                        type="number"
                        value={seed}
                        onChange={(e) => setSeed(parseInt(e.target.value))}
                        className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white font-mono"
                    />
                    <button
                        onClick={() => {
                            setSeed(Math.floor(Math.random() * Number.MAX_SAFE_INTEGER));
                            if (!autoRandomizeSeed) {
                                updateSetting('generator', 'autoRandomizeSeed', true);
                                toast.success('Auto-randomize enabled!', { icon: '🎲' });
                            }
                        }}
                        className="no-touch-padding w-10 flex items-center justify-center bg-gray-700 hover:bg-gray-600 border border-gray-600 rounded transition-colors flex-shrink-0 text-base"
                        title="Randomize seed"
                    >
                        🎲
                    </button>
                    <button
                        onClick={() => updateSetting('generator', 'autoRandomizeSeed', !autoRandomizeSeed)}
                        className={`no-touch-padding w-10 flex items-center justify-center border rounded transition-colors flex-shrink-0 ${
                            autoRandomizeSeed
                                ? 'bg-blue-600 text-white border-blue-500'
                                : 'bg-gray-700 text-gray-400 hover:bg-gray-600 border-gray-600'
                        }`}
                        title={autoRandomizeSeed ? 'Auto-randomize ON' : 'Auto-randomize OFF'}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
                <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Sampler</label>
                    <select
                        value={sampler}
                        onChange={(e) => setSampler(e.target.value)}
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                    >
                        {SAMPLER_OPTIONS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Scheduler</label>
                    <select
                        value={scheduler}
                        onChange={(e) => setScheduler(e.target.value)}
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white"
                    >
                        {SCHEDULER_OPTIONS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>
            </div>
        </div>
    );
});

export default ParametersPanel;
