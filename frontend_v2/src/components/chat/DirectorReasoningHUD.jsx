import React, { useState } from 'react';
import clsx from 'clsx';
import {
    Brain, Sparkles, ChevronDown, ChevronUp, Clock, MapPin, Shield, Zap,
    Gauge, Activity, Compass, Dices, Layers, Bot, ArrowRight
} from 'lucide-react';
import { useLLMDirectorGates } from '../../hooks/useLLMProviderStatus';

const TENSION_COLOR = {
    calm: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    normal: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
    rising: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    high: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
    climactic: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
};

const FATE_OUTCOME_STYLE = {
    critical_success: 'text-emerald-300 bg-emerald-500/20 border-emerald-500/30',
    success: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    success_with_cost: 'text-amber-300 bg-amber-500/20 border-amber-500/30',
    complication: 'text-orange-400 bg-orange-500/15 border-orange-500/25',
    failure: 'text-rose-400 bg-rose-500/20 border-rose-500/30',
};

/**
 * The offline fallback gate list.
 *
 * The backend serves the canonical registry (`GET /llm/director/gates`),
 * which is what the HUD uses. This copy is only for when that request has
 * not landed — and it is deliberately kept, because four of its keys are
 * ALIASES the Director never emits (`gate_location`, `gate_weather`,
 * `gate_character_activity`, `gate_quests_and_goals`), and each carries a
 * `fallbackKey` naming the coarse gate the Director does emit in its place.
 * Those aliases are why the list needs a fallback at all; the canonical
 * registry has the fine-grained keys and needs none.
 */
const SIXTEEN_GATES = [
    { key: 'gate_character_mood', fallbackKey: 'gate_character_mood', label: 'Character Mood' },
    { key: 'gate_scene_tone', fallbackKey: 'gate_scene_tone', label: 'Tone & Atmosphere' },
    { key: 'gate_relationship_dynamic', fallbackKey: 'gate_relationship_dynamic', label: 'Relationship Dynamic' },
    { key: 'gate_character_outfit', fallbackKey: 'gate_character_state', label: 'Outfit & Appearance' },
    { key: 'gate_character_activity', fallbackKey: 'gate_character_state', label: 'Current Activity' },
    { key: 'gate_physical_condition', fallbackKey: 'gate_character_state', label: 'Physical Condition' },
    { key: 'gate_inventory_or_items', fallbackKey: 'gate_inventory_or_items', label: 'Inventory & Items' },
    { key: 'gate_world_clock', fallbackKey: 'gate_world_state', label: 'World Clock & Time' },
    { key: 'gate_location', fallbackKey: 'gate_world_state', label: 'Location & Setting' },
    { key: 'gate_weather', fallbackKey: 'gate_world_state', label: 'Weather & Environment' },
    { key: 'gate_character_skills', fallbackKey: 'gate_character_skills', label: 'Character Skills' },
    { key: 'gate_user_skills', fallbackKey: 'gate_user_skills', label: 'User Persona Skills' },
    { key: 'gate_quests_and_goals', fallbackKey: 'gate_quests_and_goals', label: 'Quests & Goals' },
    { key: 'gate_social_status', fallbackKey: 'gate_social_status', label: 'Social Status & Rank' },
    { key: 'gate_durable_memory', fallbackKey: 'gate_durable_memory', label: 'Durable Memory' },
    { key: 'gate_lore_discovery', fallbackKey: 'gate_lore_discovery', label: 'Lore Discovery' },
];

export default function DirectorReasoningHUD({ jobData, pendingSpeaker }) {
    const [expanded, setExpanded] = useState(false);
    const [showInspector, setShowInspector] = useState(false);
    const decision = jobData?.directorDecision;

    // The canonical registry, from the same module the Director reads its
    // gate map from. Until it arrives the offline list above is used, so the
    // panel is never empty and never invents gates the Director does not
    // emit.
    const gatesQuery = useLLMDirectorGates();
    const registry = gatesQuery.data;
    const canonicalGates = registry?.categories?.flatMap((c) => c.gates || []) || null;
    const gates = canonicalGates && canonicalGates.length > 0
        ? canonicalGates.map((g) => ({ key: g.key, fallbackKey: g.key, label: g.label }))
        : SIXTEEN_GATES;
    const gateThreshold = registry?.threshold ?? decision?.updater_evaluation?.activation_threshold ?? 0.55;

    return (
        <div className="mb-2 rounded-xl border border-white/10 bg-gray-900/80 backdrop-blur-md overflow-hidden text-xs shadow-lg transition-all duration-300">
            {/* Live Telemetry Header Bar */}
            <div className="px-3 py-2 flex flex-wrap items-center justify-between gap-2 border-b border-white/5 bg-black/30">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-3xs font-bold uppercase tracking-wider">
                        <Brain size={12} className="animate-pulse text-emerald-400" />
                        <span>Director &amp; Reasoning</span>
                    </span>

                    {decision?.pacing_directive && (
                        <span className="px-2 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/25 text-blue-300 text-3xs font-medium">
                            Pacing: <span className="font-semibold">{decision.pacing_directive}</span>
                        </span>
                    )}

                    {decision?.scene_tension != null && (
                        <span className={clsx("px-2 py-0.5 rounded-full border text-3xs font-medium", TENSION_COLOR[decision.scene_tension_label] || TENSION_COLOR.normal)}>
                            Tension: <span className="font-semibold">{decision.scene_tension}/5 ({decision.scene_tension_label})</span>
                        </span>
                    )}

                    {decision?.emotional_tone && (
                        <span className="px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/25 text-purple-300 text-3xs font-medium hidden sm:inline-flex">
                            Tone: {decision.emotional_tone}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    {/* Token Speedometer */}
                    {jobData?.speedTps ? (
                        <span className="flex items-center gap-1 font-mono text-3xs text-emerald-400">
                            <Zap size={11} className="animate-bounce" />
                            {jobData.speedTps} tok/s
                        </span>
                    ) : (
                        <span className="flex items-center gap-1 text-3xs text-blue-400/80">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                            {jobData?.phase === 'evaluating_prompt' ? 'Evaluating prompt...' : 'Synthesizing...'}
                        </span>
                    )}

                    {decision && (
                        <button
                            type="button"
                            onClick={() => setExpanded(v => !v)}
                            className="p-1 rounded text-gray-400 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-0.5 text-3xs"
                            title="Toggle detailed decision telemetry"
                        >
                            <span>{expanded ? 'Less' : 'Details'}</span>
                            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        </button>
                    )}
                </div>
            </div>

            {/* 5-Step Pipeline Progress Bar */}
            <div className="px-3 py-1.5 flex items-center justify-between gap-1.5 border-b border-white/5 bg-black/20 text-3xs font-medium overflow-x-auto custom-scrollbar">
                <div className="flex items-center gap-1 shrink-0 text-blue-300">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                    <span>1. Triage: <strong className="font-bold">{decision?.next_speaker || 'Character'}</strong></span>
                </div>
                <ArrowRight size={10} className="text-gray-600 shrink-0" />
                <div className="flex items-center gap-1 shrink-0 text-indigo-300">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                    <span>2. Agent Gen</span>
                </div>
                <ArrowRight size={10} className="text-gray-600 shrink-0" />
                <div className="flex items-center gap-1 shrink-0 text-amber-300">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    <span>3. Completion</span>
                </div>
                <ArrowRight size={10} className="text-gray-600 shrink-0" />
                <div className="flex items-center gap-1 shrink-0">
                    <span className={clsx("w-1.5 h-1.5 rounded-full", decision?.should_run_updater ? "bg-purple-400 animate-pulse" : "bg-gray-600")} />
                    <span className={decision?.should_run_updater ? "text-purple-300 font-semibold" : "text-gray-500"}>
                        4. 16-Gate Statekeeper
                    </span>
                </div>
                <ArrowRight size={10} className="text-gray-600 shrink-0" />
                <div className="flex items-center gap-1 shrink-0">
                    <span className={clsx("w-1.5 h-1.5 rounded-full", decision?.should_trigger_image ? "bg-pink-400 animate-pulse" : "bg-gray-600")} />
                    <span className={decision?.should_trigger_image ? "text-pink-300 font-semibold" : "text-gray-500"}>
                        5. Illustrate
                    </span>
                </div>
            </div>

            {/* Quick Context Summary Row */}
            <div className="px-3 py-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-3xs text-gray-400 bg-white/[0.02]">
                <span className="flex items-center gap-1">
                    <span>Agent:</span>
                    <strong className="px-1.5 py-0.2 rounded bg-blue-500/20 text-blue-300 border border-blue-500/30 uppercase font-bold">
                        {decision?.next_speaker || pendingSpeaker?.name || 'Character'}
                    </strong>
                </span>
                {decision?.character_expression && (
                    <span>
                        Expression: <strong className="text-amber-300">{decision.character_expression}</strong>
                    </span>
                )}
                {decision?.character_mood && (
                    <span>
                        Mood: <strong className="text-pink-300">{decision.character_mood.replace(/_/g, ' ')}</strong>
                    </span>
                )}
                {decision?.affinity_delta != null && decision.affinity_delta !== 0 && (
                    <span>
                        Affinity:{' '}
                        <strong className={decision.affinity_delta > 0 ? "text-emerald-400" : "text-rose-400"}>
                            {decision.affinity_delta > 0 ? `+${decision.affinity_delta}` : decision.affinity_delta}
                        </strong>
                    </span>
                )}
                {jobData?.providerId && (
                    <span>
                        Worker: <strong className="font-mono text-sky-300">{jobData.providerId}</strong>
                    </span>
                )}
                {decision?.fate_check_resolved && (
                    <span className="flex items-center gap-1">
                        <Dices size={10} className="text-amber-400" />
                        Fate Check:{' '}
                        <span className={clsx("px-1.5 py-0.2 rounded border font-semibold", FATE_OUTCOME_STYLE[decision.fate_outcome] || 'text-gray-300')}>
                            {decision.fate_outcome || 'Checked'}
                        </span>
                    </span>
                )}
            </div>

            {/* Expandable 13-Decision Breakdown */}
            {expanded && decision && (
                <div className="p-3 border-t border-white/5 bg-black/40 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                    <div className="grid gap-2.5 sm:grid-cols-3">
                        {/* 1. Turn & Pacing */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1 pb-1 border-b border-white/5">
                                <Compass size={11} className="text-blue-400" />
                                Turn &amp; Pacing
                            </div>
                            <div className="text-gray-300"><b>Speaker:</b> <span className="text-emerald-300">{decision.next_speaker}</span></div>
                            <div className="text-gray-300"><b>Directive:</b> <span className="text-blue-300">{decision.pacing_directive}</span></div>
                            <div className="text-gray-300"><b>Speed:</b> {decision.pacing_speed_label} ({decision.pacing_speed}/4)</div>
                            <div className="text-gray-300"><b>Tone:</b> <span className="text-purple-300">{decision.emotional_tone}</span></div>
                            <div className="text-gray-300"><b>Continue Chain:</b> {Math.round((decision.continue_chain_prob || 0) * 100)}%</div>
                        </div>

                        {/* 2. Visuals & Fate Check */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1 pb-1 border-b border-white/5">
                                <Sparkles size={11} className="text-amber-400" />
                                Visuals &amp; Fate
                            </div>
                            <div className="text-gray-300"><b>Expression:</b> <span className="text-amber-300">{decision.character_expression}</span></div>
                            <div className="text-gray-300"><b>Image Focus:</b> {decision.image_focus}</div>
                            <div className="text-gray-300"><b>Trigger Image:</b> {Math.round((decision.trigger_image_prob || 0) * 100)}% (≥{Math.round((decision.image_threshold ?? 0.65) * 100)}%)</div>
                            <div className="text-gray-300">
                                <b>Action Risk:</b>{' '}
                                <span className={decision.is_risky_action_probability >= 0.5 ? 'text-amber-400 font-semibold' : 'text-gray-400'}>
                                    {Math.round((decision.is_risky_action_probability || 0) * 100)}% ({decision.action_difficulty_label || 'normal'})
                                </span>
                            </div>
                            {decision.director_instruction && (
                                <div className="mt-1 pt-1 border-t border-white/5 text-gray-400 italic">
                                    &ldquo;{decision.director_instruction}&rdquo;
                                </div>
                            )}
                        </div>

                        {/* 3. Statekeeper Gates */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1.5 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between pb-1 border-b border-white/5">
                                <span className="flex items-center gap-1">
                                    <Shield size={11} className="text-purple-400" />
                                    Statekeeper Gates
                                </span>
                                <span className={clsx(
                                    "px-1.5 py-0.5 rounded text-3xs font-bold",
                                    decision.should_run_updater ? "bg-purple-500/25 text-purple-300 border border-purple-500/40" : "bg-gray-800 text-gray-400"
                                )}>
                                    {decision.should_run_updater ? "⚡ ACTIVE / RUNS" : "⏸️ IDLE"}
                                </span>
                            </div>

                            {decision.updater_evaluation?.diagnostic_summary && (
                                <div className="text-3xs text-purple-200/90 bg-purple-950/40 border border-purple-500/20 rounded p-1.5 leading-snug">
                                    {decision.updater_evaluation.diagnostic_summary}
                                </div>
                            )}

                            <div className="space-y-1 max-h-60 overflow-y-auto custom-scrollbar pr-1">
                                {gates.map(({ key, fallbackKey, label }) => {
                                    const prob = decision.updater_gates?.[key] ?? decision.updater_gates?.[fallbackKey];
                                    const pct = Math.round((prob || 0) * 100);
                                    const thresholdPct = Math.round((gateThreshold || 0.55) * 100);
                                    const active = pct >= thresholdPct;
                                    return (
                                        <div key={key} className="space-y-0.5">
                                            <div className="flex justify-between">
                                                <span className={active ? 'text-purple-300 font-semibold' : 'text-gray-400'}>{label}</span>
                                                <span className={clsx("font-mono", active ? "text-purple-300 font-bold" : "text-gray-500")}>
                                                    {pct}% {active && '✓'}
                                                </span>
                                            </div>
                                            <div className="w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                                                <div
                                                    className={clsx("h-full rounded-full transition-all duration-300", active ? "bg-gradient-to-r from-purple-500 to-indigo-400" : "bg-gray-700")}
                                                    style={{ width: `${pct}%` }}
                                                />
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>

                    {/* Question & Rubric Inspector Toggle */}
                    {decision.questions_evaluated?.length > 0 && (
                        <div className="pt-2 border-t border-white/5 space-y-2">
                            <button
                                type="button"
                                onClick={() => setShowInspector(v => !v)}
                                className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-gray-800/60 hover:bg-gray-800 border border-white/5 text-gray-300 transition-colors text-3xs font-medium"
                            >
                                <span className="flex items-center gap-1.5">
                                    <Layers size={11} className="text-emerald-400" />
                                    <span>Question &amp; Decision Inspector ({decision.questions_evaluated.length} questions evaluated)</span>
                                </span>
                                <span className="text-gray-400 font-mono flex items-center gap-1">
                                    {showInspector ? 'Hide Rubrics' : 'View Full Rubrics & Choices'}
                                    {showInspector ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                                </span>
                            </button>

                            {showInspector && (
                                <div className="max-h-60 overflow-y-auto space-y-1.5 pr-1 rounded-lg border border-white/5 p-2 bg-black/50 scrollbar-thin scrollbar-thumb-gray-800">
                                    {decision.questions_evaluated.map((q) => (
                                        <div key={q.key} className="p-2 rounded bg-gray-900/80 border border-white/5 space-y-1 text-3xs">
                                            <div className="flex items-center justify-between gap-2">
                                                <div className="flex items-center gap-1.5">
                                                    <span className="px-1.5 py-0.2 rounded bg-gray-800 text-gray-400 font-mono text-3xs uppercase">
                                                        {q.category}
                                                    </span>
                                                    <span className="font-semibold text-gray-200">{q.prompt}</span>
                                                </div>
                                                <span className={clsx(
                                                    "px-1.5 py-0.2 rounded font-mono font-bold text-3xs shrink-0",
                                                    q.status?.includes('FIRED') || q.status?.includes('Triggered') || q.status?.includes('YES')
                                                        ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                                                        : "bg-gray-800 text-gray-400"
                                                )}>
                                                    {q.status}
                                                </span>
                                            </div>
                                            {q.options && typeof q.options === 'object' && (
                                                <details className="text-gray-500 text-3xs mt-1">
                                                    <summary className="cursor-pointer hover:text-gray-400 select-none">
                                                        Available choices &amp; rubric
                                                    </summary>
                                                    <div className="mt-1 pl-2 border-l border-white/10 space-y-0.5 font-mono text-gray-400">
                                                        {Object.entries(q.options).map(([optKey, optDesc]) => (
                                                            <div key={optKey} className={clsx(String(q.value) === optKey && "text-emerald-300 font-semibold")}>
                                                                <span className="text-gray-300">{optKey}:</span> {String(optDesc)}
                                                                {q.probabilities?.[optKey] != null && (
                                                                    <span className="ml-1 text-emerald-400">({Math.round(q.probabilities[optKey] * 100)}%)</span>
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                </details>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
