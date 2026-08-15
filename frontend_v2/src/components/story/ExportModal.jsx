import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, FileText, FileDown, BookOpen, Image as ImageIcon, LayoutTemplate } from 'lucide-react';
import { useExportStoryFormatted, usePublishStory } from '../../hooks/useWorldVault';
import toast from 'react-hot-toast';

/**
 * ExportModal — Modal for exporting/publishing a story in multiple formats.
 */
export default function ExportModal({ story, storyId, isOpen, onClose }) {
    const exportMutation = useExportStoryFormatted();
    const publishMutation = usePublishStory();

    const handleExport = (format) => {
        exportMutation.mutate({ storyId, format }, {
            onSuccess: () => {
                toast.success(`Exported as ${format.toUpperCase()}`);
                onClose();
            },
            onError: (e) => toast.error(`Export failed: ${e.message}`),
        });
    };

    const handlePublish = () => {
        publishMutation.mutate({ storyId }, {
            onSuccess: (data) => {
                toast.success('Story published!');
                navigator.clipboard.writeText(data.read_url || '');
                onClose();
            },
            onError: (e) => toast.error(`Publish failed: ${e.message}`),
        });
    };

    const isExporting = exportMutation.isPending;
    const isPublishing = publishMutation.isPending;

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

                            <div className="border-t border-gray-700 my-4" />

                            <button
                                onClick={handlePublish}
                                disabled={isPublishing || story?.is_published}
                                className="w-full flex items-center gap-3 p-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <BookOpen size={20} className="text-white" />
                                <div>
                                    <span className="font-medium text-white">
                                        {story?.is_published ? 'Already Published' : 'Publish to Web'}
                                    </span>
                                    <p className="text-xs text-purple-200">Generate a shareable link</p>
                                </div>
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}
