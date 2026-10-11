/**
 * The provider type selector renders the category x transport MATRIX, not a flat
 * per-category list.
 *
 * Before this, the modal grouped options by category, so choosing a "Language
 * Model" gave one list of seven where three said "Direct" only in the label and
 * the four Beam/Remote LLM/TTS cells — which the backend registry now declares —
 * were indistinguishable from the rest. The matrix is what makes "this transport
 * offers these categories" legible, and an unfilled cell must still appear so it
 * reads as "not available" rather than as a choice nobody made.
 */
import { render, waitFor } from '@testing-library/react';

import { describe, expect, it, vi, beforeEach } from 'vitest';

const getSchemasMock = vi.fn();
// ProviderModal imports `providersApi` from '../../api' (the barrel), not from
// '../../api/providers' — mocking the leaf module leaves the barrel's real
// binding in place and the modal silently falls back to its static list.
vi.mock('../../api', () => ({
    api: { get: vi.fn(), post: vi.fn() },
    API_V2_BASE: '/api/v2',
    providersApi: { getSchemas: (...a) => getSchemasMock(...a) },
}));

import ProviderModal from './ProviderModal';

const PAYLOAD = {
    engines: {
        modal:          { id: 'modal',          name: 'Modal (ComfyUI)',                category: 'image', transport: 'modal',  credentials: [], config: [] },
        modal_tts:      { id: 'modal_tts',      name: 'Modal (TTS)',                    category: 'tts',   transport: 'modal',  credentials: [], config: [] },
        modal_vllm:     { id: 'modal_vllm',     name: 'Modal (LLM)',                    category: 'llm',   transport: 'modal',  credentials: [], config: [] },
        beam:           { id: 'beam',           name: 'Beam (ComfyUI)',                 category: 'image', transport: 'beam',   credentials: [], config: [] },
        beam_llm:       { id: 'beam_llm',       name: 'Beam (LLM)',                     category: 'llm',   transport: 'beam',   credentials: [], config: [] },
        beam_tts:       { id: 'beam_tts',       name: 'Beam (TTS)',                     category: 'tts',   transport: 'beam',   credentials: [], config: [] },
        remote_comfy:   { id: 'remote_comfy',   name: 'Self-hosted container (ComfyUI)', category: 'image', transport: 'remote', credentials: [], config: [] },
        remote_llm:     { id: 'remote_llm',     name: 'Self-hosted LLM container',     category: 'llm',   transport: 'remote', credentials: [], config: [] },
        remote_tts:     { id: 'remote_tts',     name: 'Self-hosted TTS container',     category: 'tts',   transport: 'remote', credentials: [], config: [] },
        direct_url:     { id: 'direct_url',     name: 'Direct ComfyUI server',          category: 'image', transport: 'direct', credentials: [], config: [] },
        direct_tts:     { id: 'direct_tts',     name: 'Direct ComfyUI (TTS)',           category: 'tts',   transport: 'direct', credentials: [], config: [] },
        openai_compat:  { id: 'openai_compat',  name: 'Direct: OpenAI-compatible API',  category: 'llm',   transport: 'direct', credentials: [], config: [] },
    },
    categories: [
        { id: 'image', label: 'Image Generation' },
        { id: 'llm', label: 'Language Models' },
        { id: 'tts', label: 'Voice & Audio' },
    ],
    transports: [
        { id: 'modal', label: 'Modal (serverless)' },
        { id: 'beam', label: 'Beam.cloud (serverless)' },
        { id: 'remote', label: 'Self-hosted container' },
        { id: 'direct', label: 'Direct API endpoint' },
    ],
    matrix: [
        { category: 'image', transport: 'modal', provider_type: 'modal', filled: true },
        { category: 'llm', transport: 'modal', provider_type: 'modal_vllm', filled: true },
        { category: 'tts', transport: 'modal', provider_type: 'modal_tts', filled: true },
        { category: 'image', transport: 'beam', provider_type: 'beam', filled: true },
        { category: 'llm', transport: 'beam', provider_type: 'beam_llm', filled: true },
        { category: 'tts', transport: 'beam', provider_type: 'beam_tts', filled: true },
        { category: 'image', transport: 'remote', provider_type: 'remote_comfy', filled: true },
        { category: 'llm', transport: 'remote', provider_type: 'remote_llm', filled: true },
        { category: 'tts', transport: 'remote', provider_type: 'remote_tts', filled: true },
        { category: 'image', transport: 'direct', provider_type: 'direct_url', filled: true },
        { category: 'llm', transport: 'direct', provider_type: null, filled: false },
        { category: 'tts', transport: 'direct', provider_type: 'direct_tts', filled: true },
    ],
};

function renderModal() {
    return render(
        <ProviderModal
            provider={null}
            onClose={() => {}}
            onSave={() => {}}
            saveProvider={vi.fn().mockResolvedValue({})}
        />
    );
}

describe('ProviderModal type selector', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        getSchemasMock.mockResolvedValue(PAYLOAD);
    });

    it('groups the options by TRANSPORT, one optgroup each', async () => {
        renderModal();
        await waitFor(() => expect(getSchemasMock).toHaveBeenCalled());

        const groups = Array.from(document.querySelectorAll('optgroup'));
        const labels = groups.map((g) => g.label);
        expect(labels).toEqual([
            'Modal (serverless)',
            'Beam.cloud (serverless)',
            'Self-hosted container',
            'Direct API endpoint',
        ]);
    });

    it('names the category in each option, so the grid is legible', async () => {
        renderModal();
        await waitFor(() => expect(getSchemasMock).toHaveBeenCalled());

        const beam = Array.from(document.querySelectorAll('optgroup'))
            .find((g) => g.label === 'Beam.cloud (serverless)');
        const options = Array.from(beam.querySelectorAll('option')).map((o) => o.value);
        expect(options).toEqual(['beam', 'beam_llm', 'beam_tts']);

        // And the label carries the category, not just the engine name.
        const text = Array.from(beam.querySelectorAll('option')).map((o) => o.textContent);
        expect(text.join(' ')).toContain('Image Generation');
        expect(text.join(' ')).toContain('Language Models');
        expect(text.join(' ')).toContain('Voice & Audio');
    });

    it('covers all four transports and all three categories from the matrix', async () => {
        renderModal();
        await waitFor(() => expect(getSchemasMock).toHaveBeenCalled());

        const byTransport = {};
        for (const g of document.querySelectorAll('optgroup')) {
            byTransport[g.label] = Array.from(g.querySelectorAll('option')).map((o) => o.value);
        }
        expect(Object.keys(byTransport)).toHaveLength(4);
        const all = Object.values(byTransport).flat();
        expect(all).toHaveLength(12); // 4 transports x 3 categories, direct/llm filled by openai_compat
        expect(all).toContain('beam_tts');
        expect(all).toContain('remote_llm');
        expect(all).toContain('remote_tts');
    });

    it('sends the whole payload through, not just engines', async () => {
        // Dropping `transports`/`matrix` is what made the modal fall back to the
        // flat per-category grouping.
        renderModal();
        await waitFor(() => expect(getSchemasMock).toHaveBeenCalled());
        const groups = Array.from(document.querySelectorAll('optgroup'));
        expect(groups).toHaveLength(4);
    });

    it('the select is fully populated from the matrix', async () => {
        renderModal();
        await waitFor(() => expect(getSchemasMock).toHaveBeenCalled());

        const select = document.querySelector('select');
        expect(select).toBeTruthy();
        expect(Array.from(select.options).length).toBeGreaterThan(10);
    });
});
