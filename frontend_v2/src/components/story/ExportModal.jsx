import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, FileText, FileDown, BookOpen, Image as ImageIcon, LayoutTemplate, Globe } from 'lucide-react';
import { useExportStoryFormatted, useExportPublishedStory, usePublishStory, useUnpublishStory } from '../../hooks/useWorldVault';
import toast from 'react-hot-toast';
import { useEscapeKey } from '../../hooks/useEscapeKey';

/**
 * ExportModal — Modal for exporting/publishing a story in multiple formats.
 * `token` mode (public StoryReader) hides publish controls; `story` mode shows
 * Publish + Unpublish.
 */
export default function ExportModal({ story, storyId, token, isOpen, onClose }) {
    useEscapeKey(onClose, !!isOpen);

    const exportMutation = useExportStoryFormatted();
    const exportPublishedMutation = useExportPublishedStory();
    const publishMutation = usePublishStory();
    const unpublishMutation = useUnpublishStory();

    const handleExport = (format) => {
        const onSuccess = () => {
            toast.success(`Exported as ${format.toUpperCase()}`);
            onClose();
        };
        const onError = (e) => toast.error(`Export failed: ${e.message}`);

        if (token) {
            exportPublishedMutation.mutate({ token, format }, { onSuccess, onError });
        } else {
            exportMutation.mutate({ storyId, format }, { onSuccess, onError });
        }
    };

    const handlePublish = () => {
        publishMutation.mutate({ storyId }, {
            onSuccess: (data) => {
                toast.success('Story published — link copied!');
                navigator.clipboard.writeText(data.read_url || '');
                onClose();
            },
            onError: (e) => toast.error(`Publish failed: ${e.message}`),
        });
    };

    const handleUnpublish = () => {
        unpublishMutation.mutate({ storyId }, {
            onSuccess: () => {
                toast.success('Story unpublished');
                onClose();
            },
            onError: (e) => toast.error(`Unpublish failed: ${e.message}`),
        });
    };

    const isExporting = exportMutation.isPending || exportPublishedMutation.isPending;
    const isPublishing = publishMutation.isPending || unpublishMutation.isPending;
    const published = !!story?.is_published;

    return (
        <AnimatePresence>
            {isOpen && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="w-full max-w-md bg-gray-900 border border-gray-700 rounded-xl shadow-2xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between p-6 border-b border-gray-700">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                <FileDown size={20} className="text-blue-400" />
                                Export &amp; Publish Story
                            </h3>
                            <button
                                onClick={onClose}
                                className="p-1 text-gray-400 hover:text-white"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div className="p-6 space-y-3">
                            <button
                                onClick={() => handleExport('md')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <FileText size={20} className="text-green-400" />
                                <div>
                                    <span className="font-medium text-white">Export as Markdown</span>
                                    <p className="text-xs text-gray-400">Clean .md file for Obsidian, Notion, etc.</p>
                                </div>
                            </button>

                            <button
                                onClick={() => handleExport('json')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <FileText size={20} className="text-blue-400" />
                                <div>
                                    <span className="font-medium text-white">Export as JSON</span>
                                    <p className="text-xs text-gray-400">Full raw data with beats and metadata.</p>
                                </div>
                            </button>

                            <button
                                onClick={() => handleExport('epub')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <BookOpen size={20} className="text-amber-400" />
                                <div>
                                    <span className="font-medium text-white">Export as ePub</span>
                                    <p className="text-xs text-gray-400">Readable on Kindle, Apple Books, etc.</p>
                                </div>
                            </button>

                            <button
                                onClick={() => handleExport('comic')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <LayoutTemplate size={20} className="text-red-400" />
                                <div>
                                    <span className="font-medium text-white">Export as Comic PDF</span>
                                    <p className="text-xs text-gray-400">Multi-page PDF with panels and images.</p>
                                </div>
                            </button>

                            <button
                                onClick={() => handleExport('webtoon')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <ImageIcon size={20} className="text-cyan-400" />
                                <div>
                                    <span className="font-medium text-white">Export as Webtoon</span>
                                    <p className="text-xs text-gray-400">Long vertical scroll image strip.</p>
                                </div>
                            </button>

                            {!token && (
                                <>
                                    <div className="border-t border-gray-700 my-4" />

                                    {published ? (
                                        <button
                                            onClick={handleUnpublish}
                                            disabled={isPublishing}
                                            className="w-full flex items-center gap-3 p-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-500/30 disabled:opacity-50 rounded-lg text-left transition-colors"
                                        >
                                            <Globe size={20} className="text-amber-400" />
                                            <div>
                                                <span className="font-medium text-white">Unpublish Story</span>
                                                <p className="text-xs text-amber-200">Hide the public read link</p>
                                            </div>
                                        </button>
                                    ) : (
                                        <button
                                            onClick={handlePublish}
                                            disabled={isPublishing}
                                            className="w-full flex items-center gap-3 p-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                                        >
                                            <BookOpen size={20} className="text-white" />
                                            <div>
                                                <span className="font-medium text-white">Publish to Web</span>
                                                <p className="text-xs text-purple-200">Generate a shareable link</p>
                                            </div>
                                        </button>
                                    )}
                                </>
                            )}
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}
