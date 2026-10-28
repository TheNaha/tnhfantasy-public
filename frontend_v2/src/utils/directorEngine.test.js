import { describe, expect, it } from 'vitest';

import { classifyDirectorEngine, DIRECTOR_ENGINE_LEVELS } from './directorEngine';

describe('classifyDirectorEngine', () => {
    it('reads a live remote tier as live with its full stamp', () => {
        const info = classifyDirectorEngine({ engine_used: 'remote_laya_cpu:agent-1' });
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.live);
        expect(info.label).toBe('remote_laya_cpu:agent-1');
        expect(info.tone).toContain('emerald');
    });

    it('reads Modal, Beam and local tiers as live', () => {
        for (const engine of [
            'modal_laya_cpu:p1',
            'beam_laya_cpu:p2',
            'local_laya_cpu',
        ]) {
            expect(classifyDirectorEngine({ engine_used: engine }).level).toBe(
                DIRECTOR_ENGINE_LEVELS.live
            );
        }
    });

    it('downgrades the generative util-LLM fallback to reduced', () => {
        const info = classifyDirectorEngine({ engine_used: 'util_llm_json:p3' });
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.reduced);
        expect(info.tone).toContain('amber');
    });

    it('downgrades the heuristic fallback to heuristic', () => {
        const info = classifyDirectorEngine({ engine_used: 'heuristic' });
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.heuristic);
        expect(info.tone).toContain('amber');
    });

    it('reads a disabled decisions model as off', () => {
        const info = classifyDirectorEngine({ engine_used: 'disabled' });
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.off);
        expect(info.label).toBe('Director off');
        expect(info.tone).toContain('rose');
    });

    it('falls back to provider_tier when engine_used is missing', () => {
        expect(classifyDirectorEngine({ provider_tier: 'heuristic' }).level).toBe(
            DIRECTOR_ENGINE_LEVELS.heuristic
        );
    });

    it('shows an unstampable decision plainly instead of claiming it is degraded', () => {
        const info = classifyDirectorEngine({});
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.live);
        expect(info.label).toBe('laya');
    });

    it('survives a missing decision', () => {
        const info = classifyDirectorEngine(null);
        expect(info.level).toBe(DIRECTOR_ENGINE_LEVELS.live);
        expect(info.label).toBe('laya');
    });
});
