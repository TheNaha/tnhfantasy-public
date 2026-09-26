import { useState, useEffect } from 'react';
import clsx from 'clsx';
import { Brain } from 'lucide-react';

const SOURCE_DOT = {
    override:    'bg-orange-400',
    character:   'bg-blue-400',
    char_append: 'bg-sky-400',
    chat_append: 'bg-teal-400',
    config:      'bg-emerald-400',
    lorebook:    'bg-violet-400',
    world_state: 'bg-amber-400',
};

function SectionPreview({ sec }) {
    const [expanded, setExpanded] = useState(false);
    return (
        <div className="rounded-lg bg-gray-900/50 border border-white/5 overflow-hidden">
            <button
                type="button"
                onClick={() => setExpanded(v => !v)}
                className="w-full text-left text-2xs font-semibold text-gray-500 px-2.5 py-1.5 bg-gray-800/30 uppercase tracking-wider border-b border-white/5 flex items-center gap-1.5 hover:bg-gray-800/60 transition-colors"
            >
                <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', SOURCE_DOT[sec.source] ?? 'bg-gray-500')} />
                <span className="flex-1 truncate">{sec.label}</span>
                <span className="text-gray-600 ml-1">{expanded ? '▲' : '▼'}</span>
            </button>
            {expanded && (
                <div className="max-h-40 overflow-y-auto px-2.5 py-2 text-xs leading-relaxed text-gray-300 whitespace-pre-wrap custom-scrollbar">
                    {sec.content || '—'}
                </div>
            )}
        </div>
    );
}

function SystemPromptPanel({ activeChat, linkedCharacter, systemPromptData, onChatUpdate, onCharacterPatch }) {
    const [activeTab, setActiveTab] = useState('preview'); // 'preview' | 'override' | 'append'

    // Controlled textarea values — reset when active chat changes
    const chatKey = activeChat?.id || 'none';
    const [overrideVal, setOverrideVal] = useState(activeChat?.system_prompt_override || '');
    const [chatAppendVal, setChatAppendVal] = useState(activeChat?.append_system_prompt || '');
    const [charAppendVal, setCharAppendVal] = useState(linkedCharacter?.append_system_prompt || '');

    useEffect(() => {
        setOverrideVal(activeChat?.system_prompt_override || '');
        setChatAppendVal(activeChat?.append_system_prompt || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [chatKey]);

    useEffect(() => {
        setCharAppendVal(linkedCharacter?.append_system_prompt || '');
    }, [linkedCharacter?.id, linkedCharacter?.append_system_prompt]);

    const hasOverride = Boolean(activeChat?.system_prompt_override);
    const hasChatAppend = Boolean(activeChat?.append_system_prompt);
    const hasCharAppend = Boolean(linkedCharacter?.append_system_prompt);

    const saveOverride = () => {
        const val = overrideVal.trim() || null;
        if (val !== (activeChat?.system_prompt_override || null)) {
            onChatUpdate({ system_prompt_override: val });
        }
    };
    const saveChatAppend = () => {
        const val = chatAppendVal.trim() || null;
        if (val !== (activeChat?.append_system_prompt || null)) {
            onChatUpdate({ append_system_prompt: val });
        }
    };
    const saveCharAppend = () => {
        if (!linkedCharacter) return;
        const val = charAppendVal.trim() || null;
        if (val !== (linkedCharacter?.append_system_prompt || null)) {
            onCharacterPatch({ append_system_prompt: val });
        }
    };

    const TABS = [
        { id: 'preview', label: 'Preview' },
        { id: 'override', label: 'Chat Prompt', badge: hasOverride },
        { id: 'append',  label: 'Character Extra',   badge: hasChatAppend || hasCharAppend },
    ];

    return (
        <div className="glass-panel p-4 rounded-xl border border-white/5 space-y-3">
            {/* Header */}
            <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                    <Brain size={12} /> System Prompt
                </h4>
                {hasOverride && (
                    <button
                        onClick={() => { setOverrideVal(''); onChatUpdate({ system_prompt_override: null }); }}
                        className="text-2xs text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                    >
                        Clear override
                    </button>
                )}
            </div>

            {/* Tab bar */}
            <div className="flex gap-1 p-1 bg-black/30 rounded-lg">
                {TABS.map(t => (
                    <button
                        key={t.id}
                        type="button"
                        onClick={() => setActiveTab(t.id)}
                        className={clsx(
                            'flex-1 py-1 text-xs font-bold uppercase tracking-wider rounded transition-all relative',
                            activeTab === t.id
                                ? 'bg-gray-700 text-white shadow'
                                : 'text-gray-500 hover:text-gray-300'
                        )}
                    >
                        {t.label}
                        {t.badge && (
                            <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-teal-400" />
                        )}
                    </button>
                ))}
            </div>

            {/* Preview tab — collapsible section list */}
            {activeTab === 'preview' && (
                <div className="space-y-1.5">
                    {systemPromptData?.sections?.length ? (
                        systemPromptData.sections.map((sec, i) => (
                            <SectionPreview key={i} sec={sec} />
                        ))
                    ) : (
                        <p className="text-xs text-gray-600 text-center py-3">
                            {activeChat ? 'No system prompt sections assembled yet.' : 'Select a chat to preview.'}
                        </p>
                    )}
                    {systemPromptData && (
                        <p className="text-2xs text-gray-600 pt-1 text-right">
                            ~{systemPromptData.context_tokens ?? '?'} tokens · {systemPromptData.message_count ?? 0} messages in context
                        </p>
                    )}
                </div>
            )}

            {activeTab === 'override' && (
                <div className="space-y-2">
                    <p className="text-xs text-gray-500 leading-relaxed">
                        <span className="text-orange-400 font-semibold">Chat System Prompt</span> is applied only to this chat.
                        It is appended after the character's core instructions.
                    </p>
                    <textarea
                        value={overrideVal}
                        onChange={e => setOverrideVal(e.target.value)}
                        onBlur={saveOverride}
                        placeholder="Override everything — write a complete system prompt…"
                        rows={5}
                        className="w-full bg-gray-800/60 border border-orange-500/20 focus:border-orange-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[80px]"
                    />
                    <button
                        type="button"
                        onClick={saveOverride}
                        className="w-full py-1.5 text-xs font-bold uppercase tracking-wider rounded-lg bg-orange-500/10 text-orange-300 hover:bg-orange-500/20 border border-orange-500/20 transition-colors"
                    >
                        Save override
                    </button>
                </div>
            )}

            {/* Append tab — non-destructive extra instructions at two levels */}
            {activeTab === 'append' && (
                <div className="space-y-4">
                    {/* Per-chat append */}
                    <div className="space-y-2">
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-teal-400 shrink-0" />
                            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                                This chat
                            </p>
                            {hasChatAppend && (
                                <button
                                    type="button"
                                    onClick={() => { setChatAppendVal(''); onChatUpdate({ append_system_prompt: null }); }}
                                    className="ml-auto text-2xs text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                                >
                                    Clear
                                </button>
                            )}
                        </div>
                        <p className="text-xs text-gray-600 leading-relaxed">
                            Appended after the character card, before global instructions. Only affects this chat.
                        </p>
                        <textarea
                            value={chatAppendVal}
                            onChange={e => setChatAppendVal(e.target.value)}
                            onBlur={saveChatAppend}
                            placeholder="e.g. Always speak in riddles. Today is {user}'s birthday…"
                            rows={3}
                            className="w-full bg-gray-800/60 border border-teal-500/20 focus:border-teal-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[60px]"
                        />
                        <button
                            type="button"
                            onClick={saveChatAppend}
                            className="w-full py-1.5 text-xs font-bold uppercase tracking-wider rounded-lg bg-teal-500/10 text-teal-300 hover:bg-teal-500/20 border border-teal-500/20 transition-colors"
                        >
                            Save chat append
                        </button>
                    </div>

                    {/* Per-character append */}
                    <div className="space-y-2 pt-2 border-t border-white/5">
                        <div className="flex items-center gap-1.5">
                            <span className="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0" />
                            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                                {linkedCharacter ? linkedCharacter.name : 'Character'} (all chats)
                            </p>
                            {hasCharAppend && (
                                <button
                                    type="button"
                                    onClick={() => { setCharAppendVal(''); onCharacterPatch({ append_system_prompt: null }); }}
                                    className="ml-auto text-2xs text-red-400 hover:text-red-300 px-1.5 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 transition-colors"
                                >
                                    Clear
                                </button>
                            )}
                        </div>
                        {linkedCharacter ? (
                            <>
                                <p className="text-xs text-gray-600 leading-relaxed">
                                    Appended after the character card in <em>every</em> chat that uses {linkedCharacter.name}. Use this for permanent personality tweaks.
                                </p>
                                <textarea
                                    value={charAppendVal}
                                    onChange={e => setCharAppendVal(e.target.value)}
                                    onBlur={saveCharAppend}
                                    placeholder={`e.g. ${linkedCharacter.name} always ends sentences with a soft laugh…`}
                                    rows={3}
                                    className="w-full bg-gray-800/60 border border-sky-500/20 focus:border-sky-500/50 text-xs rounded-lg px-3 py-2 text-gray-300 placeholder-gray-600 focus:outline-none resize-y min-h-[60px]"
                                />
                                <button
                                    type="button"
                                    onClick={saveCharAppend}
                                    className="w-full py-1.5 text-xs font-bold uppercase tracking-wider rounded-lg bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 border border-sky-500/20 transition-colors"
                                >
                                    Save character append
                                </button>
                            </>
                        ) : (
                            <p className="text-xs text-gray-600 text-center py-2 border border-dashed border-gray-700/50 rounded-lg">
                                Assign a character to edit their append block.
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

export default SystemPromptPanel;
