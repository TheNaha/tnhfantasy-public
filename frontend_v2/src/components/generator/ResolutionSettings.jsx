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
        </div>
    );
});

export default ResolutionSettings;
