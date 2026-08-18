import { useState, useMemo } from 'react';
import { Search, Plus, Download, Upload, Star, FolderOpen } from 'lucide-react';
import {
    usePrompts,
    usePromptCategories,
    useDeletePrompt,
    useUpdatePrompt,
    useIncrementPromptUsage,
    useImportPrompts
} from '../hooks/usePrompts';
import promptsApi from '../api/promptsApi';
import PromptCard from '../components/generator/PromptCard';
import PromptForm from '../components/generator/PromptForm';
import toast from 'react-hot-toast';
import { useConfirmation } from '../store/confirmationStore';

export default function Prompts() {
    const { data: prompts = [], isLoading } = usePrompts();
    const { data: categories = ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom'] } = usePromptCategories();

    const deletePromptMutation = useDeletePrompt();
    const updatePromptMutation = useUpdatePrompt();
    const incrementPromptUsageMutation = useIncrementPromptUsage();
    const importPromptsMutation = useImportPrompts();

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('All');
    const [showAddForm, setShowAddForm] = useState(false);
    const [editingPrompt, setEditingPrompt] = useState(null);
    const [isExporting, setIsExporting] = useState(false);

    const confirm = useConfirmation();

    const displayedPrompts = useMemo(() => {
        let filtered = prompts;
        if (selectedCategory !== 'All') {
            filtered = prompts.filter(p => p.category === selectedCategory);
        }
        if (searchQuery.trim()) {
            const q = searchQuery.toLowerCase();
            filtered = filtered.filter(p =>
                p.name.toLowerCase().includes(q) ||
                p.text.toLowerCase().includes(q) ||
                (p.category || '').toLowerCase().includes(q)
            );
        }
        return filtered;
    }, [prompts, selectedCategory, searchQuery]);

    const handleUsePrompt = async (prompt) => {
        await incrementPromptUsageMutation.mutateAsync(prompt.id);
        navigator.clipboard.writeText(prompt.text).then(() => {
            toast.success(`Prompt copied to clipboard`, { icon: '📋' });
        }).catch(() => {
            toast.success(`Prompt "${prompt.name}" selected`, { icon: '✨' });
        });
    };

    const handleDelete = async (prompt) => {
        const ok = await confirm({
            title: 'Delete prompt',
            description: `Remove "${prompt.name}" from your library?`,
            confirmText: 'Delete',
            tone: 'danger',
        });
        if (!ok) return;
        try {
            await deletePromptMutation.mutateAsync(prompt.id);
            toast.success('Prompt deleted');
        } catch {
            toast.error('Failed to delete prompt');
        }
    };

    const handleToggleFavorite = async (prompt) => {
        try {
            await updatePromptMutation.mutateAsync({ id: prompt.id, favorite: !prompt.favorite });
        } catch {
            toast.error('Failed to update prompt');
        }
    };

    const handleExport = async () => {
        if (prompts.length === 0) {
            toast.error('No prompts to export');
            return;
        }
        setIsExporting(true);
        try {
            const { prompts: exportData } = await promptsApi.exportPrompts();
            const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `prompt-library-${Date.now()}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            toast.success('Exported prompt library', { icon: '📥' });
        } catch {
            toast.error('Failed to export prompts');
        } finally {
            setIsExporting(false);
        }
    };

    const handleImport = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = 'application/json';
        input.onchange = async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                const result = await importPromptsMutation.mutateAsync(data);
                toast.success(`Imported ${result.count} prompts`, { icon: '📤' });
            } catch {
                toast.error('Failed to import prompts');
            }
        };
        input.click();
    };

    return (
        <div className="max-w-6xl mx-auto p-6 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">Prompt Library</h1>
                    <p className="text-sm text-gray-400 mt-1">
                        {prompts.length} saved prompt{prompts.length !== 1 ? 's' : ''}
                    </p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handleImport}
                        className="flex items-center gap-2 px-3 py-2 bg-gray-800 text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-700 transition-colors"
                    >
                        <Upload size={14} /> Import
                    </button>
                    <button
                        onClick={handleExport}
                        disabled={prompts.length === 0 || isExporting}
                        className="flex items-center gap-2 px-3 py-2 bg-gray-800 text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-700 disabled:opacity-50 transition-colors"
                    >
                        <Download size={14} /> Export
                    </button>
                    <button
                        onClick={() => { setEditingPrompt(null); setShowAddForm(true); }}
                        className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-500 transition-colors"
                    >
                        <Plus size={14} /> New Prompt
                    </button>
                </div>
            </div>

            <div className="flex gap-3">
                <div className="flex-1 relative">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search prompts..."
                        className="w-full pl-9 pr-4 py-2 bg-gray-800/60 border border-white/10 rounded-lg text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
                <select
                    value={selectedCategory}
                    onChange={(e) => setSelectedCategory(e.target.value)}
                    className="px-3 py-2 bg-gray-800/60 border border-white/10 rounded-lg text-sm text-gray-200 focus:outline-none focus:border-blue-500/50"
                >
                    {categories.map(cat => (
                        <option key={cat} value={cat}>{cat}</option>
                    ))}
                </select>
            </div>

            {isLoading && prompts.length === 0 ? (
                <div className="text-center py-12 text-gray-500">Loading prompt library...</div>
            ) : displayedPrompts.length === 0 ? (
                <div className="text-center py-12">
                    <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
                    <p className="text-lg mb-2">No prompts found</p>
                    <p className="text-sm text-gray-400">
                        {prompts.length === 0
                            ? 'Start by adding your first prompt!'
                            : 'Try adjusting your search or filters'}
                    </p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {displayedPrompts.map(prompt => (
                        <PromptCard
                            key={prompt.id}
                            prompt={prompt}
                            onUse={handleUsePrompt}
                            onEdit={(p) => { setEditingPrompt(p); setShowAddForm(true); }}
                            onDelete={handleDelete}
                            onToggleFavorite={handleToggleFavorite}
                        />
                    ))}
                </div>
            )}

            {showAddForm && (
                <PromptForm
                    prompt={editingPrompt}
                    onClose={() => { setShowAddForm(false); setEditingPrompt(null); }}
                    onSave={() => { setShowAddForm(false); setEditingPrompt(null); }}
                />
            )}
        </div>
    );
}
