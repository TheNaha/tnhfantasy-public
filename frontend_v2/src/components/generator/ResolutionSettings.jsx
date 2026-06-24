import { memo } from 'react';
import { Lock, Unlock } from 'lucide-react';
import NumberInput from '../common/NumberInput';
import PresetManager from './PresetManager';
import { useGeneratorStore } from '../../store/generatorStore';

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

const ResolutionSettings = memo(function ResolutionSettings() {
    const width = useGeneratorStore(state => state.width);
    const height = useGeneratorStore(state => state.height);
    const setWidth = useGeneratorStore(state => state.setWidth);
    const setHeight = useGeneratorStore(state => state.setHeight);
    const batchSize = useGeneratorStore(state => state.batchSize);
    const setBatchSize = useGeneratorStore(state => state.setBatchSize);
    const aspectRatioLocked = useGeneratorStore(state => state.aspectRatioLocked);
    const setAspectRatioLocked = useGeneratorStore(state => state.setAspectRatioLocked);

    const lockedParams = useGeneratorStore(state => state.lockedParams);
    const toggleParamLock = useGeneratorStore(state => state.toggleParamLock);

    const setResolution = (w, h) => {
        if (!lockedParams.width) setWidth(w);
        if (!lockedParams.height) setHeight(h);
    };

    const handleDimensionChange = (type, value) => {
        const newVal = parseInt(value);
        if (isNaN(newVal)) return;

        if (aspectRatioLocked) {
            const ratio = width / height;
            if (type === 'width' && !lockedParams.width) {
                setWidth(newVal);
                if (!lockedParams.height) setHeight(Math.round(newVal / ratio));
            } else if (type === 'height' && !lockedParams.height) {
                setHeight(newVal);
                if (!lockedParams.width) setWidth(Math.round(newVal * ratio));
            }
        } else {
            if (type === 'width' && !lockedParams.width) setWidth(newVal);
            else if (type === 'height' && !lockedParams.height) setHeight(newVal);
        }
    };

    const renderLockIcon = (param) => (
        <button
            onClick={() => toggleParamLock(param)}
            className={`ml-2 no-touch-padding p-1 rounded-md border transition-all flex items-center justify-center ${lockedParams[param] ? 'bg-red-500/20 text-red-400 border-red-500/50' : 'bg-transparent text-gray-600 hover:text-gray-400 border-transparent hover:bg-white/5'}`}
            title={lockedParams[param] ? "Unlock parameter" : "Lock parameter (prevent auto-change)"}
            aria-label={lockedParams[param] ? "Unlock parameter" : "Lock parameter"}
        >
            {lockedParams[param] ? <Lock size={10} /> : <Unlock size={10} />}
        </button>
    );

    return (
        <div className="glass-panel p-5 rounded-2xl border border-white/5 shadow-xl space-y-4 lg:space-y-4 md:space-y-6 mb-4">
            <div className="flex justify-between items-center">
                <h3 className="text-base lg:text-lg font-bold text-white tracking-wide">Parameters</h3>
                <PresetManager />
            </div>

            <div className="space-y-3 lg:space-y-4">
                <label className="text-[11px] font-bold text-blue-400 uppercase tracking-widest px-1 flex items-center">
                    Resolution
                </label>

                <div className="grid grid-cols-4 gap-2">
                    {RESOLUTION_PRESETS.map((p) => (
                        <button
                            key={p.label}
                            onClick={() => setResolution(p.w, p.h)}
                            disabled={lockedParams.width || lockedParams.height}
                            aria-label={`Set aspect ratio ${p.label}, ${p.w}x${p.h} pixels`}
                            title={`Set aspect ratio ${p.label} (${p.w}x${p.h})`}
                            aria-pressed={width === p.w && height === p.h}
                            className={`flex flex-col items-center justify-center gap-1 p-2 rounded-xl transition-all border focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:outline-none disabled:opacity-50 disabled:cursor-not-allowed ${width === p.w && height === p.h ? 'bg-blue-500/20 border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)] text-blue-400 scale-105' : 'bg-black/40 border-white/10 text-gray-400 hover:bg-black/60 hover:text-white hover:border-white/20 shadow-inner'}`}
                        >
                            <div className="w-5 h-5 flex items-center justify-center">
                                <div
                                    className="border-2 border-current rounded-sm transition-all"
                                    style={{
                                        width: p.w >= p.h ? '16px' : `${(p.w / p.h) * 16}px`,
                                        height: p.h >= p.w ? '16px' : `${(p.h / p.w) * 16}px`
                                    }}
                                />
                            </div>
                            <span className="text-[10px] font-bold">{p.label}</span>
                        </button>
                    ))}
                </div>

                <div className="flex items-end gap-3 pt-2">
                    <div className="flex-1 space-y-1.5">
                        <div className="flex items-center">
                            <label htmlFor="width-input" className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Width</label>
                            {renderLockIcon('width')}
                        </div>
                        <input
                            id="width-input"
                            type="number"
                            value={width}
                            disabled={lockedParams.width}
                            onChange={(e) => handleDimensionChange('width', e.target.value)}
                            className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all glow-focus disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                    </div>
                    <button
                        onClick={() => setAspectRatioLocked(!aspectRatioLocked)}
                        className={`no-touch-padding px-3 py-2 rounded-xl border transition-all duration-300 flex items-center justify-center shadow-lg ${aspectRatioLocked ? 'bg-blue-500/20 text-blue-400 border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]' : 'bg-black/40 text-gray-500 hover:text-white border-white/10 hover:bg-black/60'}`}
                        title={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                        aria-label={aspectRatioLocked ? "Unlock Aspect Ratio" : "Lock Aspect Ratio"}
                        aria-pressed={aspectRatioLocked}
                    >
                        {aspectRatioLocked ? <Lock size={16} /> : <Unlock size={16} />}
                    </button>
                    <div className="flex-1 space-y-1.5">
                        <div className="flex items-center">
                            <label htmlFor="height-input" className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Height</label>
                            {renderLockIcon('height')}
                        </div>
                        <input
                            id="height-input"
                            type="number"
                            value={height}
                            disabled={lockedParams.height}
                            onChange={(e) => handleDimensionChange('height', e.target.value)}
                            className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all glow-focus disabled:opacity-50 disabled:cursor-not-allowed"
                        />
                    </div>
                </div>
            </div>

            <div className="space-y-1.5">
                <div className="flex items-center">
                    <label className="block text-[11px] font-bold text-blue-400 uppercase tracking-widest px-1">Batch Size</label>
                    {renderLockIcon('batchSize')}
                </div>
                <input
                    type="number"
                    value={batchSize}
                    onChange={(e) => {
                        if (!lockedParams.batchSize) setBatchSize(Math.max(1, parseInt(e.target.value) || 1));
                    }}
                    disabled={lockedParams.batchSize}
                    min={1}
                    max={16}
                    className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none transition-all glow-focus disabled:opacity-50 disabled:cursor-not-allowed"
                />
            </div>
        </div>
    );
});

export default ResolutionSettings;
