import { useMemo, useState } from 'react';
import { X, Search, Plus, Download, Upload, Star, TrendingUp, FolderOpen } from 'lucide-react';
import {
    usePrompts,
    usePromptCategories,
    useDeletePrompt,
    useUpdatePrompt,
    useIncrementPromptUsage,
    useImportPrompts
} from '../../hooks/usePrompts';
import promptsApi from '../../api/promptsApi';
import PromptCard from './PromptCard';
import PromptForm from './PromptForm';
import toast from 'react-hot-toast';
import { useConfirmation } from '../../store/confirmationStore';

/**
 * Prompt Library Modal Component
 * Browse, search, and manage saved prompts
 */
export const PromptLibrary = ({ isOpen, onClose, onSelectPrompt }) => {
    const { data: prompts = [], isLoading } = usePrompts();
    const { data: categories = ['All', 'Portrait', 'Landscape', 'Anime', 'Abstract', 'Realistic', 'Custom'] } = usePromptCategories();

    const deletePromptMutation = useDeletePrompt();
    const updatePromptMutation = useUpdatePrompt();
    const incrementPromptUsageMutation = useIncrementPromptUsage();
    const importPromptsMutation = useImportPrompts();

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('All');
    const [view, setView] = useState('all'); // 'all', 'favorites', 'popular'
    const [editingPrompt, setEditingPrompt] = useState(null);
    const [showAddForm, setShowAddForm] = useState(false);
    const [isExporting, setIsExporting] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const { confirm } = useConfirmation();

    // Filter and search prompts
    const displayedPrompts = useMemo(() => {
        let filtered = prompts;

        // View filter
        if (view === 'favorites') {
            filtered = prompts.filter(p => p.favorite);
        } else if (view === 'popular') {
            filtered = [...prompts]
                .sort((a, b) => (b.usage_count || 0) - (a.usage_count || 0))
                .slice(0, 20);
        }

        // Category filter
        if (selectedCategory !== 'All') {
            filtered = filtered.filter(p => p.category === selectedCategory);
        }

        // Search filter
        if (searchQuery.trim()) {
            const lowerQuery = searchQuery.toLowerCase();
            filtered = filtered.filter(p =>
                p.name.toLowerCase().includes(lowerQuery) ||
                p.text.toLowerCase().includes(lowerQuery) ||
                p.description?.toLowerCase().includes(lowerQuery) ||
                p.tags?.some(tag => tag.toLowerCase().includes(lowerQuery))
            );
        }

        return filtered;
    }, [prompts, view, selectedCategory, searchQuery]);

    // Handle using a prompt
    const handleUsePrompt = (prompt) => {
        void incrementPromptUsageMutation.mutate(prompt.id);
        onSelectPrompt(prompt);
        toast.success(`Applied "${prompt.name}"`, { icon: '✨' });
        onClose();
    };

    // Handle toggle favorite
    const handleToggleFavorite = async (id) => {
        const prompt = prompts.find(p => p.id === id);
        if (prompt) {
            await updatePromptMutation.mutateAsync({ id, updates: { favorite: !prompt.favorite } });
        }
    };

    // Handle delete with confirmation
    const handleDelete = async (id) => {
        const prompt = prompts.find(p => p.id === id);
        const confirmed = await confirm({
            title: 'Delete Prompt',
            message: `Delete "${prompt?.name}"? This cannot be undone.`,
            confirmText: 'Delete',
            isDangerous: true
        });
        if (confirmed) {
            await deletePromptMutation.mutateAsync(id);
            toast.success('Prompt deleted', { icon: '🗑️' });
        }
    };

    // Handle export
    const handleExport = async () => {
        setIsExporting(true);
        try {
            const { prompts: exportData } = await promptsApi.exportPrompts();
            const json = JSON.stringify(exportData, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `prompt-library-${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
            toast.success('Exported prompt library', { icon: '📥' });
        } catch (error) {
            toast.error(`Export failed: ${error.message}`);
        } finally {
            setIsExporting(false);
        }
    };

    // Handle import
    const handleImport = (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = async (event) => {
            setIsImporting(true);
            try {
                const result = await importPromptsMutation.mutateAsync(event.target.result);
                if (result.success) {
                    toast.success(`Imported ${result.count} prompts`, { icon: '📤' });
                } else {
                    toast.error(`Import failed: ${result.error}`, { icon: '❌' });
                }
            } catch (error) {
                toast.error(`Import failed: ${error.message}`, { icon: '❌' });
            } finally {
                setIsImporting(false);
            }
        };
        reader.readAsText(file);
        e.target.value = ''; // Reset input
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
            <div className="bg-gray-900 rounded-2xl border border-gray-700 w-full max-w-6xl max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-gray-800">
                    <div>
                        <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                            <FolderOpen className="text-blue-500" />
                            Prompt Library
                        </h2>
                        <p className="text-sm text-gray-400 mt-1">
                            {prompts.length} saved prompt{prompts.length !== 1 ? 's' : ''}
                        </p>
                    </div>

                    <div className="flex items-center gap-2">
                        {/* Export */}
                        <button
                            onClick={handleExport}
                            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
                            title="Export library"
                            disabled={prompts.length === 0 || isExporting}
                        >
                            <Download size={20} />
                        </button>

                        {/* Import */}
                        <label className={`p-2 rounded transition-colors ${isImporting ? 'text-gray-600' : 'text-gray-400 hover:text-white hover:bg-gray-800 cursor-pointer'}`}>
                            <Upload size={20} />
                            <input
                                type="file"
                                accept=".json"
                                onChange={handleImport}
                                className="hidden"
                                disabled={isImporting}
                            />
                        </label>

                        {/* Add New */}
                        <button
                            onClick={() => setShowAddForm(true)}
                            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded flex items-center gap-2 transition-colors"
                        >
                            <Plus size={18} />
                            Add Prompt
                        </button>

                        {/* Close */}
                        <button
                            onClick={onClose}
                            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
                        >
                            <X size={24} />
                        </button>
                    </div>
                </div>

                {/* Filters Bar */}
                <div className="p-6 border-b border-gray-800 space-y-4">
                    {/* Search */}
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
                        <input
                            type="text"
                            placeholder="Search prompts..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>

                    {/* View Tabs */}
                    <div className="flex gap-2">
                        <button
                            onClick={() => setView('all')}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${view === 'all'
                                ? 'bg-blue-500 text-white'
                                : 'bg-gray-800 text-gray-400 hover:text-white'
                                }`}
                        >
                            All
                        </button>
                        <button
                            onClick={() => setView('favorites')}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-1 ${view === 'favorites'
                                ? 'bg-blue-500 text-white'
                                : 'bg-gray-800 text-gray-400 hover:text-white'
                                }`}
                        >
                            <Star size={14} />
                            Favorites
                        </button>
                        <button
                            onClick={() => setView('popular')}
                            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-1 ${view === 'popular'
                                ? 'bg-blue-500 text-white'
                                : 'bg-gray-800 text-gray-400 hover:text-white'
                                }`}
                        >
                            <TrendingUp size={14} />
                            Most Used
                        </button>
                    </div>

                    {/* Categories */}
                    <div className="flex flex-wrap gap-2">
                        {categories.map(cat => (
                            <button
                                key={cat}
                                onClick={() => setSelectedCategory(cat)}
                                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${selectedCategory === cat
                                    ? 'bg-purple-500 text-white'
                                    : 'bg-gray-800 text-gray-400 hover:text-white'
                                    }`}
                            >
                                {cat}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Prompts Grid */}
                <div className="flex-1 overflow-y-auto p-6">
                    {isLoading && prompts.length === 0 ? (
                        <div className="text-center py-20 text-gray-500">
                            <p className="text-lg mb-2">Loading prompt library...</p>
                        </div>
                    ) : displayedPrompts.length === 0 ? (
                        <div className="text-center py-20 text-gray-500">
                            <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
                            <p className="text-lg mb-2">No prompts found</p>
                            <p className="text-sm">
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
                                    onEdit={(p) => setEditingPrompt(p)}
                                    onDelete={handleDelete}
                                    onToggleFavorite={handleToggleFavorite}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Add/Edit Form Modal */}
            {(showAddForm || editingPrompt) && (
                <PromptForm
                    prompt={editingPrompt}
                    onClose={() => {
                        setShowAddForm(false);
                        setEditingPrompt(null);
                    }}
                    onSave={() => {
                        setShowAddForm(false);
                        setEditingPrompt(null);
                    }}
                />
            )}
        </div>
    );
};

export default PromptLibrary;
