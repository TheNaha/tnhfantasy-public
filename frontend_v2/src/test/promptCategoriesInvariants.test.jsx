/**
 * The prompt-category list exists in one module.
 *
 * `['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom']`
 * was written out in four files. The hook merged it with the server's list, and
 * each of the three components then re-declared the same array as the default
 * for a destructured `data` — a list kept in sync by hand, three times over,
 * from a value the hook already guaranteed was populated.
 *
 * The check is generated from the string itself, so a fifth copy fails whether
 * it is written as a literal, spread from a local constant, or reordered.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { DEFAULT_PROMPT_CATEGORIES } from '../constants/prompts';

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..');
const WALK_SKIP = new Set(['node_modules', 'dist']);
const OWNER = 'constants/prompts.js';

function sourceFiles(dir = SRC, acc = []) {
    for (const entry of readdirSync(dir)) {
        if (WALK_SKIP.has(entry)) continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) sourceFiles(full, acc);
        else if (/\.jsx?$/.test(entry) && !/\.test\.jsx?$/.test(entry)) acc.push(full);
    }
    return acc;
}

/**
 * The one copy this batch cannot reach, with the reason.
 *
 * `pages/Prompts.jsx` still ends its `usePromptCategories()` destructure with
 * `= ['All', 'Portrait', …]`. It is owned by another workstream, so the fourth
 * copy of the list is still on disk. Listed rather than ignored so the guard
 * cannot quietly learn to tolerate it: when that file imports
 * `DEFAULT_PROMPT_CATEGORIES`, the staleness case below fails and the entry has
 * to be deleted.
 */
const HAND_ROLLED = {};

/** Any file that spells out more than one of the categories by hand. */
const allCopies = sourceFiles()
    .map((f) => ({ rel: relative(SRC, f).split(sep).join('/'), text: readFileSync(f, 'utf8') }))
    .filter(({ rel }) => rel !== OWNER)
    .filter(({ text }) => ['Portrait', 'Landscape'].every((c) => text.includes(`'${c}'`)));

const copies = allCopies.filter(({ rel }) => !(rel in HAND_ROLLED));

describe('the prompt-category list lives in one place', () => {
    it('no production module re-declares the categories', () => {
        expect(
            copies.map((c) => c.rel),
            `these modules spell out the category list themselves: ${copies.map((c) => c.rel).join(', ')}`
        ).toEqual([]);
    });

    it('the owning module still exports the list the components rely on', () => {
        expect(DEFAULT_PROMPT_CATEGORIES).toContain('All');
        expect(DEFAULT_PROMPT_CATEGORIES.length).toBeGreaterThan(3);
        expect(new Set(DEFAULT_PROMPT_CATEGORIES).size).toBe(DEFAULT_PROMPT_CATEGORIES.length);
    });

    it('names every exemption that is still needed', () => {
        const stale = [];
        for (const [rel, why] of Object.entries(HAND_ROLLED)) {
            const entry = allCopies.find((c) => c.rel === rel);
            if (!entry) { stale.push(`${rel}: no longer holds a hand-written copy — delete the entry`); continue; }
            if (/DEFAULT_PROMPT_CATEGORIES/.test(entry.text)) {
                stale.push(`${rel}: now imports DEFAULT_PROMPT_CATEGORIES — delete the entry`);
            } else if (!why || why.length < 20) {
                stale.push(`${rel}: exemption has no reason worth reading`);
            }
        }
        expect(stale, stale.join('\n')).toEqual([]);
    });

    it('can fail (canary)', () => {
        const reintroduced = "const CATS = ['All', 'Portrait', 'Landscape'];\n";
        const isCopy = ['Portrait', 'Landscape'].every((c) => reintroduced.includes(`'${c}'`));
        expect(isCopy).toBe(true);
        expect(readFileSync(join(SRC, OWNER), 'utf8')).toContain('DEFAULT_PROMPT_CATEGORIES');
    });
});

const getCategories = vi.hoisted(() => vi.fn());
vi.mock('../api/promptsApi', () => ({
    default: { getCategories, listPrompts: vi.fn() },
}));

describe('usePromptCategories', () => {
    let usePromptCategories;

    beforeEach(async () => {
        vi.resetModules();
        getCategories.mockReset();
        getCategories.mockResolvedValue({ categories: ['Portrait', 'Studio'] });
        usePromptCategories = (await import('../hooks/usePrompts')).usePromptCategories;
    });

    const wrapper = (client) => function Wrapper({ children }) {
        return React.createElement(QueryClientProvider, { client: client }, children);
    };

    it('has a list on the very first render, before the request settles', () => {
        // The reason the three component-level defaults existed. Removing them
        // without this makes `categories.filter(...)` throw on mount.
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(() => usePromptCategories(), { wrapper: wrapper(client) });
        expect(result.current.data).toEqual(DEFAULT_PROMPT_CATEGORIES);
        return waitFor(() => expect(result.current.isPlaceholderData).toBe(false));
    });

    it('merges the server list over the defaults', async () => {
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(() => usePromptCategories(), { wrapper: wrapper(client) });
        await waitFor(() => expect(result.current.isPlaceholderData).toBe(false));
        expect(result.current.data).toEqual([...DEFAULT_PROMPT_CATEGORIES, 'Studio']);
    });

    it('still returns the defaults when the server sends none', async () => {
        getCategories.mockResolvedValue({ categories: null });
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const { result } = renderHook(() => usePromptCategories(), { wrapper: wrapper(client) });
        await waitFor(() => expect(result.current.isPlaceholderData).toBe(false));
        expect(result.current.data).toEqual(DEFAULT_PROMPT_CATEGORIES);
    });
});