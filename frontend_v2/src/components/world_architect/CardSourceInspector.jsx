import { useState } from 'react';
import clsx from 'clsx';
import {
    ChevronDown, ChevronRight, Copy, Check, User, Sparkles, BookOpen,
    MessageSquare, Layers, Tag, Shield, Compass, FileText, ExternalLink
} from 'lucide-react';
import { copyToClipboard } from '../../utils/clipboard';

export default function CardSourceInspector({ sourceCard, onCopyField, className = '' }) {
    const [copiedKey, setCopiedKey] = useState(null);
    const [openSections, setOpenSections] = useState({
        description: true,
        personality: true,
        scenario: true,
        first_mes: true,
        alternate_greetings: false,
        character_book: false,
        system_prompt: false,
        creator_notes: false,
    });
    const [searchFilter, setSearchFilter] = useState('');

    if (!sourceCard) {
        return (
            <div className={clsx("glass-panel rounded-2xl p-5 border border-white/10 text-center text-gray-400 text-xs", className)}>
                <User size={32} className="mx-auto mb-2 text-gray-600 opacity-60" />
                <p>No card data loaded. Upload a card to inspect original fields.</p>
            </div>
        );
    }

    const toggleSection = (key) => {
        setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const handleCopy = async (key, text) => {
        if (!text) return;
        await copyToClipboard(text);
        setCopiedKey(key);
        if (onCopyField) onCopyField(key, text);
        setTimeout(() => setCopiedKey(null), 1800);
    };

    const {
        name = 'Unknown Character',
        card_spec = 'chara_card_v2',
        card_spec_version = '2.0',
        creator = '',
        character_version = '',
        description = '',
        personality = '',
        scenario = '',
        first_mes = '',
        alternate_greetings = [],
        system_prompt = '',
        creator_notes = '',
        tags = [],
        character_book = null,
        avatar_base64 = null,
    } = sourceCard;

    const loreEntriesCount = character_book?.entries?.length || 0;

    return (
        <div className={clsx("glass-panel rounded-2xl border border-white/10 flex flex-col h-full overflow-hidden bg-gray-950/80 shadow-2xl", className)}>
            {/* Header / Avatar Profile */}
            <div className="p-4 border-b border-white/10 bg-gradient-to-b from-gray-900/90 to-transparent flex items-start gap-3.5">
                {avatar_base64 ? (
                    <img
                        src={avatar_base64.startsWith('data:') ? avatar_base64 : `data:image/png;base64,${avatar_base64}`}
                        alt={name}
                        className="w-16 h-16 rounded-xl object-cover object-top border border-emerald-500/40 shadow-md shrink-0 bg-gray-900"
                    />
                ) : (
                    <div className="w-16 h-16 rounded-xl bg-gray-900 border border-white/10 flex items-center justify-center shrink-0">
                        <User size={28} className="text-gray-500" />
                    </div>
                )}

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <h2 className="text-sm font-bold text-white truncate" title={name}>{name}</h2>
                        <span className="px-1.5 py-0.5 rounded text-3xs font-mono font-bold uppercase bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                            {card_spec} {card_spec_version ? `v${card_spec_version}` : ''}
                        </span>
                        {character_version && (
                            <span className="px-1.5 py-0.5 rounded text-3xs font-mono text-gray-400 bg-gray-900 border border-white/5">
                                v{character_version}
                            </span>
                        )}
                    </div>

                    {creator && (
                        <p className="text-2xs text-gray-400 mt-0.5 truncate">
                            Author: <span className="text-gray-300 font-medium">{creator}</span>
                        </p>
                    )}

                    {tags && tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                            {tags.slice(0, 4).map((tag, idx) => (
                                <span key={idx} className="px-1.5 py-0.2 rounded text-3xs bg-white/5 text-gray-300 border border-white/5">
                                    #{tag}
                                </span>
                            ))}
                            {tags.length > 4 && (
                                <span className="text-3xs text-gray-500">+{tags.length - 4} more</span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Subheader / Search Filter */}
            <div className="px-4 py-2 border-b border-white/5 bg-gray-900/40 flex items-center justify-between gap-2 text-2xs">
                <span className="text-gray-400 font-semibold uppercase tracking-wider text-3xs">
                    Original Card Provenance
                </span>
                <input
                    type="text"
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                    placeholder="Filter source text..."
                    className="bg-gray-900/80 border border-white/10 rounded-lg px-2 py-0.5 text-2xs text-gray-200 placeholder-gray-500 w-36 focus:outline-none focus:border-emerald-500/50"
                />
            </div>

            {/* Scrollable Accordions */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2.5 custom-scrollbar text-xs">
                {/* 1. Description */}
                <AccordionSection
                    title="Description"
                    count={description.length}
                    countLabel="chars"
                    isOpen={openSections.description}
                    onToggle={() => toggleSection('description')}
                    onCopy={() => handleCopy('description', description)}
                    isCopied={copiedKey === 'description'}
                >
                    <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 font-mono text-2xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
                        {description || <span className="text-gray-600 italic">No description provided</span>}
                    </div>
                </AccordionSection>

                {/* 2. Personality */}
                <AccordionSection
                    title="Personality"
                    count={personality.length}
                    countLabel="chars"
                    isOpen={openSections.personality}
                    onToggle={() => toggleSection('personality')}
                    onCopy={() => handleCopy('personality', personality)}
                    isCopied={copiedKey === 'personality'}
                >
                    <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 font-mono text-2xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto">
                        {personality || <span className="text-gray-600 italic">No personality text provided</span>}
                    </div>
                </AccordionSection>

                {/* 3. Scenario */}
                <AccordionSection
                    title="Scenario"
                    count={scenario.length}
                    countLabel="chars"
                    isOpen={openSections.scenario}
                    onToggle={() => toggleSection('scenario')}
                    onCopy={() => handleCopy('scenario', scenario)}
                    isCopied={copiedKey === 'scenario'}
                >
                    <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 font-mono text-2xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto">
                        {scenario || <span className="text-gray-600 italic">No scenario text provided</span>}
                    </div>
                </AccordionSection>

                {/* 4. First Message */}
                <AccordionSection
                    title="First Message (Default Opening)"
                    count={first_mes.length}
                    countLabel="chars"
                    isOpen={openSections.first_mes}
                    onToggle={() => toggleSection('first_mes')}
                    onCopy={() => handleCopy('first_mes', first_mes)}
                    isCopied={copiedKey === 'first_mes'}
                >
                    <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 text-2xs text-gray-200 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto border-l-2 border-l-emerald-500">
                        {first_mes || <span className="text-gray-600 italic">No first message provided</span>}
                    </div>
                </AccordionSection>

                {/* 5. Alternate Greetings */}
                {alternate_greetings && alternate_greetings.length > 0 && (
                    <AccordionSection
                        title={`Alternate Greetings (${alternate_greetings.length})`}
                        badge={`${alternate_greetings.length} scenarios`}
                        isOpen={openSections.alternate_greetings}
                        onToggle={() => toggleSection('alternate_greetings')}
                        onCopy={() => handleCopy('alternate_greetings', alternate_greetings.join('\n---\n'))}
                        isCopied={copiedKey === 'alternate_greetings'}
                    >
                        <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                            {alternate_greetings.map((alt, idx) => (
                                <div key={idx} className="p-2 rounded-lg bg-gray-900/80 border border-white/5 space-y-1">
                                    <div className="flex items-center justify-between text-3xs text-gray-400">
                                        <span className="font-bold text-emerald-400">Greeting #{idx + 1}</span>
                                        <button
                                            type="button"
                                            onClick={() => handleCopy(`alt_${idx}`, alt)}
                                            className="hover:text-white flex items-center gap-1"
                                        >
                                            {copiedKey === `alt_${idx}` ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
                                            <span>Copy</span>
                                        </button>
                                    </div>
                                    <p className="text-3xs text-gray-300 whitespace-pre-wrap line-clamp-4 leading-normal font-mono">
                                        {alt}
                                    </p>
                                </div>
                            ))}
                        </div>
                    </AccordionSection>
                )}

                {/* 6. Embedded Lorebook */}
                {loreEntriesCount > 0 && (
                    <AccordionSection
                        title={`Embedded Lorebook (${loreEntriesCount})`}
                        badge={`${loreEntriesCount} entries`}
                        isOpen={openSections.character_book}
                        onToggle={() => toggleSection('character_book')}
                        onCopy={() => handleCopy('lorebook', JSON.stringify(character_book, null, 2))}
                        isCopied={copiedKey === 'lorebook'}
                    >
                        <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                            {character_book.entries.slice(0, 15).map((entry, idx) => (
                                <div key={idx} className="p-2 rounded-lg bg-gray-900/70 border border-white/5 space-y-1">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                        {(entry.keys || []).map((k, kidx) => (
                                            <span key={kidx} className="px-1 py-0.2 rounded text-3xs font-mono bg-purple-500/20 text-purple-300">
                                                {k}
                                            </span>
                                        ))}
                                    </div>
                                    <p className="text-3xs text-gray-300 line-clamp-3 font-mono leading-normal">
                                        {entry.content}
                                    </p>
                                </div>
                            ))}
                            {loreEntriesCount > 15 && (
                                <div className="text-3xs text-center text-gray-500 italic py-1">
                                    +{loreEntriesCount - 15} more lorebook entries embedded
                                </div>
                            )}
                        </div>
                    </AccordionSection>
                )}

                {/* 7. System Prompt / Instructions */}
                {system_prompt && (
                    <AccordionSection
                        title="System Prompt"
                        count={system_prompt.length}
                        countLabel="chars"
                        isOpen={openSections.system_prompt}
                        onToggle={() => toggleSection('system_prompt')}
                        onCopy={() => handleCopy('system_prompt', system_prompt)}
                        isCopied={copiedKey === 'system_prompt'}
                    >
                        <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 font-mono text-2xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto">
                            {system_prompt}
                        </div>
                    </AccordionSection>
                )}

                {/* 8. Creator Notes */}
                {creator_notes && (
                    <AccordionSection
                        title="Creator Notes"
                        count={creator_notes.length}
                        countLabel="chars"
                        isOpen={openSections.creator_notes}
                        onToggle={() => toggleSection('creator_notes')}
                        onCopy={() => handleCopy('creator_notes', creator_notes)}
                        isCopied={copiedKey === 'creator_notes'}
                    >
                        <div className="p-2.5 rounded-xl bg-gray-900/60 border border-white/5 font-mono text-2xs text-gray-300 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto">
                            {creator_notes}
                        </div>
                    </AccordionSection>
                )}
            </div>
        </div>
    );
}

function AccordionSection({
    title,
    count,
    countLabel = '',
    badge,
    isOpen,
    onToggle,
    onCopy,
    isCopied,
    children
}) {
    return (
        <div className="rounded-xl border border-white/5 bg-gray-900/40 overflow-hidden transition-colors hover:border-white/10">
            <div className="flex items-center justify-between p-2.5 cursor-pointer select-none" onClick={onToggle}>
                <div className="flex items-center gap-2 min-w-0">
                    {isOpen ? <ChevronDown size={14} className="text-gray-400 shrink-0" /> : <ChevronRight size={14} className="text-gray-500 shrink-0" />}
                    <span className="text-xs font-semibold text-gray-200 truncate">{title}</span>
                    {badge ? (
                        <span className="px-1.5 py-0.2 rounded text-3xs font-mono font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/20">
                            {badge}
                        </span>
                    ) : count !== undefined && count > 0 ? (
                        <span className="text-3xs font-mono text-gray-500">
                            ({count} {countLabel})
                        </span>
                    ) : null}
                </div>

                <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <button
                        type="button"
                        onClick={onCopy}
                        title="Copy content"
                        className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                    >
                        {isCopied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                    </button>
                </div>
            </div>

            {isOpen && <div className="px-2.5 pb-2.5 pt-0.5">{children}</div>}
        </div>
    );
}
