import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { X } from 'lucide-react';

const SIZE_CLASSES = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    full: 'max-w-4xl',
};

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
    useEffect(() => {
        if (!isOpen) return undefined;
        const onKey = (e) => {
            if (e.key === 'Escape') onClose?.();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    const panelSize = SIZE_CLASSES[size] || SIZE_CLASSES.md;

    return createPortal(
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80"
            onClick={closeOnBackdrop ? onClose : undefined}
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
        </div>,
        document.body
    );
}

export default Modal;
