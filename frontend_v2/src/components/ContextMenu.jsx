import { useState, useCallback, useRef, useEffect, memo } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Copy, Download, FolderPlus, Eye, Trash2,
    Sparkles, Share2, FolderOpen, CopyPlus
} from 'lucide-react';

const MotionDiv = motion.div;

const DropdownMenu = memo(function DropdownMenu({
    actions,
    position,
    containerRef,
    handleAction,
}) {
    // Adjust position to stay within viewport
    const menuWidth = 200;
    const menuHeight = actions.length * 44 + 16;

    let x = position.x;
    let y = position.y;

    if (x + menuWidth > window.innerWidth) {
        x = window.innerWidth - menuWidth - 10;
    }
    if (y + menuHeight > window.innerHeight) {
        y = window.innerHeight - menuHeight - 10;
    }

    return (
        <MotionDiv
            ref={containerRef}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.1 }}
            className="fixed z-50 bg-gray-900 border border-gray-700 rounded-lg shadow-xl py-2 min-w-[180px]"
            style={{ left: x, top: y }}
        >
            {actions.map((action, idx) => (
                <button
                    key={idx}
                    onClick={() => handleAction(action)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors ${action.danger
                            ? 'text-red-400 hover:bg-red-500/20'
                            : 'text-gray-300 hover:bg-gray-800'
                        }`}
                >
                    {action.icon && <action.icon size={16} />}
                    {action.label}
                </button>
            ))}
        </MotionDiv>
    );
});

const BottomSheet = memo(function BottomSheet({
    actions,
    containerRef,
    handleAction,
    handleClose,
}) {
    return (
        <>
            {/* Backdrop */}
            <MotionDiv
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-40 bg-black/60"
                onClick={handleClose}
            />

            {/* Sheet */}
            <MotionDiv
                ref={containerRef}
                initial={{ y: '100%' }}
                animate={{ y: 0 }}
                exit={{ y: '100%' }}
                transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                drag="y"
                dragConstraints={{ top: 0 }}
                dragElastic={0.2}
                onDragEnd={(_, info) => {
                    if (info.offset.y > 100) handleClose();
                }}
                className="fixed bottom-0 left-0 right-0 z-50 bg-gray-900 rounded-t-2xl border-t border-gray-700"
            >
                {/* Handle */}
                <div className="flex justify-center py-3">
                    <div className="w-10 h-1 bg-gray-600 rounded-full" />
                </div>

                {/* Actions */}
                <div className="px-4 pb-8 space-y-1">
                    {actions.map((action, idx) => (
                        <button
                            key={idx}
                            onClick={() => handleAction(action)}
                            className={`w-full flex items-center gap-4 px-4 py-4 text-base text-left rounded-xl transition-colors ${action.danger
                                    ? 'text-red-400 hover:bg-red-500/20'
                                    : 'text-white hover:bg-gray-800'
                                }`}
                        >
                            {action.icon && <action.icon size={20} />}
                            <span className="font-medium">{action.label}</span>
                        </button>
                    ))}

                    {/* Cancel button for mobile */}
                    <button
                        onClick={handleClose}
                        className="w-full flex items-center justify-center gap-2 px-4 py-4 mt-2 text-base text-gray-400 bg-gray-800 rounded-xl"
                    >
                        Cancel
                    </button>
                </div>
            </MotionDiv>
        </>
    );
});

/**
 * ContextMenu - Adaptive context menu component.
 * Desktop: Right-click dropdown positioned at cursor
 * Mobile: Long-press bottom sheet with drag-to-dismiss
 * 
 * @param {Object} props
 * @param {React.ReactNode} props.children - Element that triggers context menu
 * @param {Array} props.actions - Array of action objects { icon, label, onClick, danger }
 * @param {boolean} props.disabled - Disable context menu
 */
const ContextMenu = memo(function ContextMenu({
    children,
    actions = [],
    disabled = false
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [position, setPosition] = useState({ x: 0, y: 0 });
    const [isMobile, setIsMobile] = useState(false);
    const longPressTimer = useRef(null);
    const containerRef = useRef(null);

    // Detect mobile
    useEffect(() => {
        const checkMobile = () => setIsMobile(window.innerWidth < 768);
        checkMobile();
        window.addEventListener('resize', checkMobile);
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Handle right-click (desktop)
    const handleContextMenu = useCallback((e) => {
        if (disabled || isMobile) return;
        e.preventDefault();
        e.stopPropagation();
        setPosition({ x: e.clientX, y: e.clientY });
        setIsOpen(true);
    }, [disabled, isMobile]);

    // Handle long-press start (mobile)
    const handleTouchStart = useCallback(() => {
        if (disabled || !isMobile) return;

        longPressTimer.current = setTimeout(() => {
            // Haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(50);
            setIsOpen(true);
        }, 400); // 400ms long-press
    }, [disabled, isMobile]);

    // Handle touch end/cancel
    const handleTouchEnd = useCallback(() => {
        if (longPressTimer.current) {
            clearTimeout(longPressTimer.current);
            longPressTimer.current = null;
        }
    }, []);

    // Handle touch move (cancel long-press if user moves finger)
    const handleTouchMove = useCallback(() => {
        handleTouchEnd();
    }, [handleTouchEnd]);
    useEffect(() => {
        return () => {
            clearTimeout(longPressTimer.current);
            longPressTimer.current = null;
        };
    }, []);

    // Close menu
    const handleClose = useCallback(() => {
        setIsOpen(false);
    }, []);

    // Handle action click
    const handleAction = useCallback((action) => {
        action.onClick?.();
        handleClose();
    }, [handleClose]);

    // Close on click outside
    useEffect(() => {
        if (!isOpen) return;

        const handleClickOutside = (e) => {
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                handleClose();
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('touchstart', handleClickOutside);

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('touchstart', handleClickOutside);
        };
    }, [isOpen, handleClose]);

    // Close on escape
    useEffect(() => {
        if (!isOpen) return;

        const handleEscape = (e) => {
            if (e.key === 'Escape') handleClose();
        };

        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, handleClose]);

    return (
        <>
            {/* Trigger element */}
            <div
                onContextMenu={handleContextMenu}
                onTouchStart={handleTouchStart}
                onTouchEnd={handleTouchEnd}
                onTouchMove={handleTouchMove}
                onTouchCancel={handleTouchEnd}
            >
                {children}
            </div>

            {/* Menu portal */}
            {createPortal(
                <AnimatePresence>
                    {isOpen && (
                        isMobile ? (
                            <BottomSheet
                                actions={actions}
                                containerRef={containerRef}
                                handleAction={handleAction}
                                handleClose={handleClose}
                            />
                        ) : (
                            <DropdownMenu
                                actions={actions}
                                position={position}
                                containerRef={containerRef}
                                handleAction={handleAction}
                            />
                        )
                    )}
                </AnimatePresence>,
                document.body
            )}
        </>
    );
});


/**
 * Helper to create standard image actions
 */
// eslint-disable-next-line react-refresh/only-export-components
export const createImageActions = ({
    onCopySeed,
    onDownload,
    onAddToCollection,
    onViewParams,
    onRemix,
    onShare,
    onDelete,
    onMoveAsset,
    onCopyAsset,
}) => {
    const actions = [];

    if (onCopySeed) {
        actions.push({ icon: Copy, label: 'Copy Seed', onClick: onCopySeed });
    }
    if (onDownload) {
        actions.push({ icon: Download, label: 'Download', onClick: onDownload });
    }
    if (onViewParams) {
        actions.push({ icon: Eye, label: 'View Parameters', onClick: onViewParams });
    }
    if (onRemix) {
        actions.push({ icon: Sparkles, label: 'Remix', onClick: onRemix });
    }
    if (onAddToCollection) {
        actions.push({ icon: FolderPlus, label: 'Add to Collection', onClick: onAddToCollection });
    }
    if (onMoveAsset) {
        actions.push({ icon: FolderOpen, label: 'Move to...', onClick: onMoveAsset });
    }
    if (onCopyAsset) {
        actions.push({ icon: CopyPlus, label: 'Copy to...', onClick: onCopyAsset });
    }
    if (onShare) {
        actions.push({ icon: Share2, label: 'Share', onClick: onShare });
    }
    if (onDelete) {
        actions.push({ icon: Trash2, label: 'Delete', onClick: onDelete, danger: true });
    }

    return actions;
};

export default ContextMenu;
