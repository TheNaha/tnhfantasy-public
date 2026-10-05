import { useState, useId } from 'react';
import { X, Save, Tag } from 'lucide-react';
import {
    usePromptCategories,
    useCreatePrompt,
    useUpdatePrompt
} from '../../hooks/usePrompts';
import toast from 'react-hot-toast';
import ModalOverlay from '../common/ModalOverlay';

/**
 * Form for adding or editing prompts.
 *
 * On `ModalOverlay`, not a hand-rolled `fixed inset-0` of its own. It was the
 * only dialog in this drawer with no Escape handling, no backdrop click and no
 * portal: it could be dismissed only with its own Cancel button or its close X,
 * and because it sat in the DOM wherever the generator rendered it rather than in
 * a portal on `document.body`, a stacking-context rule decided whether it ended
 * up above or below a dialog opened over it. The `role="dialog"` goes on the
 * panel, not on the backdrop — `ModalOverlay` is the layer behind the dialog, and
 * nesting the role there breaks testing-library.
 */
export const PromptForm = ({ prompt, onClose, onSave }) => {
    const nameId = useId();
    const descriptionId = useId();
    const categoryId = useId();
    const textId = useId();
    const negativeId = useId();
    const tagId = useId();

    const { data: categories } = usePromptCategories();
    const createPromptMutation = useCreatePrompt();
    const updatePromptMutation = useUpdatePrompt();

    const isEditing = !!prompt;

    const [formData, setFormData] = useState({
        name: prompt?.name || '',
        text: prompt?.text || '',
        negative: prompt?.negative || '',
        category: prompt?.category || 'Custom',
        description: prompt?.description || '',
        tags: prompt?.tags || [],
    });

    const [tagInput, setTagInput] = useState('');

    const handleChange = (field, value) => {
        setFormData(prev => ({ ...prev, [field]: value }));
    };

    const handleAddTag = () => {
        if (!tagInput.trim()) return;
        if (formData.tags.includes(tagInput.trim())) {
            toast.error('Tag already exists');
            return;
        }
        setFormData(prev => ({
            ...prev,
            tags: [...prev.tags, tagInput.trim()]
        }));
        setTagInput('');
    };

    const handleRemoveTag = (tagToRemove) => {
        setFormData(prev => ({
            ...prev,
            tags: prev.tags.filter(t => t !== tagToRemove)
        }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!formData.name.trim()) {
            toast.error('Please enter a name for this prompt');
            return;
        }

        if (!formData.text.trim()) {
            toast.error('Please enter the prompt text');
            return;
        }

        try {
            if (isEditing) {
                await updatePromptMutation.mutateAsync({ id: prompt.id, updates: formData });
                toast.success('Prompt updated successfully', { icon: '✏️' });
            } else {
                await createPromptMutation.mutateAsync(formData);
                toast.success('Prompt added to library', { icon: '✨' });
            }

            onSave?.();
            onClose();
        } catch (error) {
            toast.error(error.message || 'Failed to save prompt');
        }
    };

    return (
        <ModalOverlay onClose={onClose} className="z-[60] bg-black/80 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-label={isEditing ? 'Edit Prompt' : 'Add New Prompt'}
                onClick={(e) => e.stopPropagation()}
                className="bg-gray-900 rounded-xl border border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto"
            >
                {/* Header */}
                <div className="flex items-center justify-between p-6 border-b border-gray-800 sticky top-0 bg-gray-900 z-10">
                    <h3 className="text-xl font-bold text-white">
                        {isEditing ? 'Edit Prompt' : 'Add New Prompt'}
                    </h3>
                    <button
                        onClick={onClose}
                        className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
                        aria-label="Close form"
                    >
                        <X size={20} aria-hidden="true" />
                    </button>
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="p-6 space-y-4">
                    {/* Name */}
                    <div>
                        <label htmlFor={nameId} className="block text-sm font-medium text-gray-300 mb-2">
                            Name <span className="text-red-400">*</span>
                        </label>
                        <input
                            id={nameId}
                            type="text"
                            value={formData.name}
                            onChange={(e) => handleChange('name', e.target.value)}
                            placeholder="e.g., Realistic Portrait"
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none"
                            required
                        />
                    </div>

                    {/* Description */}
                    <div>
                        <label htmlFor={descriptionId} className="block text-sm font-medium text-gray-300 mb-2">
                            Description
                        </label>
                        <input
                            id={descriptionId}
                            type="text"
                            value={formData.description}
                            onChange={(e) => handleChange('description', e.target.value)}
                            placeholder="Brief description of this prompt"
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>

                    {/* Category */}
                    <div>
                        <label htmlFor={categoryId} className="block text-sm font-medium text-gray-300 mb-2">
                            Category
                        </label>
                        <select
                            id={categoryId}
                            value={formData.category}
                            onChange={(e) => handleChange('category', e.target.value)}
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            {categories.filter(c => c !== 'All').map(cat => (
                                <option key={cat} value={cat}>{cat}</option>
                            ))}
                        </select>
                    </div>

                    {/* Prompt Text */}
                    <div>
                        <label htmlFor={textId} className="block text-sm font-medium text-gray-300 mb-2">
                            Prompt <span className="text-red-400">*</span>
                        </label>
                        <textarea
                            id={textId}
                            value={formData.text}
                            onChange={(e) => handleChange('text', e.target.value)}
                            placeholder="Enter your prompt here..."
                            rows={6}
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none resize-y"
                            required
                        />
                        <p className="text-xs text-gray-500 mt-1">
                            {formData.text.length} characters
                        </p>
                    </div>

                    {/* Negative Prompt */}
                    <div>
                        <label htmlFor={negativeId} className="block text-sm font-medium text-gray-300 mb-2">
                            Negative Prompt
                        </label>
                        <textarea
                            id={negativeId}
                            value={formData.negative}
                            onChange={(e) => handleChange('negative', e.target.value)}
                            placeholder="Things to avoid in the generation (optional)"
                            rows={3}
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none resize-y"
                        />
                    </div>

                    {/* Tags */}
                    <div>
                        <label htmlFor={tagId} className="block text-sm font-medium text-gray-300 mb-2">
                            Tags
                        </label>
                        <div className="flex gap-2 mb-2">
                            <input
                                id={tagId}
                                type="text"
                                value={tagInput}
                                onChange={(e) => setTagInput(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        e.preventDefault();
                                        handleAddTag();
                                    }
                                }}
                                placeholder="Add a tag..."
                                className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none"
                            />
                            <button
                                type="button"
                                onClick={handleAddTag}
                                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg flex items-center gap-2 transition-colors"
                            >
                                <Tag size={16} />
                                Add
                            </button>
                        </div>

                        {/* Tag Pills */}
                        {formData.tags.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {formData.tags.map((tag, i) => (
                                    <span
                                        key={i}
                                        className="flex items-center gap-1 px-2 py-1 bg-blue-500/20 text-blue-300 rounded border border-blue-500/30 text-sm"
                                    >
                                        {tag}
                                        <button
                                            type="button"
                                            onClick={() => handleRemoveTag(tag)}
                                            className="hover:text-white"
                                            aria-label={`Remove tag ${tag}`}
                                        >
                                            <X size={14} aria-hidden="true" />
                                        </button>
                                    </span>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3 pt-4">
                        <button
                            type="submit"
                            className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-3 rounded-lg font-medium flex items-center justify-center gap-2 transition-colors"
                        >
                            <Save size={18} />
                            {isEditing ? 'Update Prompt' : 'Save Prompt'}
                        </button>
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-6 py-3 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors"
                        >
                            Cancel
                        </button>
                    </div>
                </form>
            </div>
        </ModalOverlay>
    );
};

export default PromptForm;
