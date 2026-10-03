import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryErrorState, QueryGate } from '../components/common/QueryState';

const PAGES_DIR = join(process.cwd(), 'src', 'pages');

const readPage = (name) => readFileSync(join(PAGES_DIR, name), 'utf8');

/**
 * Seven pages rendered a failed fetch as a genuinely empty vault.
 *
 * `/roleplay`, `/characters`, `/lorebooks`, `/locations`, `/scenarios`,
 * `/personas` and `/voices` each destructured `data` and `isLoading` from
 * their query, read no `isError`, and fell through to an empty state: "No
 * Characters Found — you haven't created any characters yet. Create one to
 * start roleplaying", next to a vault that already held three characters.
 * Clicking that button makes a duplicate.
 *
 * A per-page assertion would be a list of seven filenames, and the eighth page
 * would be written without one. This asserts the *rule* instead: a page that
 * ships an empty state has to handle the error state, or `isError` is missing
 * from it somewhere and the next audit has to find it by hand again.
 */

/** Empty-state copy that means "you have nothing" rather than "this failed". */
const EMPTY_STATE_COPY = [
    'No Characters Found',
    "You haven't created any characters yet",
    'No lorebooks yet',
    'No locations yet',
    'No scenarios yet',
    'No personas yet',
    'No voice models yet',
    'Your next session will appear here',
];

const pages = readdirSync(PAGES_DIR).filter((f) => f.endsWith('.jsx') && !f.endsWith('.test.jsx'));

describe('a failed fetch is never rendered as an empty vault', () => {
    it('found the page set (guards against the glob silently matching nothing)', () => {
        expect(pages.length).toBeGreaterThan(15);
    });

    const offenders = [];
    for (const file of pages) {
        const source = readPage(file);
        const shipsEmptyState = EMPTY_STATE_COPY.some((copy) => source.includes(copy));
        if (!shipsEmptyState) continue;
        const handlesError =
            source.includes('isError') ||
            source.includes('QueryErrorState') ||
            source.includes('QueryGate');
        if (!handlesError) offenders.push(file);
    }

    it('every page with an empty state also has an error state', () => {
        expect(offenders).toEqual([]);
    });
});

describe('QueryState', () => {
    const renderInRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

    it('names what failed and says it is not the same as having none', () => {
        renderInRouter(<QueryErrorState noun="characters" error={new Error('boom')} />);
        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(/could not load your characters/i);
        expect(alert).toHaveTextContent(/boom/);
        expect(alert).toHaveTextContent(/not the same as having none/i);
    });

    it('unwraps a FastAPI 422 detail, naming the field that was rejected', () => {
        const error = { response: { data: { detail: [{ loc: ['body', 'name'], msg: 'field required' }] } } };
        renderInRouter(<QueryErrorState noun="lorebooks" error={error} />);
        expect(screen.getByRole('alert')).toHaveTextContent('name: field required');
    });

    it('offers a retry that re-runs the query', async () => {
        const onRetry = vi.fn();
        renderInRouter(<QueryErrorState noun="worlds" error={new Error('x')} onRetry={onRetry} />);
        screen.getByRole('button', { name: /try again/i }).click();
        expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it('omits the retry button when there is nothing to retry with', () => {
        renderInRouter(<QueryErrorState noun="worlds" error={new Error('x')} />);
        expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    });

    it('QueryGate renders the loading fallback, then the error, then children', () => {
        const { rerender } = renderInRouter(
            <QueryGate isLoading noun="chats" loadingFallback={<span>loading…</span>}>
                <span>list</span>
            </QueryGate>
        );
        expect(screen.getByText('loading…')).toBeTruthy();

        rerender(
            <MemoryRouter>
                <QueryGate isLoading={false} isError error={new Error('down')} onRetry={() => {}} noun="chats">
                    <span>list</span>
                </QueryGate>
            </MemoryRouter>
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText('list')).toBeNull();
    });

    it('QueryGate never substitutes the children for a failure', () => {
        // The exact inversion this component exists to prevent: the list
        // rendering because the fetch did.
        renderInRouter(
            <QueryGate isLoading={false} isError error={new Error('down')} noun="chats">
                <span>No chats yet</span>
            </QueryGate>
        );
        expect(screen.queryByText('No chats yet')).toBeNull();
    });
});
