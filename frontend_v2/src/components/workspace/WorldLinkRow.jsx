import { Globe2 } from 'lucide-react';
import clsx from 'clsx';

import { QueryErrorState } from '../common/QueryState';

const countLabel = (n, singular, plural = `${singular}s`) => `${n} ${n === 1 ? singular : plural}`;

/**
 * The World a chat or a story belongs to, and what that world contributes.
 *
 * `Chat.world_id` / `Story.world_id` have been writable since 17c35e64 but were
 * reachable only from the new-chat wizard, so a world could be attached at
 * creation and never revised, inspected, or removed — and `worldLinkWarning`
 * promised a "World panel" that did not exist on either surface. This is that
 * panel: a plain select, revisitable from any chat or story at any time, that
 * also answers the question grouping exists to answer — what does picking this
 * actually add to the prompt.
 *
 * The counts come off the world row itself (`lorebook_ids`, `location_ids`,
 * `scenario_ids`), which is what the prompt assembly reads. They are the
 * world's *index*, not ownership of record, so a count of 0 is honest: the
 * world contributes its description and nothing else.
 */
export default function WorldLinkRow({ worldId, worlds = [], onChange, testId = 'world-link-row', queryErrors = {} }) {
    const world = worlds.find(w => w?.id === worldId) || null;
    const worldsError = queryErrors.worlds;

    const contributions = world ? [
        (world.lorebook_ids || []).length && countLabel(world.lorebook_ids.length, 'lorebook'),
        (world.location_ids || []).length && countLabel(world.location_ids.length, 'location'),
        (world.scenario_ids || []).length && countLabel(world.scenario_ids.length, 'scenario'),
    ].filter(Boolean) : [];

    return (
        <div className="glass-panel p-4 rounded-xl border border-white/5" data-testid={testId}>
            <div className="flex items-center justify-between gap-2 mb-3">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5 min-w-0">
                    <Globe2 size={12} className="text-cyan-400 shrink-0" /> World
                </h4>
                {worlds.length > 0 ? (
                    <select
                        aria-label="World"
                        data-testid={`${testId}-select`}
                        value={worldId || ''}
                        onChange={(e) => onChange?.(e.target.value)}
                        className={clsx(
                            'bg-gray-800 border text-xs rounded px-2 py-1 text-gray-300 focus:outline-none min-w-0 truncate max-w-[60%]',
                            world ? 'border-cyan-500/30' : 'border-gray-700'
                        )}
                    >
                        <option value="">No world</option>
                        {worlds.map(w => (
                            <option key={w.id} value={w.id}>{w.name}</option>
                        ))}
                    </select>
                ) : null}
            </div>

            {world ? (
                <div className="space-y-1.5">
                    {world.description && (
                        <p className="text-xs text-gray-400 leading-relaxed line-clamp-3">{world.description}</p>
                    )}
                    <p className="text-2xs text-gray-500">
                        {contributions.length > 0
                            ? `Added to every reply: ${contributions.join(' · ')}.`
                            : 'Added to every reply: this world\'s description. It has no lorebooks, locations or scenarios indexed yet.'}
                    </p>
                </div>
            ) : worldsError ? null : (
                // Suppressed when the fetch failed: printing "No worlds yet"
                // and a failure notice in the same panel is the self-
                // contradicting UI this whole chain exists to remove.
                <p className="text-xs text-gray-500">
                    {worlds.length === 0
                        ? 'No worlds yet. Create one to group characters, chats, locations and lorebooks under shared lore.'
                        : "A world feeds its own description, lorebooks, locations and scenario into every reply. You can pick, change or drop it here at any time."}
                </p>
            )}

            {/*
                A failed worlds fetch is not an empty vault.
                `useWorlds()` destructured `data` with a `= []` default, so the
                row rendered "No worlds yet. Create one…" — and rendered no
                `<select>` at all, since that is gated on `worlds.length > 0`.
                A world already attached to the chat also resolved to `null`
                here, so the panel could not even describe what was already in
                use. This is the one place the truth can be stated.
            */}
            {worldsError && (
                <QueryErrorState
                    noun={worldsError.noun}
                    error={worldsError.error}
                    onRetry={worldsError.refetch}
                />
            )}
        </div>
    );
}
