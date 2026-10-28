// How to read a Director decision's engine stamp.
//
// Laya answers from the best tier of the cascade that was alive: a remote
// classification pass (remote agent, Modal, Beam), the in-process CPU
// `LayaRunner`, a generative util-LLM fallback, the deterministic
// heuristics — or nothing at all, when the decisions model is disabled.
// Every decision carries that tier on `engine_used` (with a provider id
// after a `:`), and the Studio's Decision Traces show it verbatim.
//
// The chat's decision panel printed the stamp in the same green whether the
// engine was live or the rule-based fallback, so a director that had been
// down for an hour looked exactly like a healthy one. This classifier maps
// the stamp to a level so panels can colour and word the state honestly.

export const DIRECTOR_ENGINE_LEVELS = {
    live: 'live',
    reduced: 'reduced',
    heuristic: 'heuristic',
    off: 'off',
};

const CLASSES = {
    live: {
        tone: 'text-emerald-400',
        chip: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
    },
    reduced: {
        tone: 'text-amber-300',
        chip: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
    },
    heuristic: {
        tone: 'text-amber-400',
        chip: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
    },
    off: {
        tone: 'text-rose-400',
        chip: 'bg-rose-500/10 text-rose-300 border-rose-500/25',
    },
};

export function classifyDirectorEngine(decision) {
    const raw = String(decision?.engine_used ?? decision?.provider_tier ?? '');
    const engine = raw ? raw.split(':')[0] : '';

    if (engine === 'disabled') {
        return { level: DIRECTOR_ENGINE_LEVELS.off, label: 'Director off', ...CLASSES.off };
    }
    if (engine === 'heuristic') {
        return {
            level: DIRECTOR_ENGINE_LEVELS.heuristic,
            label: 'heuristic fallback',
            ...CLASSES.heuristic,
        };
    }
    if (engine === 'util_llm_json') {
        return {
            level: DIRECTOR_ENGINE_LEVELS.reduced,
            label: 'util LLM (reduced)',
            ...CLASSES.reduced,
        };
    }
    // A live tier keeps its full stamp (`modal_laya_cpu:p1`, `local_laya_cpu`).
    // A decision without a stamp predates the telemetry, or arrived from a
    // caller that never set it — shown plainly rather than dressed as live.
    return { level: DIRECTOR_ENGINE_LEVELS.live, label: raw || 'laya', ...CLASSES.live };
}
