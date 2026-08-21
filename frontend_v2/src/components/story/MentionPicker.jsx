import React, { useState, useEffect, useRef } from 'react';
import getCaretCoordinates from 'textarea-caret';
import { Users, BookOpen } from 'lucide-react';
import { useCharacters, useLorebooks } from '../../hooks/useWorldVault';

export default function MentionPicker({ textareaRef, editorContent, onSelect }) {
    const { data: characters = [] } = useCharacters();
    const { data: lorebooks = [] } = useLorebooks();
    
    const [pickerState, setPickerState] = useState({
        isOpen: false,
        x: 0,
        y: 0,
        query: '',
        startIndex: -1
    });
    
    const [selectedIndex, setSelectedIndex] = useState(0);

    const filteredItems = React.useMemo(() => {
        if (!pickerState.isOpen) return [];
        const query = pickerState.query.toLowerCase();
        
        const chars = characters
            .filter(c => c.name.toLowerCase().includes(query))
            .map(c => ({ ...c, _type: 'character', _icon: Users }));
            
        const books = lorebooks
            .filter(l => l.name.toLowerCase().includes(query))
            .map(l => ({ ...l, _type: 'lorebook', _icon: BookOpen }));
            
        return [...chars, ...books].slice(0, 10); // show top 10
    }, [characters, lorebooks, pickerState.query, pickerState.isOpen]);

    useEffect(() => {
        const textarea = textareaRef.current;
        if (!textarea) return;

        const handleInput = (e) => {
            const cursor = textarea.selectionStart;
            const textBefore = editorContent.slice(0, cursor);
            
            // Match @ followed by word characters up to current cursor
            const match = textBefore.match(/@([\w\s]*)$/);
            
            if (match) {
                const caret = getCaretCoordinates(textarea, cursor);
                // Adjust for scroll and parent offset if needed
                setPickerState({
                    isOpen: true,
                    x: caret.left,
                    y: caret.top + caret.height,
                    query: match[1],
                    startIndex: match.index
                });
                setSelectedIndex(0);
            } else {
                setPickerState(s => ({ ...s, isOpen: false }));
            }
        };

        const handleKeyDown = (e) => {
            if (!pickerState.isOpen) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSelectedIndex(i => (i + 1) % (filteredItems.length || 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSelectedIndex(i => (i - 1 + filteredItems.length) % (filteredItems.length || 1));
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                if (filteredItems.length > 0) {
                    e.preventDefault();
                    const item = filteredItems[selectedIndex];
                    onSelect(item, pickerState.startIndex, textarea.selectionStart);
                    setPickerState(s => ({ ...s, isOpen: false }));
                }
            } else if (e.key === 'Escape') {
                setPickerState(s => ({ ...s, isOpen: false }));
            }
        };

        textarea.addEventListener('input', handleInput);
        textarea.addEventListener('keydown', handleKeyDown);
        
        // Handle clicks outside
        const handleClick = () => setPickerState(s => ({ ...s, isOpen: false }));
        document.addEventListener('click', handleClick);

        return () => {
            textarea.removeEventListener('input', handleInput);
            textarea.removeEventListener('keydown', handleKeyDown);
            document.removeEventListener('click', handleClick);
        };
    }, [textareaRef, editorContent, pickerState, filteredItems, selectedIndex, onSelect]);

    if (!pickerState.isOpen || filteredItems.length === 0) return null;

    return (
        <div 
            className="absolute z-50 bg-gray-900 border border-white/10 rounded-lg shadow-xl overflow-hidden min-w-[200px]"
            style={{ 
                left: pickerState.x, 
                top: pickerState.y + 10 // small offset below text
            }}
        >
            <div className="px-3 py-1.5 bg-gray-800/50 border-b border-white/5 text-[10px] text-gray-500 uppercase tracking-wider font-semibold">
                Link Entity
            </div>
            <div className="max-h-48 overflow-y-auto">
                {filteredItems.map((item, idx) => {
                    const Icon = item._icon;
                    const isSelected = idx === selectedIndex;
                    return (
                        <div
                            key={item.id}
                            className={`flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors ${
                                isSelected ? 'bg-blue-500/20 text-white' : 'text-gray-300 hover:bg-white/5'
                            }`}
                            onClick={() => {
                                onSelect(item, pickerState.startIndex, textareaRef.current.selectionStart);
                                setPickerState(s => ({ ...s, isOpen: false }));
                            }}
                        >
                            <Icon size={14} className={isSelected ? 'text-blue-400' : 'text-gray-500'} />
                            <span className="text-sm">{item.name}</span>
                            <span className="text-[10px] text-gray-500 ml-auto capitalize">{item._type}</span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
