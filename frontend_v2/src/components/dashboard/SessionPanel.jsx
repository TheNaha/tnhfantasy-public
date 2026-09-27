import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
    AlertTriangle,
    ArrowLeft,
    Check,
    Edit2,
    Image as ImageIcon,
    Layers,
    Loader2,
    Lock,
    Merge,
    Plus,
    Scissors,
    Trash2,
    Wand2,
    X,
} from 'lucide-react';

import { useConfirmation } from '../../store/confirmationStore';
import { useGallery } from '../../hooks/useGallery';
import { thumbUrl } from '../../utils/assetUrl';
import { formatTimestamp } from '../../utils/dateTime';
import { getSessionName } from '../../utils/dashboardItems';
import {
    flattenSessionPages,
    useAddSessionAssets,
    useCreateSession,
    useDeleteSession,
    useDetectSessions,
    useMergeSession,
    useRemoveSessionAsset,
    useRenameSession,
    useSessionAssets,
    useSessions,
    useSplitSession,
} from '../../hooks/useSessions';

function formatSessionRange(startAt, endAt) {
    if (!startAt && !endAt) return 'No images yet';
    if (!endAt) return `From ${formatTimestamp(startAt)}`;
    if (!startAt) return `Until ${formatTimestamp(endAt)}`;
    return `${formatTimestamp(startAt)} → ${formatTimestamp(endAt)}`;
}

function pluralImages(count) {
    return `${count} image${count === 1 ? '' : 's'}`;
}

/**
 * The one place the auto-detected / curated distinction and the lock marker are
 * drawn, so the drawer row and the session view-mode card cannot drift.
 */
export function SessionBadges({ autoDetected, locked, className = '' }) {
    return (
        <span className={`flex items-center gap-1.5 flex-wrap ${className}`}>
            <span
                title={autoDetected
                    ? 'Found automatically by the session detector'
                    : 'Created or edited by you — the detector will leave it alone'}
                className={`px-1.5 py-0.5 rounded text-2xs font-semibold uppercase tracking-wide border ${
                    autoDetected
                        ? 'border-purple-500/40 bg-purple-500/15 text-purple-300'
                        : 'border-blue-500/40 bg-blue-500/15 text-blue-300'
                }`}
            >
                {autoDetected ? 'Auto-detected' : 'Curated'}
            </span>
            {locked && (
                <span
                    title="Curated — the session detector will not modify this session"
                    aria-label="Locked session"
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-semibold uppercase tracking-wide border border-amber-500/40 bg-amber-500/15 text-amber-300"
                >
                    <Lock size={10} aria-hidden="true" />
                    Locked
                </span>
            )}
        </span>
    );
}

function SessionCover({ session, alt }) {
    if (!session?.thumbnail) {
        return (
            <div className="w-12 h-12 rounded bg-gray-800 flex items-center justify-center flex-shrink-0">
                <Layers size={20} className="text-gray-600" aria-hidden="true" />
            </div>
        );
    }
    return (
        <img
            src={thumbUrl(session.thumbnail)}
            alt={alt}
            loading="lazy"
            className="w-12 h-12 rounded object-cover flex-shrink-0 bg-gray-800"
        />
    );
}

function DetectButton({ onClick, pending, className = '', children }) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={pending}
            aria-busy={pending}
            className={`inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-60 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors ${className}`}
        >
            {pending ? (
                <>
                    <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                    Scanning your library…
                </>
            ) : (
                <>
                    <Wand2 size={16} aria-hidden="true" />
                    {children || 'Detect sessions'}
                </>
            )}
        </button>
    );
}

function DetectResultSummary({ summary }) {
    if (!summary) return null;
    const entries = [
        ['Created', summary.sessions_created],
        ['Extended', summary.sessions_extended],
        ['Skipped (curated)', summary.sessions_skipped_locked],
    ];
    return (
        <div
            role="status"
            className="rounded-lg border border-purple-500/30 bg-purple-500/10 p-3 text-sm text-purple-100 space-y-1"
        >
            {entries.map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-4">
                    <span className="text-purple-200/80">{label}</span>
                    <span className="font-semibold tabular-nums">{value ?? 0}</span>
                </div>
            ))}
            {typeof summary.elapsed_seconds === 'number' && (
                <div className="flex items-center justify-between gap-4 border-t border-purple-500/20 pt-1 text-xs text-purple-200/70">
                    <span>Elapsed</span>
                    <span className="tabular-nums">{summary.elapsed_seconds}s</span>
                </div>
            )}
        </div>
    );
}

function SessionSplitPicker({ session, onCancel, onDone }) {
    const { data, isLoading, error } = useSessionAssets(session.id);
    const splitMutation = useSplitSession();
    const [keepIds, setKeepIds] = useState(() => new Set());

    const assets = useMemo(() => data?.assets || [], [data]);
    const total = data?.total ?? assets.length;
    const movingCount = Math.max(0, total - keepIds.size);
    const canSplit = keepIds.size > 0 && keepIds.size < total;

    const toggle = useCallback((assetId) => {
        setKeepIds((current) => {
            const next = new Set(current);
            if (next.has(assetId)) {
                next.delete(assetId);
            } else {
                next.add(assetId);
            }
            return next;
        });
    }, []);

    const submit = useCallback(async () => {
        if (!canSplit || splitMutation.isPending) return;
        await splitMutation.mutateAsync({ id: session.id, keepAssetIds: Array.from(keepIds) });
        onDone();
    }, [canSplit, keepIds, onDone, session.id, splitMutation]);

    return (
        <div className="flex-1 min-h-0 flex flex-col">
            <div className="p-4 border-b border-gray-800 flex items-center gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                    aria-label="Back to sessions"
                >
                    <ArrowLeft size={18} aria-hidden="true" />
                </button>
                <div className="min-w-0 flex-1">
                    <h3 className="text-white font-semibold truncate">Split {getSessionName(session)}</h3>
                    <p className="text-xs text-gray-500">
                        Tick the images that stay. Everything else moves to a new session.
                    </p>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
                {isLoading && (
                    <div className="flex items-center justify-center gap-2 py-10 text-gray-400 text-sm">
                        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                        Loading images…
                    </div>
                )}

                {error && (
                    <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200"
                    >
                        <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                        <span>{error.message || 'Could not load this session’s images.'}</span>
                    </div>
                )}

                {!isLoading && !error && assets.length === 0 && (
                    <p className="py-10 text-center text-sm text-gray-500">
                        This session has no images, so there is nothing to split.
                    </p>
                )}

                {!isLoading && !error && assets.length > 0 && (
                    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                        {assets.map((asset) => {
                            const checked = keepIds.has(asset.id);
                            return (
                                <label
                                    key={asset.id}
                                    className={`relative block cursor-pointer rounded-lg overflow-hidden border-2 transition-colors ${
                                        checked ? 'border-blue-500' : 'border-transparent hover:border-gray-600'
                                    }`}
                                >
                                    <input
                                        type="checkbox"
                                        className="sr-only"
                                        checked={checked}
                                        onChange={() => toggle(asset.id)}
                                    />
                                    <img
                                        src={thumbUrl(asset.relative_path)}
                                        alt={asset.relative_path}
                                        loading="lazy"
                                        className="w-full aspect-square object-cover bg-gray-800"
                                    />
                                    <span
                                        className={`absolute top-1 left-1 w-5 h-5 rounded border-2 flex items-center justify-center ${
                                            checked ? 'bg-blue-500 border-blue-500' : 'border-white/60 bg-black/50'
                                        }`}
                                        aria-hidden="true"
                                    >
                                        {checked && <Check size={12} strokeWidth={3} className="text-white" />}
                                    </span>
                                </label>
                            );
                        })}
                    </div>
                )}
            </div>

            <div className="p-4 border-t border-gray-800 space-y-3">
                <p className="text-xs text-gray-400" aria-live="polite">
                    Keeping <span className="font-semibold text-white">{keepIds.size}</span> of {total} —{' '}
                    <span className="font-semibold text-white">{movingCount}</span> will move to a new session.
                </p>
                {splitMutation.error && (
                    <p role="alert" className="text-sm text-red-300">
                        {splitMutation.error.message || 'Split failed.'}
                    </p>
                )}
                <div className="flex gap-2">
                    <button
                        type="button"
                        onClick={onCancel}
                        className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg font-medium transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={submit}
                        disabled={!canSplit || splitMutation.isPending}
                        aria-busy={splitMutation.isPending}
                        className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                    >
                        {splitMutation.isPending
                            ? <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                            : <Scissors size={16} aria-hidden="true" />}
                        Split session
                    </button>
                </div>
            </div>
        </div>
    );
}

/**
 * Add and remove single images, as opposed to SessionSplitPicker which moves a
 * whole complement to a new session. Both endpoints (`/assets` POST/DELETE)
 * existed with no caller at all.
 */
function SessionImagePicker({ session, onCancel }) {
    const { data, isLoading, error } = useSessionAssets(session.id);
    const { data: galleryData, isLoading: galleryLoading } = useGallery({ sort: 'date_desc' });
    const addMutation = useAddSessionAssets();
    const removeMutation = useRemoveSessionAsset();
    const [actionError, setActionError] = useState('');

    const assets = useMemo(() => data?.assets || [], [data]);
    const memberIds = useMemo(() => new Set(assets.map((asset) => asset.id)), [assets]);
    const candidates = useMemo(() => {
        const pages = galleryData?.pages || [];
        const files = pages.flatMap((page) => page.files || []);
        return files.filter((file) => !memberIds.has(file.id)).slice(0, 60);
    }, [galleryData, memberIds]);

    const handleAdd = useCallback(async (assetId) => {
        setActionError('');
        try {
            await addMutation.mutateAsync({ id: session.id, assetIds: [assetId] });
        } catch (mutationError) {
            setActionError(mutationError?.message || 'Could not add that image.');
        }
    }, [addMutation, session.id]);

    const handleRemove = useCallback(async (assetId) => {
        setActionError('');
        try {
            await removeMutation.mutateAsync({ id: session.id, assetId });
        } catch (mutationError) {
            setActionError(mutationError?.message || 'Could not remove that image.');
        }
    }, [removeMutation, session.id]);

    return (
        <div className="flex-1 min-h-0 flex flex-col">
            <div className="p-4 border-b border-gray-800 flex items-center gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                    aria-label="Back to sessions"
                >
                    <ArrowLeft size={18} aria-hidden="true" />
                </button>
                <div className="min-w-0 flex-1">
                    <h3 className="text-white font-semibold truncate">Images in {getSessionName(session)}</h3>
                    <p className="text-xs text-gray-500">Add images from your library, or take one out.</p>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-5">
                {actionError && (
                    <p role="alert" className="text-sm text-red-300">{actionError}</p>
                )}

                {error && (
                    <p role="alert" className="text-sm text-red-300">
                        {error.message || 'Could not load this session\u2019s images.'}
                    </p>
                )}

                {isLoading && (
                    <p className="text-sm text-gray-400">Loading images…</p>
                )}

                {!isLoading && (
                    <section>
                        <h4 className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">
                            In this session
                        </h4>
                        {assets.length === 0 ? (
                            <p className="text-sm text-gray-500">This session has no images yet.</p>
                        ) : (
                            <ul className="space-y-2">
                                {assets.map((asset) => (
                                    <li
                                        key={asset.id}
                                        className="flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-2"
                                    >
                                        <img
                                            src={thumbUrl(asset.relative_path)}
                                            alt={asset.relative_path}
                                            loading="lazy"
                                            className="w-10 h-10 rounded object-cover bg-gray-900 flex-shrink-0"
                                        />
                                        <span className="text-xs text-gray-300 truncate flex-1">
                                            {asset.relative_path}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => handleRemove(asset.id)}
                                            disabled={removeMutation.isPending}
                                            className="p-1.5 rounded-md bg-gray-800 hover:bg-red-900/50 text-gray-300 hover:text-red-300 disabled:opacity-50 transition-colors"
                                            aria-label={`Remove ${asset.relative_path} from this session`}
                                        >
                                            <Trash2 size={14} aria-hidden="true" />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </section>
                )}

                <section>
                    <h4 className="text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">
                        Add from your library
                    </h4>
                    {galleryLoading && (
                        <p className="text-sm text-gray-400">Loading your library…</p>
                    )}
                    {!galleryLoading && candidates.length === 0 && (
                        <p className="text-sm text-gray-500">
                            Nothing left to add — the most recent images are all in this session.
                        </p>
                    )}
                    {!galleryLoading && candidates.length > 0 && (
                        <ul className="space-y-2">
                            {candidates.map((file) => (
                                <li
                                    key={file.id}
                                    className="flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-2"
                                >
                                    <img
                                        src={thumbUrl(file.relative_path)}
                                        alt={file.relative_path || ''}
                                        loading="lazy"
                                        className="w-10 h-10 rounded object-cover bg-gray-900 flex-shrink-0"
                                    />
                                    <span className="text-xs text-gray-300 truncate flex-1">
                                        {file.relative_path}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() => handleAdd(file.id)}
                                        disabled={addMutation.isPending}
                                        className="p-1.5 rounded-md bg-gray-800 hover:bg-blue-900/50 text-gray-300 hover:text-blue-300 disabled:opacity-50 transition-colors"
                                        aria-label={`Add ${file.relative_path} to this session`}
                                    >
                                        <Plus size={14} aria-hidden="true" />
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </section>
            </div>

            <div className="p-4 border-t border-gray-800 flex justify-end">
                <button
                    type="button"
                    onClick={onCancel}
                    className="px-5 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-sm transition-colors"
                >
                    Done
                </button>
            </div>
        </div>
    );
}

function SessionMergePicker({ session, candidates, onCancel, onDone }) {
    const mergeMutation = useMergeSession();
    const [targetSessionId, setTargetSessionId] = useState(candidates[0]?.id || '');

    const submit = useCallback(async () => {
        if (!targetSessionId || targetSessionId === session.id || mergeMutation.isPending) return;
        await mergeMutation.mutateAsync({ id: session.id, targetSessionId });
        onDone();
    }, [mergeMutation, onDone, session.id, targetSessionId]);

    return (
        <div className="flex-1 min-h-0 flex flex-col">
            <div className="p-4 border-b border-gray-800 flex items-center gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                    aria-label="Back to sessions"
                >
                    <ArrowLeft size={18} aria-hidden="true" />
                </button>
                <div className="min-w-0 flex-1">
                    <h3 className="text-white font-semibold truncate">Merge {getSessionName(session)}</h3>
                    <p className="text-xs text-gray-500">
                        Every image moves into the session you pick, and{' '}
                        {getSessionName(session)} is removed.
                    </p>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {candidates.length === 0 ? (
                    <p className="py-10 text-center text-sm text-gray-500">
                        There is no other session to merge into yet.
                    </p>
                ) : (
                    candidates.map((candidate) => (
                        <label
                            key={candidate.id}
                            className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                                targetSessionId === candidate.id
                                    ? 'border-blue-500 bg-blue-500/10'
                                    : 'border-gray-700 bg-gray-800/50 hover:border-gray-600'
                            }`}
                        >
                            <input
                                type="radio"
                                name="merge-target"
                                className="sr-only"
                                value={candidate.id}
                                checked={targetSessionId === candidate.id}
                                onChange={() => setTargetSessionId(candidate.id)}
                            />
                            <SessionCover session={candidate} alt="" />
                            <div className="min-w-0 flex-1">
                                <div className="text-sm font-medium text-white truncate">
                                    {getSessionName(candidate)}
                                </div>
                                <div className="text-xs text-gray-500">
                                    {pluralImages(candidate.image_count ?? 0)}
                                </div>
                            </div>
                        </label>
                    ))
                )}
            </div>

            <div className="p-4 border-t border-gray-800 space-y-3">
                {mergeMutation.error && (
                    <p role="alert" className="text-sm text-red-300">
                        {mergeMutation.error.message || 'Merge failed.'}
                    </p>
                )}
                <div className="flex gap-2">
                    <button
                        type="button"
                        onClick={onCancel}
                        className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg font-medium transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={submit}
                        disabled={!targetSessionId || mergeMutation.isPending}
                        aria-busy={mergeMutation.isPending}
                        className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                    >
                        {mergeMutation.isPending
                            ? <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                            : <Merge size={16} aria-hidden="true" />}
                        Merge into session
                    </button>
                </div>
            </div>
        </div>
    );
}

/**
 * The sessions drawer.
 *
 * Mirrors `CollectionsPanel` (fixed overlay, right-hand sheet, one fetch
 * through React Query). Everything here is server state: sessions and their
 * members live in the query cache, and only the open/closed, editing and
 * picker state is held locally.
 */
export default function SessionPanel({ isOpen, onClose }) {
    const { confirm } = useConfirmation();

    const sessionsQuery = useSessions({}, { enabled: isOpen });
    const sessions = useMemo(() => flattenSessionPages(sessionsQuery.data), [sessionsQuery.data]);

    const createMutation = useCreateSession();
    const renameMutation = useRenameSession();
    const deleteMutation = useDeleteSession();
    const detectMutation = useDetectSessions();

    const detectInFlightRef = useRef(false);
    const [detectSummary, setDetectSummary] = useState(null);
    const [detectError, setDetectError] = useState(null);
    const [newSessionName, setNewSessionName] = useState('');
    const [editingId, setEditingId] = useState(null);
    const [editName, setEditName] = useState('');
    const [splitTargetId, setSplitTargetId] = useState(null);
    const [imagesTargetId, setImagesTargetId] = useState(null);
    const [mergeTargetId, setMergeTargetId] = useState(null);
    const [actionError, setActionError] = useState(null);

    useEffect(() => {
        if (!isOpen) return undefined;
        const onKeyDown = (event) => {
            if (event.key === 'Escape') onClose?.();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isOpen, onClose]);

    const isSplitSession = Boolean(splitTargetId);
    const splitSession = sessions.find((session) => session.id === splitTargetId) || null;
    const imagesSession = sessions.find((session) => session.id === imagesTargetId) || null;
    const mergeSessionRow = sessions.find((session) => session.id === mergeTargetId) || null;
    const mergeCandidates = sessions.filter((session) => session.id !== mergeTargetId);

    const runDetect = useCallback(async () => {
        if (detectInFlightRef.current) return;
        detectInFlightRef.current = true;
        setDetectError(null);
        setDetectSummary(null);
        setActionError(null);
        try {
            const accepted = await confirm({
                title: 'Detect sessions?',
                message:
                    'This scans every generated image for batches that were made together and creates sessions for them. '
                    + 'On a large library it can take a minute. Sessions you have already curated are never modified.',
                confirmText: 'Detect sessions',
                isDangerous: true,
            });
            if (!accepted) return;
            const response = await detectMutation.mutateAsync({});
            setDetectSummary(response?.summary || null);
        } catch (error) {
            setDetectError(error?.message || 'Detection failed.');
        } finally {
            detectInFlightRef.current = false;
        }
    }, [confirm, detectMutation]);

    const handleCreate = useCallback(() => {
        const name = newSessionName.trim();
        if (!name || createMutation.isPending) return;
        createMutation.mutate({ name });
        setNewSessionName('');
    }, [createMutation, newSessionName]);

    const startRename = useCallback((session) => {
        setEditingId(session.id);
        setEditName(typeof session.name === 'string' ? session.name : '');
    }, []);

    const commitRename = useCallback(async (sessionId) => {
        const name = editName.trim();
        setEditingId(null);
        const current = sessions.find((session) => session.id === sessionId);
        if (!name || name === (current?.name ?? '')) return;
        try {
            await renameMutation.mutateAsync({ id: sessionId, name });
        } catch (error) {
            setActionError(error?.message || 'Rename failed.');
        }
    }, [editName, renameMutation, sessions]);

    const handleDelete = useCallback(async (session) => {
        const accepted = await confirm({
            title: 'Delete session?',
            message: `"${getSessionName(session)}" will be removed. The images themselves are not deleted.`,
            confirmText: 'Delete session',
            isDangerous: true,
        });
        if (!accepted) return;
        try {
            await deleteMutation.mutateAsync(session.id);
        } catch (error) {
            setActionError(error?.message || 'Delete failed.');
        }
    }, [confirm, deleteMutation]);

    if (!isOpen) return null;

    const showList = !isSplitSession && !mergeSessionRow && !imagesSession;
    const isListLoading = sessionsQuery.isLoading && sessions.length === 0;
    const hasMoreSessions = sessionsQuery.hasNextPage;

    return (
        <AnimatePresence>
            <div
                key="session-panel"
                className="fixed inset-0 z-40 flex items-start justify-end bg-black/50"
                onClick={onClose}
            >
                <motion.div
                    initial={{ x: '100%' }}
                    animate={{ x: 0 }}
                    exit={{ x: '100%' }}
                    transition={{ type: 'tween', duration: 0.2, ease: 'easeOut' }}
                    onClick={(event) => event.stopPropagation()}
                    className="h-full w-full max-w-md bg-gray-900 border-l border-gray-800 flex flex-col shadow-2xl"
                    role="dialog"
                    aria-label="Sessions"
                >
                    {isSplitSession && splitSession && (
                        <SessionSplitPicker
                            session={splitSession}
                            onCancel={() => setSplitTargetId(null)}
                            onDone={() => setSplitTargetId(null)}
                        />
                    )}

                    {!isSplitSession && !mergeSessionRow && imagesSession && (
                        <SessionImagePicker
                            session={imagesSession}
                            onCancel={() => setImagesTargetId(null)}
                        />
                    )}

                    {!isSplitSession && mergeSessionRow && (
                        <SessionMergePicker
                            session={mergeSessionRow}
                            candidates={mergeCandidates}
                            onCancel={() => setMergeTargetId(null)}
                            onDone={() => setMergeTargetId(null)}
                        />
                    )}

                    {showList && (
                        <>
                            <div className="p-6 border-b border-gray-800">
                                <div className="flex items-center justify-between mb-4">
                                    <div className="flex items-center gap-2">
                                        <Layers className="text-purple-400" size={24} aria-hidden="true" />
                                        <h2 className="text-xl font-bold text-white">Sessions</h2>
                                    </div>
                                    <button
                                        onClick={onClose}
                                        className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                                        aria-label="Close sessions panel"
                                        type="button"
                                    >
                                        <X size={20} aria-hidden="true" />
                                    </button>
                                </div>

                                <form
                                    className="flex gap-2"
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        handleCreate();
                                    }}
                                >
                                    <input
                                        type="text"
                                        value={newSessionName}
                                        onChange={(event) => setNewSessionName(event.target.value)}
                                        placeholder="New session name"
                                        aria-label="New session name"
                                        className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:ring-2 focus:ring-blue-500 outline-none"
                                    />
                                    <button
                                        type="submit"
                                        disabled={!newSessionName.trim() || createMutation.isPending}
                                        className="inline-flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                                    >
                                        <Plus size={16} aria-hidden="true" />
                                        Create
                                    </button>
                                </form>

                                <div className="mt-3 space-y-2">
                                    <DetectButton
                                        onClick={runDetect}
                                        pending={detectMutation.isPending}
                                        className="w-full"
                                    />
                                    {detectError && (
                                        <p role="alert" className="text-sm text-red-300">
                                            {detectError}
                                        </p>
                                    )}
                                    {detectSummary && <DetectResultSummary summary={detectSummary} />}
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto p-4">
                                {actionError && (
                                    <p role="alert" className="mb-3 text-sm text-red-300">
                                        {actionError}
                                    </p>
                                )}

                                {isListLoading && (
                                    <div className="flex items-center justify-center gap-2 py-10 text-gray-400 text-sm">
                                        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                                        Loading sessions…
                                    </div>
                                )}

                                {sessionsQuery.isError && (
                                    <div
                                        role="alert"
                                        className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200"
                                    >
                                        <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                                        <span>
                                            {sessionsQuery.error?.message || 'Could not load your sessions.'}
                                        </span>
                                    </div>
                                )}

                                {!isListLoading && !sessionsQuery.isError && sessions.length === 0 && (
                                    <div className="flex flex-col items-center justify-center text-center py-10">
                                        <div className="w-16 h-16 rounded-2xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center mb-4">
                                            <Layers size={28} className="text-purple-400" aria-hidden="true" />
                                        </div>
                                        <h3 className="text-white font-semibold">No sessions yet</h3>
                                        <p className="text-sm text-gray-400 mt-2 max-w-[19rem]">
                                            Sessions group the images you made together. Detect them from your whole
                                            library, or start one by hand and split it as you go.
                                        </p>
                                        <DetectButton
                                            onClick={runDetect}
                                            pending={detectMutation.isPending}
                                            className="mt-4"
                                        />
                                    </div>
                                )}

                                {sessions.length > 0 && (
                                    <div className="space-y-3">
                                        {sessions.map((session) => (
                                            <div
                                                key={session.id}
                                                className="group relative p-4 rounded-lg border bg-gray-800/50 border-gray-700 hover:border-gray-600 transition-all"
                                            >
                                                <div className="flex items-start gap-3">
                                                    <SessionCover session={session} alt={getSessionName(session)} />
                                                    <div className="flex-1 min-w-0">
                                                        {editingId === session.id ? (
                                                            <input
                                                                type="text"
                                                                value={editName}
                                                                onChange={(event) => setEditName(event.target.value)}
                                                                onBlur={() => commitRename(session.id)}
                                                                onKeyDown={(event) => {
                                                                    if (event.key === 'Enter') commitRename(session.id);
                                                                    if (event.key === 'Escape') setEditingId(null);
                                                                }}
                                                                onClick={(event) => event.stopPropagation()}
                                                                className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                                                                aria-label={`Rename ${getSessionName(session)}`}
                                                                autoFocus
                                                            />
                                                        ) : (
                                                            <div className="font-medium text-white truncate">
                                                                {getSessionName(session)}
                                                            </div>
                                                        )}
                                                        <div className="text-xs text-gray-500">
                                                            {pluralImages(session.image_count ?? 0)}
                                                        </div>
                                                        <div className="text-xs text-gray-500 mt-0.5">
                                                            {formatSessionRange(session.start_at, session.end_at)}
                                                        </div>
                                                        <SessionBadges
                                                            autoDetected={session.auto_detected}
                                                            locked={session.locked}
                                                            className="mt-1.5"
                                                        />
                                                    </div>
                                                </div>

                                                <div className="mt-3 flex flex-wrap gap-1.5">
                                                    <button
                                                        type="button"
                                                        onClick={() => startRename(session)}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded-md transition-colors"
                                                    >
                                                        <Edit2 size={12} aria-hidden="true" />
                                                        Rename
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => setSplitTargetId(session.id)}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded-md transition-colors"
                                                    >
                                                        <Scissors size={12} aria-hidden="true" />
                                                        Split
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => setImagesTargetId(session.id)}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded-md transition-colors"
                                                    >
                                                        <ImageIcon size={12} aria-hidden="true" />
                                                        Images
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => setMergeTargetId(session.id)}
                                                        disabled={sessions.length < 2}
                                                        title={sessions.length < 2
                                                            ? 'Create a second session to merge into'
                                                            : 'Merge into another session'}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed text-gray-300 text-xs rounded-md transition-colors"
                                                    >
                                                        <Merge size={12} aria-hidden="true" />
                                                        Merge
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleDelete(session)}
                                                        disabled={deleteMutation.isPending}
                                                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-gray-800 hover:bg-red-900/50 text-gray-300 hover:text-red-300 text-xs rounded-md transition-colors"
                                                    >
                                                        <Trash2 size={12} aria-hidden="true" />
                                                        Delete
                                                    </button>
                                                </div>
                                            </div>
                                        ))}

                                        {hasMoreSessions && (
                                            <button
                                                type="button"
                                                onClick={() => sessionsQuery.fetchNextPage()}
                                                disabled={sessionsQuery.isFetchingNextPage}
                                                className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-60 text-gray-300 text-sm rounded-lg font-medium transition-colors"
                                            >
                                                {sessionsQuery.isFetchingNextPage && (
                                                    <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                                                )}
                                                Load more sessions
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </motion.div>
            </div>
        </AnimatePresence>
    );
}

/**
 * Session view mode has nothing to group by yet.
 *
 * Rendered in place of the gallery, so the mode never falls through to
 * `GroupedDashboardContent`'s zero-height container and reads as a blank page.
 */
export function SessionViewPlaceholder({ isLoading, error, onOpenPanel }) {
    if (isLoading) {
        return (
            <div className="flex justify-center items-center h-48 text-sm text-gray-400">
                <Loader2 size={16} className="animate-spin mr-2" aria-hidden="true" />
                Loading sessions…
            </div>
        );
    }

    if (error) {
        return (
            <div
                role="alert"
                className="rounded-2xl border border-red-500/40 bg-red-500/10 p-6 text-sm text-red-200 flex items-start gap-2"
            >
                <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                <span>{error.message || 'Could not load your sessions.'}</span>
            </div>
        );
    }

    return (
        <div className="rounded-2xl border border-white/5 bg-gray-800/30 p-10 text-center">
            <div className="w-16 h-16 rounded-2xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center mx-auto mb-4">
                <Layers size={28} className="text-purple-400" aria-hidden="true" />
            </div>
            <h3 className="text-white font-semibold">No sessions to group by</h3>
            <p className="text-sm text-gray-400 mt-2 max-w-md mx-auto">
                Detect sessions from your library, or create one by hand, and they will show up here as
                expandable groups.
            </p>
            <button
                type="button"
                onClick={onOpenPanel}
                className="mt-4 inline-flex items-center gap-2 px-4 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-lg font-medium transition-colors"
            >
                <Layers size={16} aria-hidden="true" />
                Open the sessions panel
            </button>
        </div>
    );
}

/**
 * Dashboard entry point for the feature.
 *
 * `DashboardHeader` owns the `['grid','list','feed','timeline']` toggle and is
 * outside this change set, so the fifth mode is entered from here instead of
 * being silently unreachable.
 */
export function SessionsToolbar({ isSessionView, onOpenPanel, onToggleViewMode }) {
    return (
        <div className="flex items-center gap-2 flex-wrap">
            <button
                type="button"
                onClick={onOpenPanel}
                className="inline-flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg font-medium transition-colors"
            >
                <Layers size={16} aria-hidden="true" />
                Manage sessions
            </button>
            <button
                type="button"
                onClick={onToggleViewMode}
                aria-pressed={isSessionView}
                className={`inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg font-medium transition-colors ${
                    isSessionView
                        ? 'bg-purple-600 text-white hover:bg-purple-500'
                        : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                }`}
            >
                <Layers size={16} aria-hidden="true" />
                {isSessionView ? 'Grouped by session' : 'Group by session'}
            </button>
        </div>
    );
}
