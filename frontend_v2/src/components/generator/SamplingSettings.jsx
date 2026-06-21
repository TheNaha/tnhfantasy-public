import { memo } from 'react';
import { RefreshCw, Settings2 } from 'lucide-react';
import NumberInput from '../common/NumberInput';
import useSettingsStore from '../../store/settingsStore';
import { useGeneratorStore } from '../../store/generatorStore';
import toast from 'react-hot-toast';
import { SAMPLERS, SCHEDULERS } from '../../constants/generation';

const SamplingSettings = memo(function SamplingSettings() {
    const steps = useGeneratorStore(state => state.steps);
    const setSteps = useGeneratorStore(state => state.setSteps);
    const cfg = useGeneratorStore(state => state.cfg);
    const setCfg = useGeneratorStore(state => state.setCfg);
    const sampler = useGeneratorStore(state => state.sampler);
    const setSampler = useGeneratorStore(state => state.setSampler);
    const scheduler = useGeneratorStore(state => state.scheduler);
    const setScheduler = useGeneratorStore(state => state.setScheduler);
    const seed = useGeneratorStore(state => state.seed);
    const setSeed = useGeneratorStore(state => state.setSeed);
    const randomizeSeed = useGeneratorStore(state => state.randomizeSeed);

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const updateSetting = useSettingsStore(state => state.updateSetting);

    return (
        <div className="space-y-3 pb-4 border-b border-gray-800">
            <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                <Settings2 size={18} className="text-gray-400" />
                Sampling
            </h3>

            <div className="grid grid-cols-2 gap-4">
                <NumberInput
                    label="Steps"
                    value={steps}
                    onChange={(val) => setSteps(Math.max(1, val))}
                    min={1}
                    max={150}
                />
                <NumberInput
                    label="CFG"
                    value={cfg}
                    onChange={(val) => setCfg(Math.max(0, val))}
                    min={0}
                    max={30}
                    step={0.5}
                />
            </div>

            <div className="grid grid-cols-2 gap-2 mt-2">
                <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Sampler</label>
                    <select
                        value={sampler}
                        onChange={(e) => setSampler(e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                    >
                        {SAMPLERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>

                <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Scheduler</label>
                    <select
                        value={scheduler}
                        onChange={(e) => setScheduler(e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm"
                    >
                        {SCHEDULERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="mt-2">
                <label className="block text-xs font-medium text-gray-500 mb-1">Seed</label>
                <div className="flex gap-2">
                    <input
                        type="number"
                        value={seed}
                        onChange={(e) => setSeed(parseInt(e.target.value))}
                        className="flex-1 min-w-0 bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-sm text-white font-mono"
                    />
                    <button
                        onClick={() => {
                            randomizeSeed();
                            if (!autoRandomizeSeed) {
                                updateSetting('generator', 'autoRandomizeSeed', true);
                                toast.success('Auto-randomize enabled!', { icon: '🎲' });
                            }
                        }}
                        className="no-touch-padding w-10 flex items-center justify-center bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg transition-colors flex-shrink-0 text-base"
                        title="Randomize seed"
                    >
                        🎲
                    </button>
                    <button
                        onClick={() => updateSetting('generator', 'autoRandomizeSeed', !autoRandomizeSeed)}
                        className={`no-touch-padding w-10 flex items-center justify-center border rounded-lg transition-colors flex-shrink-0 ${
                            autoRandomizeSeed
                                ? 'bg-blue-600 text-white border-blue-500'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 border-gray-700'
                        }`}
                        title={autoRandomizeSeed ? 'Auto-randomize ON' : 'Auto-randomize OFF'}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </div>
        </div>
    );
});

export default SamplingSettings;
