import { Star, Trash2, Copy, Edit2, TrendingUp, Check } from 'lucide-react';
import { useState } from 'react';
import { copyToClipboard } from '../../utils/clipboard';
import { parseGalleryDate } from '../../utils/dateTime';

/**
 * Individual Prompt Card Component
 * Displays a saved prompt with actions
 */
export const PromptCard = ({ prompt, onUse, onEdit, onDelete, onToggleFavorite }) => {
    const [showFullText, setShowFullText] = useState(false);
    const [isCopied, setIsCopied] = useState(false);

    const handleCopyToClipboard = async () => {
        await copyToClipboard(prompt.text);
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
    };

    return (
        <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 hover:border-gray-600 transition-all group">
            {/* Header */}
            <div className="flex items-start justify-between mb-3">
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-white truncate" title={prompt.name}>
                        {prompt.name}
                    </h3>
                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded border border-blue-500/30">
                            {prompt.category}
                        </span>
                        {(prompt.usage_count ?? prompt.usageCount ?? 0) > 0 && (
                            <span className="text-xs text-gray-500 flex items-center gap-1">
                                <TrendingUp size={12} />
                                {prompt.usage_count ?? prompt.usageCount}
                            </span>
                        )}
                    </div>
                </div>

                {/* Favorite Button */}
                <button
                    onClick={() => onToggleFavorite(prompt.id)}
                    className={`p-1.5 rounded transition-colors ${prompt.favorite
                            ? 'text-yellow-500 hover:text-yellow-400'
                            : 'text-gray-600 hover:text-yellow-500'
                        }`}
                    title={prompt.favorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-label={prompt.favorite ? 'Remove from favorites' : 'Add to favorites'}
                    aria-pressed={prompt.favorite}
                >
                    <Star size={18} fill={prompt.favorite ? 'currentColor' : 'none'} aria-hidden="true" />
                </button>
            </div>

            {/* Description */}
            {prompt.description && (
                <p className="text-sm text-gray-400 mb-2 line-clamp-2">
                    {prompt.description}
                </p>
            )}

            {/* Prompt Text */}
            <div className="mb-3">
                <p className={`text-sm text-gray-300 bg-gray-900/50 p-2 rounded border border-gray-700 ${showFullText ? '' : 'line-clamp-3'
                    }`}>
                    {prompt.text || '(Empty prompt)'}
                </p>
                {prompt.text && prompt.text.length > 150 && (
                    <button
                        onClick={() => setShowFullText(!showFullText)}
                        className="text-xs text-blue-400 hover:text-blue-300 mt-1"
                    >
                        {showFullText ? 'Show less' : 'Show more'}
                    </button>
                )}
            </div>

            {/* Tags */}
            {prompt.tags && prompt.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                    {prompt.tags.slice(0, 3).map((tag, i) => (
                        <span
                            key={i}
                            className="text-xs px-1.5 py-0.5 bg-gray-700 text-gray-400 rounded"
                        >
                            {tag}
                        </span>
                    ))}
                    {prompt.tags.length > 3 && (
                        <span className="text-xs text-gray-500">
                            +{prompt.tags.length - 3}
                        </span>
                    )}
                </div>
            )}

            {/* Actions */}
            <div className="flex gap-2">
                <button
                    onClick={() => onUse(prompt)}
                    className="flex-1 bg-blue-600 hover:bg-blue-500 text-white py-2 rounded text-sm font-medium transition-colors"
                >
                    Use Prompt
                </button>
                <button
                    onClick={handleCopyToClipboard}
                    className={`p-2 rounded transition-colors ${isCopied
                            ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                            : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                        }`}
                    title={isCopied ? "Copied!" : "Copy to clipboard"}
                    aria-label={isCopied ? "Copied!" : "Copy to clipboard"}
                >
                    {isCopied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
                <button
                    onClick={() => onEdit(prompt)}
                    className="p-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded transition-colors"
                    title="Edit prompt"
                    aria-label="Edit prompt"
                >
                    <Edit2 size={16} aria-hidden="true" />
                </button>
                <button
                    onClick={() => onDelete(prompt.id)}
                    className="p-2 bg-red-900/20 hover:bg-red-900/40 text-red-400 rounded transition-colors"
                    title="Delete prompt"
                    aria-label="Delete prompt"
                >
                    <Trash2 size={16} aria-hidden="true" />
                </button>
            </div>

            {/* Metadata Footer */}
            <div className="mt-3 pt-3 border-t border-gray-700 text-xs text-gray-500">
                Created {parseGalleryDate(prompt.created_at ?? prompt.createdAt).toLocaleDateString()}
            </div>
        </div>
    );
};

export default PromptCard;
