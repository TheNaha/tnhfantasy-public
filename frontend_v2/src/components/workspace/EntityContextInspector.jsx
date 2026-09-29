import { useId, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
    BookOpen, ChevronDown, Compass, Edit2, ExternalLink,
    Loader2, MapPin, PanelRightOpen, User,
} from 'lucide-react';
import { useLorebookEntries } from '../../hooks/useLorebooks';
import { getAvatarUrl } from '../../hooks/useCharacters';
import { selectActivatedEntries } from '../../utils/lorebookActivation';

const QUICK_LINKS = [
    { to: '/world-vault', label: 'World Vault', icon: Compass },
    { to: '/characters', label: 'Characters', icon: User },
    { to: '/lorebooks', label: 'Lorebooks', icon: BookOpen },
    { to: '/locations', label: 'Locations', icon: MapPin },
];

function pickById(collection, ids) {
    const list = Array.isArray(collection) ? collection : [];
    if (!Array.isArray(ids) || ids.length === 0) return [];
    const wanted = ids.filter(Boolean);
    return list.filter(item => item && wanted.includes(item.id));
}

/**
 * Groups `characterLorebookLinks` by the character that brought the book in,
 * keeping first-seen order for both the owners and their books — the call site
 * decides the order, and re-sorting here would make the panel disagree with
 * the chat's `additional_character_ids`.
 */
function groupByOwner(links) {
    const groups = new Map();
    for (const link of links) {
        if (!link || !link.lorebookId) continue;
        const owner = link.characterName || '';
        if (!groups.has(owner)) groups.set(owner, []);
        groups.get(owner).push(link);
    }
    return [...groups.entries()].map(([owner, entries]) => ({ owner, entries }));
}

function EntryRow({ entry }) {
    return (
        <li className="px-2.5 py-2 rounded-lg bg-gray-900/40 border border-white/5">
            <div className="flex items-start gap-2">
                <span
                    className={clsx(
                        'mt-0.5 text-2xs font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0',
                        entry._alwaysOn
                            ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                            : 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/30'
                    )}
                >
                    {entry._alwaysOn ? 'always' : 'triggered'}
                </span>
                <div className="min-w-0 flex-1">
                    {entry._matchedKeys?.length > 0 && (
                        <p className="text-2xs text-indigo-300/80 truncate">
                            {entry._matchedKeys.join(', ')}
                        </p>
                    )}
                    <p className="text-2xs text-gray-300 leading-snug line-clamp-3">{entry.content}</p>
                </div>
            </div>
        </li>
    );
}

function LorebookEntryList({ lorebookId, contextText }) {
    const { data: entries = [], isLoading, isError } = useLorebookEntries(lorebookId);
    const { activated, idle, total } = useMemo(
        () => selectActivatedEntries(entries, contextText),
        [entries, contextText]
    );

    if (isLoading) {
        return (
            <div className="flex items-center gap-2 px-2 py-2 text-xs text-gray-500">
                <Loader2 size={12} className="animate-spin" /> Loading entries…
            </div>
        );
    }
    if (isError) {
        return <p className="px-2 py-2 text-xs text-red-300/80">Could not load entries.</p>;
    }
    if (total === 0) {
        return <p className="px-2 py-2 text-xs text-gray-600">No entries in this lorebook.</p>;
    }

    return (
        <div className="space-y-1.5 pt-1">
            <p className="text-2xs text-gray-500 px-1">
                {activated.length} of {total} {total === 1 ? 'entry' : 'entries'} would be injected now
            </p>
            {activated.map(entry => <EntryRow key={entry.id} entry={entry} />)}
            {idle.length > 0 && (
                <p className="text-2xs text-gray-600 px-1">
                    {idle.length} dormant {idle.length === 1 ? 'entry' : 'entries'} — keys not present in context
                </p>
            )}
        </div>
    );
}

/**
 * One lorebook row: a disclosure that fetches the book's entries and reports
 * how many of them would be injected for the current context.
 *
 * Shared by the chat's own active lorebooks and by the books a character
 * brings with them, so both report the same "N of M" through the same
 * `LorebookEntryList`. A second implementation would be a second answer to
 * "what does the model actually receive", which is the one question this
 * panel exists to answer.
 *
 * `lorebook` may be omitted for a character-attached book whose row is not in
 * the `lorebooks` collection; `name` then supplies the label.
 */
function LorebookRow({ lorebook, lorebookId, name, expanded, onToggle, contextText, onEditLorebook }) {
    const id = lorebook?.id || lorebookId;
    const label = name || lorebook?.name || id;
    return (
        <div className="rounded-lg border border-white/5 bg-gray-800/30">
            <div className="flex items-center gap-1.5 px-2 py-1.5">
                <button
                    type="button"
                    onClick={onToggle}
                    aria-expanded={expanded}
                    className="flex-1 min-w-0 flex items-center gap-1.5 text-left"
                >
                    <ChevronDown size={11} className={clsx('text-gray-500 shrink-0 transition-transform', expanded && 'rotate-180')} aria-hidden="true" />
                    <span className="text-2xs text-gray-200 truncate">{label}</span>
                </button>
                {onEditLorebook && lorebook && (
                    <button
                        type="button"
                        onClick={() => onEditLorebook(lorebook)}
                        title={`Edit ${lorebook.name}`}
                        className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 transition-colors"
                    >
                        <Edit2 size={11} />
                    </button>
                )}
            </div>
            {expanded && (
                <div className="px-2 pb-2">
                    <LorebookEntryList lorebookId={id} contextText={contextText} />
                </div>
            )}
        </div>
    );
}

function CollapsibleGroup({ icon: Icon, title, count, defaultOpen = false, children, testId }) {
    const [open, setOpen] = useState(defaultOpen);
    const contentId = useId();
    const headerId = useId();

    return (
        <div className="rounded-lg border border-white/5 bg-gray-900/30">
            <h4>
                <button
                    type="button"
                    id={headerId}
                    aria-expanded={open}
                    aria-controls={contentId}
                    onClick={() => setOpen(o => !o)}
                    className="w-full flex items-center justify-between gap-2 px-2.5 py-2 text-left hover:bg-white/5 transition-colors"
                >
                    <span className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-widest min-w-0">
                        {Icon && <Icon size={12} className="shrink-0" />}
                        <span className="truncate">{title}</span>
                        <span className="text-2xs text-gray-600 shrink-0">({count})</span>
                    </span>
                    <ChevronDown size={13} className={clsx('text-gray-500 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden="true" />
                </button>
            </h4>
            {open && (
                <div id={contentId} role="region" aria-labelledby={headerId} className="px-2.5 pb-2.5 space-y-1.5" data-testid={testId}>
                    {children}
                </div>
            )}
        </div>
    );
}

/**
 * EntityContextInspector — read-only, progressive overview of everything a
 * chat or story pulls into the model: linked characters, locations, active
 * lorebooks and the lorebook entries that are actually firing right now.
 *
 * Fully controlled by props so Chat and Story can share it; collapsed by
 * default and lazy — lorebook entries are only fetched when a lorebook row
 * is expanded.
 */
export default function EntityContextInspector({
    title = 'Context Inspector',
    subtitle,
    characters = [],
    characterIds = [],
    primaryCharacterId = null,
    lorebooks = [],
    lorebookIds = [],
    // Books a CHARACTER contributes, as `[{ lorebookId, characterName }]`.
    // Separate from `lorebookIds` because they are a different relationship:
    // the chat's own selection versus `Character.lorebook_ids`, the vault
    // books attached to a character that follow them into every conversation.
    // Optional, so a call site that has not wired it up renders exactly as
    // before. Both chat and story panels can compute it from entities they
    // already hold, which is why it lives here rather than on one of them.
    characterLorebookLinks = [],
    locations = [],
    locationIds = [],
    freeformLocation = null,
    contextText = '',
    onEditCharacter,
    onEditLorebook,
    onEditLocation,
    onNavigate: onNavigateProp,
    extraLinks = [],
    emptyHint = 'Link characters, a location, or a lorebook to see what the model receives.',
    defaultOpen = false,
    className = '',
}) {
    const routerNavigate = useNavigate();
    const [open, setOpen] = useState(defaultOpen);
    const contentId = useId();
    const headerId = useId();

    const navigateTo = onNavigateProp || routerNavigate;

    const linkedCharacters = useMemo(() => pickById(characters, characterIds), [characters, characterIds]);
    const linkedLorebooks = useMemo(() => pickById(lorebooks, lorebookIds), [lorebooks, lorebookIds]);
    const linkedLocations = useMemo(() => pickById(locations, locationIds), [locations, locationIds]);
    const [expandedLorebooks, setExpandedLorebooks] = useState({});

    const lorebookNameById = useMemo(() => {
        const map = new Map();
        for (const lb of Array.isArray(lorebooks) ? lorebooks : []) {
            if (lb && lb.id) map.set(lb.id, lb.name);
        }
        return map;
    }, [lorebooks]);

    const characterLorebookGroups = useMemo(
        () => groupByOwner(characterLorebookLinks),
        [characterLorebookLinks]
    );
    const characterLorebookCount = useMemo(
        () => characterLorebookGroups.reduce((n, g) => n + g.entries.length, 0),
        [characterLorebookGroups]
    );

    // A character-only link still feeds the model, so it must keep the panel
    // out of the "Nothing linked yet" state — which is the one string on this
    // panel that is flatly false when it appears.
    const totalLinked =
        linkedCharacters.length + linkedLocations.length + linkedLorebooks.length + characterLorebookCount;

    return (
        <div className={clsx('glass-panel rounded-xl border border-white/5', className)} data-testid="entity-context-inspector">
            <h4>
                <button
                    type="button"
                    id={headerId}
                    aria-expanded={open}
                    aria-controls={contentId}
                    onClick={() => setOpen(o => !o)}
                    className="w-full flex items-center justify-between gap-2 p-4 text-left hover:bg-white/5 transition-colors rounded-xl"
                >
                    <span className="min-w-0">
                        <span className="flex items-center gap-1.5 text-xs font-semibold text-gray-300 uppercase tracking-widest">
                            <PanelRightOpen size={12} className="text-indigo-400" />
                            {title}
                        </span>
                        <span className="block text-2xs text-gray-500 mt-0.5 truncate">
                            {totalLinked === 0
                                ? 'Nothing linked yet'
                                : [
                                    linkedCharacters.length && `${linkedCharacters.length} linked`,
                                    linkedLocations.length && `${linkedLocations.length} location${linkedLocations.length === 1 ? '' : 's'}`,
                                    linkedLorebooks.length && `${linkedLorebooks.length} lorebook${linkedLorebooks.length === 1 ? '' : 's'}`,
                                    characterLorebookCount > 0 && `${characterLorebookCount} from character${characterLorebookCount === 1 ? '' : 's'}`,
                                ].filter(Boolean).join(' · ')}
                        </span>
                    </span>
                    <ChevronDown size={14} className={clsx('text-gray-500 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden="true" />
                </button>
            </h4>

            {open && (
                <div id={contentId} role="region" aria-labelledby={headerId} className="px-3 pb-3 space-y-2">
                    {subtitle && <p className="text-2xs text-gray-600 px-1">{subtitle}</p>}

                    {totalLinked === 0 && (
                        <p className="text-xs text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">
                            {emptyHint}
                        </p>
                    )}

                    {linkedCharacters.length > 0 && (
                        <CollapsibleGroup icon={User} title="Linked Characters" count={linkedCharacters.length} defaultOpen testId="inspector-characters">
                            {linkedCharacters.map(character => (
                                <div key={character.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-gray-800/40 group">
                                    <div className="w-6 h-6 rounded-full bg-gray-700 shrink-0 overflow-hidden flex items-center justify-center">
                                        {character.avatar_path ? (
                                            <img src={getAvatarUrl(character.id)} alt="" className="w-full h-full object-cover" loading="lazy" />
                                        ) : (
                                            <User size={11} className="text-gray-400" />
                                        )}
                                    </div>
                                    <div className="min-w-0 flex-1">
                                        <p className="text-2xs text-gray-200 truncate">{character.name}</p>
                                        {character.description && (
                                            <p className="text-2xs text-gray-500 truncate">{character.description}</p>
                                        )}
                                    </div>
                                    {onEditCharacter && (!primaryCharacterId || primaryCharacterId === character.id) && (
                                        <button
                                            type="button"
                                            onClick={() => onEditCharacter(character)}
                                            title={`Edit ${character.name}`}
                                            className="p-1 rounded text-gray-500 hover:text-indigo-400 hover:bg-white/10 transition-colors"
                                        >
                                            <Edit2 size={11} />
                                        </button>
                                    )}
                                </div>
                            ))}
                        </CollapsibleGroup>
                    )}

                    {(linkedLocations.length > 0 || freeformLocation) && (
                        <CollapsibleGroup icon={MapPin} title="Locations" count={linkedLocations.length} defaultOpen testId="inspector-locations">
                            {linkedLocations.map(location => (
                                <div key={location.id} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-gray-800/40 group">
                                    <div className="min-w-0 flex-1">
                                        <p className="text-2xs text-gray-200 truncate">{location.name}</p>
                                        {(location.atmosphere || location.description) && (
                                            <p className="text-2xs text-gray-500 truncate">{location.atmosphere || location.description}</p>
                                        )}
                                    </div>
                                    {onEditLocation && (
                                        <button
                                            type="button"
                                            onClick={() => onEditLocation(location)}
                                            title={`Edit ${location.name}`}
                                            className="p-1 rounded text-gray-500 hover:text-emerald-400 hover:bg-white/10 transition-colors"
                                        >
                                            <Edit2 size={11} />
                                        </button>
                                    )}
                                </div>
                            ))}
                            {linkedLocations.length === 0 && freeformLocation && (
                                <p className="px-2 py-1.5 text-2xs text-gray-400 bg-gray-800/40 rounded-lg truncate">
                                    {freeformLocation}
                                    <span className="text-2xs text-gray-600 ml-1.5">free-text, not linked to a Location</span>
                                </p>
                            )}
                        </CollapsibleGroup>
                    )}

                    {linkedLorebooks.length > 0 && (
                        <CollapsibleGroup icon={BookOpen} title="Active Lorebooks" count={linkedLorebooks.length} defaultOpen testId="inspector-lorebooks">
                            {linkedLorebooks.map(lorebook => (
                                <LorebookRow
                                    key={lorebook.id}
                                    lorebook={lorebook}
                                    expanded={!!expandedLorebooks[lorebook.id]}
                                    onToggle={() => setExpandedLorebooks(prev => ({ ...prev, [lorebook.id]: !prev[lorebook.id] }))}
                                    contextText={contextText}
                                    onEditLorebook={onEditLorebook}
                                />
                            ))}
                        </CollapsibleGroup>
                    )}

                    {characterLorebookCount > 0 && (
                        <CollapsibleGroup
                            icon={BookOpen}
                            title="Character Lorebooks"
                            count={characterLorebookCount}
                            defaultOpen
                            testId="inspector-character-lorebooks"
                        >
                            <p className="text-2xs text-gray-500 px-1">
                                Attached to the character, so they are injected in every chat and story they are in.
                            </p>
                            {characterLorebookGroups.map(group => (
                                <div key={group.owner || 'unattributed'} className="space-y-1.5">
                                    {group.owner && (
                                        <p className="text-2xs font-semibold uppercase tracking-wider text-gray-400 px-1 pt-1">
                                            via {group.owner}
                                        </p>
                                    )}
                                    {group.entries.map(link => (
                                        <LorebookRow
                                            key={`${link.lorebookId}-${group.owner}`}
                                            lorebookId={link.lorebookId}
                                            name={lorebookNameById.get(link.lorebookId) || link.lorebookId}
                                            expanded={!!expandedLorebooks[`char:${link.lorebookId}`]}
                                            onToggle={() =>
                                                setExpandedLorebooks(prev => ({
                                                    ...prev,
                                                    [`char:${link.lorebookId}`]: !prev[`char:${link.lorebookId}`],
                                                }))
                                            }
                                            contextText={contextText}
                                            onEditLorebook={onEditLorebook}
                                        />
                                    ))}
                                </div>
                            ))}
                        </CollapsibleGroup>
                    )}

                    <div className="flex flex-wrap gap-1.5 pt-1" data-testid="inspector-quick-links">
                        {QUICK_LINKS.map(({ to, label, icon: LinkIcon }) => (
                            <button
                                key={to}
                                type="button"
                                onClick={() => navigateTo(to)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-2xs text-gray-400 hover:text-indigo-300 bg-gray-800/40 hover:bg-gray-800 rounded-md border border-white/5 transition-colors"
                            >
                                <LinkIcon size={10} />
                                {label}
                            </button>
                        ))}
                        {extraLinks.map(link => (
                            <button
                                key={link.to}
                                type="button"
                                onClick={() => navigateTo(link.to)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-2xs text-gray-400 hover:text-indigo-300 bg-gray-800/40 hover:bg-gray-800 rounded-md border border-white/5 transition-colors"
                            >
                                {link.icon ? <link.icon size={10} /> : <ExternalLink size={10} />}
                                {link.label}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
