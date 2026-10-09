import { motion } from 'framer-motion';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Copy, Edit3, ExternalLink, GripVertical, Loader2, MessageSquare, Trash2, User } from 'lucide-react';

import SceneGallery, { SceneCount } from '../SceneGallery';
import { getAvatarUrl } from '../../hooks/useWorldVault';
import CharacterCardExportMenu from './CharacterCardExportMenu';
import CharacterCardSpecBadge from './CharacterCardSpecBadge';

/**
 * One card for a character, shared by the character vault and the avatar
 * gallery.
 *
 * The two call sites used to have separate implementations with different
 * props, different tag limits and (only on the vault side) drag-and-drop.
 * The contract below is the union of what they actually needed, shaped so
 * neither page needs a mode flag:
 *
 *   character  the character record (required)
 *   collection this character's scene collection, i.e. the
 *              `collections[character.id]` entry of the batched query.
 *              Optional: a character with no generated art simply has none.
 *   onChat     (character) => void — required; every card offers "Chat".
 *   onOpen     (character) => void — optional. Presence means "this page can
 *              show you the character", which makes the avatar clickable and
 *              adds the trailing "View" action. The gallery passes it, the
 *              vault does not (it is already showing the character).
 *   actions    optional `{ onEdit, onExport, onClone, onDelete, isCloning }`.
 *              Each key renders its own action and nothing else does, so a
 *              read-only page passes no `actions` at all instead of a
 *              `canEdit={false}`.
 *   drag       optional `{ setNodeRef, style, handleProps, isDragging }`,
 *              supplied by `<SortableCharacterCard>` so that dnd-kit stays
 *              out of this component (and so a page without a DndContext can
 *              still render the card).
 *
 * Drag-and-drop therefore has exactly one implementation:
 * `<SortableCharacterCard>` below, which is the only thing in the app that
 * calls `useSortable` for a character. The reorder itself is still persisted
 * by the vault page through `useReorderCharacters`
 * (`POST /api/v2/characters/reorder`) — no new endpoint.
 */

/**
 * Tags shown before the "+N" overflow marker.
 *
 * 4, not the vault's old 5: the smaller of the two limits is the safer one
 * here because this card is also rendered in the gallery's narrower
 * three-column grid, where a fifth tag wraps onto its own line and pushes
 * the action row down. Overflow beyond the limit is always summarised rather
 * than hidden, so nothing is lost.
 */
const VISIBLE_TAG_LIMIT = 4;

export default function CharacterCard({
    character,
    collection,
    onChat,
    onOpen,
    actions,
    drag,
}) {
    const imageCount = collection?.image_count || 0;
    const images = collection?.images || [];

    const manageActions = actions || {};
    // "Managing" a character means a dense row of five actions, which is why
    // the vault hides it until hover; a card that is only being browsed keeps
    // its two actions visible (and touch has no hover to reveal them with).
    const isManagementCard = Boolean(
        manageActions.onEdit || manageActions.onExport || manageActions.onClone || manageActions.onDelete
    );
    const isDragging = Boolean(drag?.isDragging);

    const avatar = character.has_avatar ? (
        <img src={getAvatarUrl(character.id)} alt={character.name} className="w-full h-full object-cover" />
    ) : (
        <User size={22} className="text-gray-500" />
    );

    const actionButtons = [
        <button
            key="chat"
            type="button"
            onClick={() => onChat(character)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors"
            title="Start chat with this character"
        >
            <MessageSquare size={14} /> Chat
        </button>,
    ];

    if (manageActions.onEdit) {
        actionButtons.push(
            <button
                key="edit"
                type="button"
                onClick={() => manageActions.onEdit(character)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors"
                title="Edit character"
            >
                <Edit3 size={14} /> Edit
            </button>
        );
    }

    if (manageActions.onExport) {
        actionButtons.push(
            <CharacterCardExportMenu
                key="export"
                character={character}
                onExport={manageActions.onExport}
            />
        );
    }

    if (manageActions.onClone) {
        actionButtons.push(
            <button
                key="clone"
                type="button"
                onClick={() => manageActions.onClone(character)}
                disabled={Boolean(manageActions.isCloning)}
                className="flex items-center px-2 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors disabled:opacity-50"
                title="Clone character"
            >
                {manageActions.isCloning ? <Loader2 size={14} className="animate-spin" /> : <Copy size={14} />}
            </button>
        );
    }

    // The trailing action is the one pushed to the far edge: Delete on a
    // management card, View on a browse card, so it is assigned rather than
    // appended.
    let trailingButton = null;

    if (onOpen) {
        trailingButton = (
            <button
                key="open"
                type="button"
                onClick={() => onOpen(character)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors"
                title="Open character"
            >
                <ExternalLink size={14} /> View
            </button>
        );
    }

    if (manageActions.onDelete) {
        trailingButton = (
            <button
                key="delete"
                type="button"
                onClick={() => manageActions.onDelete(character)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 transition-colors"
                title="Delete character"
            >
                <Trash2 size={14} />
            </button>
        );
    }

    return (
        <motion.div
            ref={drag?.setNodeRef}
            style={drag?.style}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`glass-panel rounded-xl border p-4 transition-all group relative ${
                isDragging
                    ? 'border-blue-500/60 shadow-lg shadow-blue-500/10'
                    : 'border-white/5 hover:border-blue-500/30'
            }`}
        >
            {drag?.handleProps && (
                <button
                    type="button"
                    className="absolute -top-1.5 -right-1.5 z-10 p-1 rounded-full bg-gray-800 border border-white/10 text-gray-500 opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto focus-visible:opacity-100 focus-visible:pointer-events-auto hover:text-white hover:bg-gray-700 transition-all cursor-grab active:cursor-grabbing"
                    aria-label={`Reorder ${character.name}`}
                    {...drag.handleProps}
                >
                    <GripVertical size={13} />
                </button>
            )}
            <div className="flex items-start gap-3">
                {onOpen ? (
                    <button
                        type="button"
                        onClick={() => onOpen(character)}
                        title={`Open ${character.name}`}
                        aria-label={`Open ${character.name}`}
                        className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden cursor-pointer hover:border-blue-500/40 transition-colors"
                    >
                        {avatar}
                    </button>
                ) : (
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden">
                        {avatar}
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-100 truncate">{character.name}</h3>
                    {character.description && (
                        <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{character.description}</p>
                    )}
                </div>
            </div>

            {character.personality && (
                <p className="text-xs text-gray-500 mt-3 line-clamp-2 italic">"{character.personality}"</p>
            )}

            {(character.card_spec || character.card_metadata) && (
                <div className="mt-3">
                    <CharacterCardSpecBadge character={character} />
                </div>
            )}

            {character.visual_tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-3">
                    {character.visual_tags.slice(0, VISIBLE_TAG_LIMIT).map((tag, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 text-xs bg-purple-500/10 text-purple-400 rounded border border-purple-500/20">{tag}</span>
                    ))}
                    {character.visual_tags.length > VISIBLE_TAG_LIMIT && (
                        <span className="px-1.5 py-0.5 text-xs text-gray-500">+{character.visual_tags.length - VISIBLE_TAG_LIMIT}</span>
                    )}
                </div>
            )}

            {imageCount > 0 && (
                <div className="mt-3">
                    <SceneCount count={imageCount} />
                    <div className="max-h-28 overflow-y-auto custom-scrollbar rounded-lg">
                        <SceneGallery images={images} compact />
                    </div>
                </div>
            )}

            <div
                // Hidden means not tappable. Both reasons this row ever disappears
                // are hover-shaped, so it is gated on the device actually having
                // hover rather than on a width:
                //   * `sm:` matches an iPad at 1024px, which is a touch device.
                //     The Delete button was invisible there but kept its
                //     hit area, so a tap near the card's corner could delete a
                //     character the user could not see.
                //   * `pointer-events-none` while faded means the same hazard
                //     cannot come back through a future hover variant that the
                //     media query misses; `group-hover`/`focus-visible` restore
                //     both paint and pointer events together, so hovering the
                //     card is still what reveals it.
                className={`flex items-center gap-2 mt-4 transition-opacity ${
                    isManagementCard
                        ? 'opacity-100 sm:[@media(hover:hover)]:opacity-0 sm:[@media(hover:hover)]:group-hover:opacity-100 sm:[@media(hover:hover)]:pointer-events-none sm:[@media(hover:hover)]:group-hover:pointer-events-auto sm:[@media(hover:hover)]:focus-within:opacity-100 sm:[@media(hover:hover)]:focus-within:pointer-events-auto'
                        : 'opacity-100'
                }`}
            >
                {actionButtons}
                {trailingButton && <div className="ml-auto flex items-center gap-2">{trailingButton}</div>}
            </div>
        </motion.div>
    );
}

/**
 * dnd-kit adapter for the character vault's sortable grid.
 *
 * Keeps `useSortable` out of the presentational card so that a page with no
 * `DndContext` (the avatar gallery) can render the same card, and keeps the
 * reordering *persisting* in the page, which owns the
 * `useReorderCharacters` mutation — this only reports the drag state.
 */
export function SortableCharacterCard(props) {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: props.character.id,
    });

    return (
        <CharacterCard
            {...props}
            drag={{
                setNodeRef,
                isDragging,
                style: {
                    transform: CSS.Transform.toString(transform),
                    transition,
                    opacity: isDragging ? 0.5 : 1,
                    zIndex: isDragging ? 50 : undefined,
                },
                handleProps: { ...attributes, ...listeners },
            }}
        />
    );
}
