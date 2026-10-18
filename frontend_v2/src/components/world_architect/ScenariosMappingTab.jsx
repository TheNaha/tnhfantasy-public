import { useState } from 'react';
import clsx from 'clsx';
import {
    Sparkles, MapPin, Clock, MessageSquare, Check, Plus, Trash2,
    Wand2, ChevronDown, ChevronRight, Layers, Eye
} from 'lucide-react';

export default function ScenariosMappingTab({
    scenarios = [],
    onChangeScenarios,
    onRefineWithLLM,
    onEnrichGreeting,
    isRefining = false,
    enrichingScenarioId = null,
}) {
    const [expandedIds, setExpandedIds] = useState({ scenario_0: true });

    const toggleExpand = (id) => {
        setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
    };

    const handleUpdateScenario = (id, field, value) => {
        const next = scenarios.map((sc) => {
            if (sc.id === id) {
                return { ...sc, [field]: value };
            }
            return sc;
        });
        onChangeScenarios(next);
    };

    const handleSetPrimary = (id) => {
        const next = scenarios.map((sc) => ({
            ...sc,
            is_primary: sc.id === id,
        }));
        onChangeScenarios(next);
    };

    const handleToggleSelected = (id) => {
        const next = scenarios.map((sc) => {
            if (sc.id === id) {
                return { ...sc, selected: !sc.selected };
            }
            return sc;
        });
        onChangeScenarios(next);
    };

    const handleAddScenario = () => {
        const newId = `scenario_custom_${Date.now()}`;
        const newScenario = {
            id: newId,
            title: `Custom Scenario #${scenarios.length + 1}`,
            description: 'Custom opening scenario.',
            first_mes: 'Your opening narrative prose...',
            location_name: 'Sanctum',
            story_time: 'Evening',
            is_primary: scenarios.length === 0,
            selected: true,
        };
        onChangeScenarios([...scenarios, newScenario]);
        setExpandedIds((prev) => ({ ...prev, [newId]: true }));
    };

    const handleDeleteScenario = (id) => {
        const next = scenarios.filter((sc) => sc.id !== id);
        if (next.length > 0 && !next.some((s) => s.is_primary)) {
            next[0].is_primary = true;
        }
        onChangeScenarios(next);
    };

    return (
        <div className="space-y-4">
            {/* Header Toolbar */}
            <div className="flex flex-wrap items-center justify-between gap-3 p-4 rounded-2xl bg-gray-900/60 border border-white/10">
                <div>
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                        <MessageSquare size={16} className="text-emerald-400" />
                        Scenarios &amp; Alternate Greetings ({scenarios.length})
                    </h3>
                    <p className="text-xs text-gray-400 mt-0.5">
                        Each greeting on the SillyTavern card is converted into an interactive starting scenario with its own location and time.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={onRefineWithLLM}
                        disabled={isRefining || scenarios.length === 0}
                        className="px-3 py-1.5 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-200 text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-50"
                        title="Use LLM to infer rich titles, locations, and narrative premises for every greeting"
                    >
                        <Sparkles size={13} className={isRefining ? 'animate-spin text-purple-400' : 'text-purple-300'} />
                        <span>{isRefining ? 'Refining Scenarios...' : '✨ Refine All with LLM'}</span>
                    </button>

                    <button
                        type="button"
                        onClick={handleAddScenario}
                        className="px-3 py-1.5 rounded-xl bg-gray-800 hover:bg-gray-700 border border-white/10 text-gray-200 text-xs font-medium flex items-center gap-1.5 transition-all"
                    >
                        <Plus size={13} />
                        <span>Add Scenario</span>
                    </button>
                </div>
            </div>

            {/* Scenarios List */}
            <div className="space-y-3">
                {scenarios.map((sc, idx) => {
                    const isExpanded = !!expandedIds[sc.id];
                    const isEnriching = enrichingScenarioId === sc.id;

                    return (
                        <div
                            key={sc.id || idx}
                            className={clsx(
                                'rounded-2xl border transition-all overflow-hidden',
                                sc.is_primary
                                    ? 'bg-emerald-950/20 border-emerald-500/40 shadow-lg'
                                    : sc.selected
                                    ? 'bg-gray-900/50 border-white/10 hover:border-white/20'
                                    : 'bg-gray-950/40 border-white/5 opacity-60'
                            )}
                        >
                            {/* Scenario Header Bar */}
                            <div className="p-3.5 flex items-center justify-between gap-3">
                                <div className="flex items-center gap-3 min-w-0">
                                    <input
                                        type="checkbox"
                                        checked={sc.selected !== false}
                                        onChange={() => handleToggleSelected(sc.id)}
                                        title="Include this scenario in the world vault"
                                        className="accent-emerald-500 rounded cursor-pointer shrink-0"
                                    />

                                    <button
                                        type="button"
                                        onClick={() => handleSetPrimary(sc.id)}
                                        className={clsx(
                                            'px-2 py-0.5 rounded text-3xs font-bold uppercase transition-all shrink-0 flex items-center gap-1',
                                            sc.is_primary
                                                ? 'bg-emerald-500 text-black font-extrabold shadow-sm'
                                                : 'bg-gray-800 text-gray-400 hover:text-white border border-white/10'
                                        )}
                                        title="Click to make this the default opening scenario for chats"
                                    >
                                        {sc.is_primary && <Check size={10} />}
                                        {sc.is_primary ? 'Default Opening' : 'Set as Default'}
                                    </button>

                                    <div
                                        className="flex items-center gap-2 cursor-pointer min-w-0"
                                        onClick={() => toggleExpand(sc.id)}
                                    >
                                        <span className="text-xs font-bold text-gray-100 truncate">
                                            {sc.title || `Scenario #${idx + 1}`}
                                        </span>
                                        <span className="text-2xs text-gray-500 font-mono shrink-0">
                                            ({sc.location_name || 'Location'}, {sc.story_time || 'Evening'})
                                        </span>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2 shrink-0">
                                    <button
                                        type="button"
                                        onClick={() => toggleExpand(sc.id)}
                                        className="p-1 rounded text-gray-400 hover:text-white"
                                    >
                                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                    </button>

                                    {scenarios.length > 1 && (
                                        <button
                                            type="button"
                                            onClick={() => handleDeleteScenario(sc.id)}
                                            className="p-1 rounded text-gray-500 hover:text-red-400 transition-colors"
                                            title="Delete scenario"
                                        >
                                            <Trash2 size={13} />
                                        </button>
                                    )}
                                </div>
                            </div>

                            {/* Expanded Details Form */}
                            {isExpanded && (
                                <div className="p-4 pt-1 border-t border-white/5 space-y-3 bg-gray-950/30 text-xs">
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                        <div className="space-y-1">
                                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                Scenario Title
                                            </label>
                                            <input
                                                type="text"
                                                value={sc.title || ''}
                                                onChange={(e) => handleUpdateScenario(sc.id, 'title', e.target.value)}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-emerald-500/50"
                                            />
                                        </div>

                                        <div className="space-y-1">
                                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1">
                                                <MapPin size={11} className="text-emerald-400" /> Inferred Location
                                            </label>
                                            <input
                                                type="text"
                                                value={sc.location_name || ''}
                                                onChange={(e) => handleUpdateScenario(sc.id, 'location_name', e.target.value)}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-emerald-500/50"
                                            />
                                        </div>

                                        <div className="space-y-1">
                                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1">
                                                <Clock size={11} className="text-amber-400" /> Story Time / Era
                                            </label>
                                            <input
                                                type="text"
                                                value={sc.story_time || ''}
                                                onChange={(e) => handleUpdateScenario(sc.id, 'story_time', e.target.value)}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-100 focus:outline-none focus:border-emerald-500/50"
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-1">
                                        <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                            Premise &amp; Context
                                        </label>
                                        <textarea
                                            rows={2}
                                            value={sc.description || ''}
                                            onChange={(e) => handleUpdateScenario(sc.id, 'description', e.target.value)}
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-2.5 text-xs text-gray-200 focus:outline-none focus:border-emerald-500/50"
                                        />
                                    </div>

                                    <div className="space-y-1">
                                        <div className="flex items-center justify-between">
                                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                Opening Greeting Prose ({sc.first_mes?.length || 0} chars)
                                            </label>
                                            {onEnrichGreeting && (
                                                <button
                                                    type="button"
                                                    onClick={() => onEnrichGreeting(sc.id, sc.first_mes)}
                                                    disabled={isEnriching}
                                                    className="text-3xs text-purple-300 hover:text-purple-200 flex items-center gap-1 font-semibold"
                                                >
                                                    <Wand2 size={11} className={isEnriching ? 'animate-spin' : ''} />
                                                    <span>{isEnriching ? 'Enriching...' : '✨ Enrich Greeting'}</span>
                                                </button>
                                            )}
                                        </div>
                                        <textarea
                                            rows={4}
                                            value={sc.first_mes || ''}
                                            onChange={(e) => handleUpdateScenario(sc.id, 'first_mes', e.target.value)}
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-2.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-emerald-500/50 leading-relaxed"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
