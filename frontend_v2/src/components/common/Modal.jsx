import React from 'react';
import { motion } from 'framer-motion';
import { X } from 'lucide-react';
import ModalOverlay from './ModalOverlay';

const SIZE_CLASSES = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    full: 'max-w-4xl',
};

/**
 * ModalOverlay + title/close-button/footer chrome.
 *
 * The direction of the relationship: <ModalOverlay> owns the backdrop layer
 * (portal, topmost-wins Escape, backdrop click) and <Modal> is the opinionated
 * wrapper on top of it for the dialogs that want a title bar, a close button
 * and a footer. A dialog with its own header/footer structure should use
 * <ModalOverlay> directly rather than pretending to be a <Modal>.
 *
 * This used to carry its own `useEffect` keydown listener and its own
 * createPortal, which meant it was not part of the Escape registry: with a
 * <Modal> stacked over another dialog, one Escape closed both. Building it on
 * <ModalOverlay> puts it in the registry like everything else.
 */
export function Modal({
    isOpen,
    onClose,
    title,
    size = 'md',
    children,
    footer,
    closeOnBackdrop = true,
    showClose = true,
    className = '',
}) {
    if (!isOpen) return null;

    const panelSize = SIZE_CLASSES[size] || SIZE_CLASSES.md;

    return (
        <ModalOverlay
            isOpen={isOpen}
            onClose={onClose}
            closeOnBackdrop={closeOnBackdrop}
            className="z-50 bg-black/80"
        >
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.2 }}
                onClick={(e) => e.stopPropagation()}
                className={`glass rounded-2xl w-full ${panelSize} flex flex-col ${className}`}
            >
                {(title || showClose) && (
                    <div className="p-6 border-b border-gray-700/50">
                        <div className="flex items-center justify-between">
                            <h2 className="text-xl font-bold text-white">{title}</h2>
                            {showClose && (
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-700/50 rounded-full text-gray-400 hover:text-white transition-colors"
                                    aria-label="Close modal"
                                >
                                    <X size={20} aria-hidden="true" />
                                </button>
                            )}
                        </div>
                    </div>
                )}
                {children}
                {footer && <div className="p-4 border-t border-gray-700/50">{footer}</div>}
            </motion.div>
        </ModalOverlay>
    );
}

export default Modal;
