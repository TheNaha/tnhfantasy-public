import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, FileText, FileDown, BookOpen, Image as ImageIcon, LayoutTemplate, Globe, Film, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { useExportStoryFormatted, useExportPublishedStory, useExportChapterComic, usePublishStory, useUnpublishStory } from '../../hooks/useWorldVault';
import toast from 'react-hot-toast';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { copyToClipboard } from '../../utils/clipboard';
import { useJobStatus } from '../../hooks/useJobStatus';
import { jobMetadata } from '../../utils/jobStatus';
import { claimJobToast, releaseJobToast } from '../../utils/jobToastOwnership';

/**
 * ExportModal — Modal for exporting/publishing a story in multiple formats.
 * `token` mode (public StoryReader) hides publish controls; `story` mode shows
 * Publish + Unpublish.
 */
export default function ExportModal({ story, storyId, chapterId, token, isOpen, onClose }) {
    useEscapeKey(onClose, !!isOpen);

    const exportMutation = useExportStoryFormatted();
    const exportPublishedMutation = useExportPublishedStory();
    const exportChapterComic = useExportChapterComic();
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

    // The comic export is a background JOB (up to 30 min of panel generation),
    // not an instant file download: the route only enqueues it and returns
    // {job_id}, and the artifact arrives later via the job's metadata
    // (`download_url`). The old code toasted "Comic exported as CBZ" on
    // ENQUEUE and closed — the user was told it finished in under a second
    // with no way to ever fetch the file. Now: announce the start, keep the
    // job id, and track it to a download button in the status card below.
    const [comicJobId, setComicJobId] = React.useState(null);
    const [comicFormat, setComicFormat] = React.useState(null);
    const { data: comicJob } = useJobStatus(comicJobId);
    const comicNotifiedRef = React.useRef(null);

    React.useEffect(() => {
        if (!comicJobId || !comicJob) return;
        if (comicNotifiedRef.current === comicJobId) return;
        const status = comicJob.status;
        if (status === 'completed' || status === 'failed' || status === 'cancelled') {
            comicNotifiedRef.current = comicJobId;
            releaseJobToast(comicJobId);
            if (status === 'completed') {
                toast.success('Comic export ready — download it from the export dialog', { id: 'comic-export' });
            }
            // failure/cancelled is announced by the global job handler.
        }
    }, [comicJob, comicJobId]);

    const handleExportComic = (format) => {
        if (!storyId || !chapterId) {
            toast.error('Cannot export comic: story or chapter not selected');
            return;
        }
        const onSuccess = (data) => {
            const jobId = data?.job_id || null;
            setComicJobId(jobId);
            setComicFormat(format);
            comicNotifiedRef.current = null;
            // Claim the terminal toast so the global handler does not show a
            // bogus "Image generated!" for an export that makes no gallery
            // image (the job's task_type is `image` for progress plumbing).
            if (jobId) claimJobToast(jobId);
            toast.success(
                `Comic export started (${format.toUpperCase()}) — panel images generate in the background`,
                { id: 'comic-export' }
            );
            // The dialog stays open: the status card below tracks the job to
            // its download link. Closing it is fine — the state survives and
            // reopening the dialog shows the same card.
        };
        const onError = (e) => toast.error(`Comic export failed to start: ${e.message}`);
        exportChapterComic.mutate({ storyId, chapterId, format }, { onSuccess, onError });
    };

    const comicStatus = comicJobId ? comicJob?.status : null;
    const comicDownloadUrl = comicStatus === 'completed' ? jobMetadata(comicJob)?.download_url : null;

    const handlePublish = () => {
        publishMutation.mutate({ storyId }, {
            // Async: `onSuccess` awaits the copy. It did not before, and the
            // ordering was the bug.
            //
            // This used to be:
            //     toast.success('Story published — link copied!');
            //     navigator.clipboard.writeText(data.read_url || '');
            //     onClose();
            // `navigator.clipboard` is undefined on a non-secure origin
            // (measured: `http://100.150.0.4:5174` → `{"secure":false,
            // "clip":false}`, `localhost:5174` → both true), and the
            // dereference throws a SYNCHRONOUS TypeError — before any promise
            // exists, so no `.then`/`.catch` anywhere downstream could see it.
            // The throw skipped `onClose()`, leaving the modal open under a
            // "link copied!" toast, with the link absent and Publish still
            // enabled. The next click was a second publish of an
            // already-published story.
            onSuccess: async (data) => {
                const rawUrl = data?.read_url || '';
                const fullUrl = rawUrl
                    ? (rawUrl.startsWith('http') ? rawUrl : `${window.location.origin}${rawUrl}`)
                    : '';
                const copied = await copyToClipboard(fullUrl);
                // The publish succeeded either way, so it is announced as such.
                // The copy is a separate fact with a separate answer.
                if (copied) {
                    toast.success('Story published — link copied!');
                } else {
                    toast.success('Story published');
                    toast.error('Could not copy the link — your browser blocks the clipboard on this address. Copy it from the reader URL.');
                }
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

    const isExporting = exportMutation.isPending || exportPublishedMutation.isPending || exportChapterComic.isPending;
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
                                aria-label="Close"
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
                                onClick={() => handleExportComic('cbz')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <Film size={20} className="text-red-400" />
                                <div>
                                    <span className="font-medium text-white">Export as AI Comic (CBZ)</span>
                                    <p className="text-xs text-gray-400">Generates panel images with character consistency. CBZ archive + HTML reader.</p>
                                </div>
                            </button>

                            <button
                                onClick={() => handleExportComic('html')}
                                disabled={isExporting}
                                className="w-full flex items-center gap-3 p-3 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded-lg text-left transition-colors"
                            >
                                <LayoutTemplate size={20} className="text-cyan-400" />
                                <div>
                                    <span className="font-medium text-white">Export as AI Webtoon (HTML)</span>
                                    <p className="text-xs text-gray-400">Self-contained HTML reader with panel navigation.</p>
                                </div>
                            </button>

                            {comicJobId && (
                                <div className="p-3 bg-gray-800/60 border border-gray-700 rounded-lg space-y-2">
                                    <div className="flex items-center gap-2 text-sm text-gray-200">
                                        {comicStatus === 'completed' ? (
                                            <CheckCircle2 size={16} className="text-green-400" />
                                        ) : comicStatus === 'failed' || comicStatus === 'cancelled' ? (
                                            <AlertTriangle size={16} className="text-red-400" />
                                        ) : (
                                            <Loader2 size={16} className="text-blue-400 animate-spin" />
                                        )}
                                        <span>
                                            {comicStatus === 'completed'
                                                ? `Comic export ready (${String(comicFormat || '').toUpperCase()})`
                                                : comicStatus === 'failed'
                                                    ? 'Comic export failed'
                                                    : comicStatus === 'cancelled'
                                                        ? 'Comic export cancelled'
                                                        : 'Comic export running — panel images take a few minutes; you can close this dialog and come back'}
                                        </span>
                                    </div>
                                    {(comicStatus === 'failed') && (
                                        <p className="text-xs text-red-400">{comicJob?.error || 'Unknown error'}</p>
                                    )}
                                    {comicStatus === 'completed' && comicDownloadUrl && (
                                        <a
                                            href={comicDownloadUrl}
                                            download
                                            className="inline-flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
                                        >
                                            <FileDown size={16} />
                                            Download {String(comicFormat || 'archive').toUpperCase()}
                                        </a>
                                    )}
                                </div>
                            )}

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
