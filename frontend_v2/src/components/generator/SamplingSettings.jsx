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
        <div className="glass-panel p-5 rounded-2xl border border-white/5 shadow-xl space-y-4 mb-4">
            <h3 className="text-base lg:text-lg font-bold flex items-center gap-2 text-white tracking-wide">
                <Settings2 size={20} className="text-gray-400 drop-shadow-md" />
                Sampling
            </h3>

            <div className="grid grid-cols-2 gap-6">
                <NumberInput
                    label="Steps"
                    value={steps}
                    onChange={(val) => setSteps(Math.max(1, val))}
                    min={1}
                    max={150}
                    className="flex-1"
                />
                <NumberInput
                    label="CFG"
                    value={cfg}
                    onChange={(val) => setCfg(Math.max(0, val))}
                    min={0}
                    max={30}
                    step={0.5}
                    className="flex-1"
                />
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-1.5 group">
                    <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Sampler</label>
                    <select
                        value={sampler}
                        onChange={(e) => setSampler(e.target.value)}
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white text-sm focus:ring-2 focus:ring-gray-500/50 outline-none transition-all glow-focus"
                    >
                        {SAMPLERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>

                <div className="space-y-1.5 group">
                    <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Scheduler</label>
                    <select
                        value={scheduler}
                        onChange={(e) => setScheduler(e.target.value)}
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white text-sm focus:ring-2 focus:ring-gray-500/50 outline-none transition-all glow-focus"
                    >
                        {SCHEDULERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="pt-2 space-y-1.5">
                <label className="block text-[11px] font-bold text-gray-400 uppercase tracking-widest px-1">Seed</label>
                <div className="flex gap-3">
                    <input
                        type="number"
                        value={seed}
                        onChange={(e) => setSeed(parseInt(e.target.value))}
                        className="flex-1 min-w-0 bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white font-mono focus:ring-2 focus:ring-gray-500/50 outline-none transition-all glow-focus shadow-inner"
                    />
                    <button
                        onClick={() => {
                            randomizeSeed();
                            if (!autoRandomizeSeed) {
                                updateSetting('generator', 'autoRandomizeSeed', true);
                                toast.success('Auto-randomize enabled!', { icon: '🎲' });
                            }
                        }}
                        className="no-touch-padding w-12 flex items-center justify-center bg-black/40 hover:bg-black/60 border border-white/10 hover:border-white/20 rounded-xl transition-all shadow-lg hover:-translate-y-0.5 text-lg"
                        title="Randomize seed"
                    >
                        🎲
                    </button>
                    <button
                        onClick={() => updateSetting('generator', 'autoRandomizeSeed', !autoRandomizeSeed)}
                        className={`no-touch-padding w-12 flex items-center justify-center border rounded-xl transition-all shadow-lg hover:-translate-y-0.5 ${
                            autoRandomizeSeed
                                ? 'bg-blue-500/20 text-blue-400 border-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.3)]'
                                : 'bg-black/40 text-gray-500 hover:text-white border-white/10 hover:bg-black/60 hover:border-white/20'
                        }`}
                        title={autoRandomizeSeed ? 'Auto-randomize ON' : 'Auto-randomize OFF'}
                    >
                        <RefreshCw size={18} className={autoRandomizeSeed ? 'animate-spin-slow' : ''} />
                    </button>
                </div>
            </div>
        </div>
    );
});

export default SamplingSettings;
