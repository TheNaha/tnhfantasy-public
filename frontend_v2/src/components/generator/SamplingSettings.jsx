import { memo } from 'react';
import { RefreshCw, Settings2, Lock, Unlock } from 'lucide-react';
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
    const clipSkip = useGeneratorStore(state => state.clipSkip);
    const setClipSkip = useGeneratorStore(state => state.setClipSkip);
    const seed = useGeneratorStore(state => state.seed);
    const setSeed = useGeneratorStore(state => state.setSeed);
    const randomizeSeed = useGeneratorStore(state => state.randomizeSeed);

    const lockedParams = useGeneratorStore(state => state.lockedParams);
    const toggleParamLock = useGeneratorStore(state => state.toggleParamLock);

    const autoRandomizeSeed = useSettingsStore(state => state.settings.generator.autoRandomizeSeed);
    const updateSetting = useSettingsStore(state => state.updateSetting);

    const renderLockIcon = (param) => (
        <button
            onClick={() => toggleParamLock(param)}
            className={`ml-2 no-touch-padding shrink-0 h-10 w-10 p-1 rounded-md border transition-all flex items-center justify-center ${lockedParams[param] ? 'bg-red-500/20 text-red-400 border-red-500/50' : 'bg-transparent text-gray-600 hover:text-gray-400 border-transparent hover:bg-white/5'}`}
            title={lockedParams[param] ? "Unlock parameter" : "Lock parameter (prevent auto-change)"}
            aria-label={lockedParams[param] ? "Unlock parameter" : "Lock parameter"}
        >
            {lockedParams[param] ? <Lock size={10} /> : <Unlock size={10} />}
        </button>
    );

    return (
        <div className="glass-panel p-5 rounded-2xl border border-white/5 shadow-xl space-y-4 mb-4">
            <h3 className="text-base lg:text-lg font-bold flex items-center gap-2 text-white tracking-wide">
                <Settings2 size={20} className="text-gray-400 drop-shadow-md" />
                Sampling
            </h3>

            <div className="grid grid-cols-2 gap-6">
                <NumberInput
                    label={<>Steps{renderLockIcon('steps')}</>}
                    value={steps}
                    onChange={(val) => { if (!lockedParams.steps) setSteps(Math.max(1, val)); }}
                    disabled={lockedParams.steps}
                    min={1}
                    max={150}
                    className="flex-1"
                />
                <NumberInput
                    label={<>CFG{renderLockIcon('cfg')}</>}
                    value={cfg}
                    onChange={(val) => { if (!lockedParams.cfg) setCfg(Math.max(0, val)); }}
                    disabled={lockedParams.cfg}
                    min={0}
                    max={30}
                    step={0.5}
                    className="flex-1"
                />
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2 border-t border-white/5 mt-4 pt-4">
                <NumberInput
                    label={<>Clip Skip{renderLockIcon('clipSkip')}</>}
                    value={clipSkip || 1}
                    onChange={(val) => { if (!lockedParams.clipSkip) setClipSkip(Math.max(1, Math.min(4, val))); }}
                    disabled={lockedParams.clipSkip}
                    min={1}
                    max={4}
                    step={1}
                    className="flex-1"
                />
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-1.5 group">
                    <div className="flex items-center">
                        <label className="block text-2xs font-bold text-gray-400 uppercase tracking-widest px-1">Sampler</label>
                        {renderLockIcon('sampler')}
                    </div>
                    <select
                        value={sampler}
                        disabled={lockedParams.sampler}
                        onChange={(e) => { if (!lockedParams.sampler) setSampler(e.target.value); }}
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white text-sm focus:ring-2 focus:ring-gray-500/50 outline-none transition-all glow-focus disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {SAMPLERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>
                <div className="space-y-1.5 group">
                    <div className="flex items-center">
                        <label className="block text-2xs font-bold text-gray-400 uppercase tracking-widest px-1">Scheduler</label>
                        {renderLockIcon('scheduler')}
                    </div>
                    <select
                        value={scheduler}
                        disabled={lockedParams.scheduler}
                        onChange={(e) => { if (!lockedParams.scheduler) setScheduler(e.target.value); }}
                        className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white text-sm focus:ring-2 focus:ring-gray-500/50 outline-none transition-all glow-focus disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {SCHEDULERS.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="pt-2 border-t border-white/5 space-y-3">
                <div className="flex items-center justify-between">
                    <label className="text-2xs font-bold text-gray-400 uppercase tracking-widest px-1">Seed</label>
                    <label className="flex items-center gap-2 cursor-pointer group">
                        <input
                            type="checkbox"
                            checked={autoRandomizeSeed}
                            onChange={(e) => updateSetting('generator', 'autoRandomizeSeed', e.target.checked)}
                            className="w-3.5 h-3.5 rounded bg-black/40 border-white/20 text-blue-500 focus:ring-blue-500/50 focus:ring-offset-gray-900 transition-all cursor-pointer"
                        />
                        <span className="text-xs text-gray-400 group-hover:text-white transition-colors">Auto-randomize</span>
                    </label>
                </div>

                {/* `min-w-0` on the input: with the two dice now `shrink-0` at
                    48px each, the row's fixed total is 96px plus the gaps, and
                    the input's automatic minimum was its intrinsic size, so the
                    row overflowed a 360px viewport by 8px and the app root
                    clipped the last dice. `min-w-0` lets the input give way
                    instead, which is the only element here that can. */}
                <div className="flex gap-2 min-w-0">
                    <input
                        type="number"
                        value={seed}
                        aria-label="Seed"
                        onChange={(e) => setSeed(Number(e.target.value))}
                        className="flex-1 min-w-0 bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white text-sm focus:ring-2 focus:ring-blue-500/50 outline-none font-mono transition-all glow-focus"
                    />
                    <button
                        onClick={() => {
                            randomizeSeed();
                            if (!autoRandomizeSeed) {
                                updateSetting('generator', 'autoRandomizeSeed', true);
                                toast.success('Auto-randomize enabled!', { icon: '🎲' });
                            }
                        }}
                        className="no-touch-padding w-12 shrink-0 flex items-center justify-center bg-black/40 hover:bg-black/60 border border-white/10 hover:border-white/20 rounded-xl transition-all shadow-lg hover:-translate-y-0.5 text-lg"
                        title="Randomize seed"
                    >
                        🎲
                    </button>
                    <button
                        onClick={() => updateSetting('generator', 'autoRandomizeSeed', !autoRandomizeSeed)}
                        className={`no-touch-padding w-12 shrink-0 flex items-center justify-center border rounded-xl transition-all shadow-lg hover:-translate-y-0.5 ${
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
