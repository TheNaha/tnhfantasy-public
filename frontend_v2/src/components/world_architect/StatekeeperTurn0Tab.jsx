import clsx from 'clsx';
import {
    Shield, Clock, Lock, Unlock, Sparkles, Wand2, Compass, AlertCircle,
    User, Plus, Trash2, Tag, Shirt, Heart
} from 'lucide-react';

export default function StatekeeperTurn0Tab({
    snapshot = {},
    lockedFields = [],
    onChangeSnapshot,
    onToggleLock,
    onSynthesizeTurn0,
    isSynthesizing = false,
}) {
    const isLocked = (field) => lockedFields.includes(field);

    const handleFieldChange = (field, value) => {
        onChangeSnapshot({
            ...snapshot,
            [field]: value,
        });
    };

    const handleClockChange = (subfield, value) => {
        const wc = { ...(snapshot.world_clock || {}) };
        wc[subfield] = value;
        onChangeSnapshot({
            ...snapshot,
            world_clock: wc,
        });
    };

    const handleAddSkill = (field) => {
        const current = snapshot[field] || [];
        const name = prompt(`Enter skill name to add:`);
        if (name && name.trim()) {
            onChangeSnapshot({
                ...snapshot,
                [field]: [...current, name.trim()],
            });
        }
    };

    const handleRemoveSkill = (field, idx) => {
        const current = [...(snapshot[field] || [])];
        current.splice(idx, 1);
        onChangeSnapshot({
            ...snapshot,
            [field]: current,
        });
    };

    const handleAddInventory = () => {
        const current = snapshot.inventory || [];
        const item = prompt(`Enter item name:`);
        if (item && item.trim()) {
            onChangeSnapshot({
                ...snapshot,
                inventory: [...current, item.trim()],
            });
        }
    };

    const handleRemoveInventory = (idx) => {
        const current = [...(snapshot.inventory || [])];
        current.splice(idx, 1);
        onChangeSnapshot({
            ...snapshot,
            inventory: current,
        });
    };

    const lockedCount = lockedFields.length;

    return (
        <div className="space-y-4">
            {/* Header Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-2xl bg-gray-900/60 border border-white/10">
                <div>
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                        <Shield size={16} className="text-amber-400" />
                        Director &amp; Statekeeper Turn-0 Seeding
                    </h3>
                    <p className="text-xs text-gray-400 mt-0.5">
                        Configure initial state values for chat opening. Lock fields with 🔒 so LLM regenerations and Laya updaters never overwrite them.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    {lockedCount > 0 && (
                        <span className="px-2.5 py-1 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-semibold flex items-center gap-1.5">
                            <Lock size={12} /> {lockedCount} locked
                        </span>
                    )}

                    <button
                        type="button"
                        onClick={onSynthesizeTurn0}
                        disabled={isSynthesizing}
                        className="px-3 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-50"
                        title="Synthesize Turn-0 state values using LLM while preserving locked fields"
                    >
                        <Sparkles size={13} className={isSynthesizing ? 'animate-spin text-amber-400' : 'text-amber-300'} />
                        <span>{isSynthesizing ? 'Synthesizing...' : '✨ Generate Turn-0 State'}</span>
                    </button>
                </div>
            </div>

            {/* Core Director Parameters */}
            <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-4 bg-gray-950/40 text-xs">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Scene Tension */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('scene_tension') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                                Scene Tension
                                <span className="px-1.5 py-0.2 rounded text-2xs font-mono font-bold bg-amber-500/20 text-amber-300">
                                    {(Number(snapshot.scene_tension) || 2.0).toFixed(1)} / 5.0
                                </span>
                            </label>
                            <LockToggleBtn
                                field="scene_tension"
                                isLocked={isLocked('scene_tension')}
                                onToggle={() => onToggleLock('scene_tension')}
                            />
                        </div>
                        <input
                            type="range"
                            min="1.0"
                            max="5.0"
                            step="0.1"
                            value={Number(snapshot.scene_tension) || 2.0}
                            onChange={(e) => handleFieldChange('scene_tension', parseFloat(e.target.value))}
                            className="w-full accent-amber-500 cursor-pointer"
                        />
                        <div className="flex justify-between text-3xs text-gray-500 font-mono">
                            <span>1.0 Serene / Intimate</span>
                            <span>3.0 Dynamic</span>
                            <span>5.0 Life-or-Death</span>
                        </div>
                    </div>

                    {/* Emotional Tone / Mood */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('character_mood') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                                Initial Character Mood
                            </label>
                            <LockToggleBtn
                                field="character_mood"
                                isLocked={isLocked('character_mood')}
                                onToggle={() => onToggleLock('character_mood')}
                            />
                        </div>
                        <input
                            type="text"
                            value={snapshot.character_mood || ''}
                            onChange={(e) => handleFieldChange('character_mood', e.target.value)}
                            placeholder="e.g. Attentive and in-character"
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-amber-500/50"
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Current Activity */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('current_activity') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200">
                                Current Activity (Turn 0)
                            </label>
                            <LockToggleBtn
                                field="current_activity"
                                isLocked={isLocked('current_activity')}
                                onToggle={() => onToggleLock('current_activity')}
                            />
                        </div>
                        <input
                            type="text"
                            value={snapshot.current_activity || ''}
                            onChange={(e) => handleFieldChange('current_activity', e.target.value)}
                            placeholder="e.g. Inspecting weapons at the anvil"
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-amber-500/50"
                        />
                    </div>

                    {/* Character Outfit */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('character_outfit') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                                <Shirt size={13} className="text-blue-400" /> Current Outfit
                            </label>
                            <LockToggleBtn
                                field="character_outfit"
                                isLocked={isLocked('character_outfit')}
                                onToggle={() => onToggleLock('character_outfit')}
                            />
                        </div>
                        <input
                            type="text"
                            value={snapshot.character_outfit || ''}
                            onChange={(e) => handleFieldChange('character_outfit', e.target.value)}
                            placeholder="e.g. Ornate plate armor with crimson cape"
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-amber-500/50"
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Relationship Status */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('relationship_status') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                                <Heart size={13} className="text-pink-400" /> Stance Toward {`{{user}}`}
                            </label>
                            <LockToggleBtn
                                field="relationship_status"
                                isLocked={isLocked('relationship_status')}
                                onToggle={() => onToggleLock('relationship_status')}
                            />
                        </div>
                        <input
                            type="text"
                            value={snapshot.relationship_status || ''}
                            onChange={(e) => handleFieldChange('relationship_status', e.target.value)}
                            placeholder="e.g. New acquaintance, cautious ally"
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-amber-500/50"
                        />
                    </div>

                    {/* Fate Check Toggle & Difficulty */}
                    <div className={clsx(
                        "p-3 rounded-xl border transition-all space-y-2",
                        isLocked('fate_check_enabled') ? "bg-amber-950/15 border-amber-500/30" : "bg-gray-900/50 border-white/5"
                    )}>
                        <div className="flex items-center justify-between">
                            <label className="text-xs font-bold text-gray-200 flex items-center gap-2">
                                <input
                                    type="checkbox"
                                    checked={!!snapshot.fate_check_enabled}
                                    onChange={(e) => handleFieldChange('fate_check_enabled', e.target.checked)}
                                    className="accent-amber-500 rounded cursor-pointer"
                                />
                                <span>Enable Interactive Fate Checks</span>
                            </label>
                            <LockToggleBtn
                                field="fate_check_enabled"
                                isLocked={isLocked('fate_check_enabled')}
                                onToggle={() => onToggleLock('fate_check_enabled')}
                            />
                        </div>
                        <div className="grid grid-cols-2 gap-2 pt-1">
                            <select
                                value={snapshot.fate_difficulty || 'auto'}
                                onChange={(e) => handleFieldChange('fate_difficulty', e.target.value)}
                                className="bg-gray-900 border border-white/10 rounded-lg px-2 py-1 text-2xs text-gray-200"
                            >
                                <option value="auto">Difficulty: Auto</option>
                                <option value="easy">Easy (DC 8)</option>
                                <option value="medium">Medium (DC 12)</option>
                                <option value="hard">Hard (DC 15)</option>
                                <option value="extreme">Extreme (DC 18)</option>
                            </select>
                            <select
                                value={snapshot.fate_outcome_override || 'auto'}
                                onChange={(e) => handleFieldChange('fate_outcome_override', e.target.value)}
                                className="bg-gray-900 border border-white/10 rounded-lg px-2 py-1 text-2xs text-gray-200"
                            >
                                <option value="auto">Outcome: Auto Roll</option>
                                <option value="critical_success">Pin: Critical Success</option>
                                <option value="success">Pin: Success</option>
                                <option value="failure">Pin: Failure</option>
                                <option value="critical_failure">Pin: Critical Failure</option>
                            </select>
                        </div>
                    </div>
                </div>

                {/* World Clock Starting Values */}
                <div className="p-3 rounded-xl bg-gray-900/50 border border-white/5 space-y-2">
                    <label className="text-xs font-bold text-gray-200 flex items-center gap-1.5">
                        <Clock size={13} className="text-emerald-400" /> World Clock Turn 0
                    </label>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                        <input
                            type="text"
                            value={snapshot.world_clock?.location || ''}
                            onChange={(e) => handleClockChange('location', e.target.value)}
                            placeholder="Starting Location"
                            className="bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-2xs text-gray-200"
                        />
                        <input
                            type="text"
                            value={snapshot.world_clock?.time_of_day || ''}
                            onChange={(e) => handleClockChange('time_of_day', e.target.value)}
                            placeholder="Starting Time of Day"
                            className="bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-2xs text-gray-200"
                        />
                        <input
                            type="number"
                            value={snapshot.world_clock?.day || 1}
                            onChange={(e) => handleClockChange('day', parseInt(e.target.value, 10) || 1)}
                            placeholder="Starting Day"
                            className="bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-2xs text-gray-200"
                        />
                    </div>
                </div>

                {/* Skills & Inventory Chips */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                    {/* Character Skills */}
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                Character Skills
                            </label>
                            <button
                                type="button"
                                onClick={() => handleAddSkill('character_skills')}
                                className="text-3xs text-emerald-400 hover:text-emerald-300 font-semibold"
                            >
                                + Add
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            {(snapshot.character_skills || []).map((sk, idx) => (
                                <span key={idx} className="px-2 py-0.5 rounded-lg text-2xs bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 flex items-center gap-1">
                                    {sk}
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveSkill('character_skills', idx)}
                                        className="hover:text-red-300 ml-0.5"
                                    >
                                        ×
                                    </button>
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* User Skills */}
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                {`{{user}} Skills`}
                            </label>
                            <button
                                type="button"
                                onClick={() => handleAddSkill('user_skills')}
                                className="text-3xs text-blue-400 hover:text-blue-300 font-semibold"
                            >
                                + Add
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            {(snapshot.user_skills || []).map((sk, idx) => (
                                <span key={idx} className="px-2 py-0.5 rounded-lg text-2xs bg-blue-500/15 border border-blue-500/30 text-blue-300 flex items-center gap-1">
                                    {sk}
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveSkill('user_skills', idx)}
                                        className="hover:text-red-300 ml-0.5"
                                    >
                                        ×
                                    </button>
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Inventory Items */}
                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                Starting Inventory
                            </label>
                            <button
                                type="button"
                                onClick={handleAddInventory}
                                className="text-3xs text-amber-400 hover:text-amber-300 font-semibold"
                            >
                                + Add
                            </button>
                        </div>
                        <div className="flex flex-wrap gap-1">
                            {(snapshot.inventory || []).map((item, idx) => (
                                <span key={idx} className="px-2 py-0.5 rounded-lg text-2xs bg-amber-500/15 border border-amber-500/30 text-amber-300 flex items-center gap-1">
                                    {item}
                                    <button
                                        type="button"
                                        onClick={() => handleRemoveInventory(idx)}
                                        className="hover:text-red-300 ml-0.5"
                                    >
                                        ×
                                    </button>
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

function LockToggleBtn({ _field, isLocked, onToggle }) {
    return (
        <button
            type="button"
            onClick={onToggle}
            className={clsx(
                "px-2 py-0.5 rounded-lg text-3xs font-semibold flex items-center gap-1 transition-all",
                isLocked
                    ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm"
                    : "bg-gray-800 text-gray-400 hover:text-gray-200 border border-white/5"
            )}
            title={isLocked ? "Field is locked from LLM/Laya overwrites" : "Click to lock this field"}
        >
            {isLocked ? <Lock size={10} /> : <Unlock size={10} />}
            <span>{isLocked ? "Locked" : "Unlocked"}</span>
        </button>
    );
}
