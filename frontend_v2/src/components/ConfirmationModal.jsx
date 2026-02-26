import { useId } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { motion as Motion, AnimatePresence } from 'framer-motion';

export default function ConfirmationModal({
    isOpen,
    onClose,
    onCancel,
    onConfirm,
    title = "Confirm Action",
    message = "Are you sure you want to proceed?",
    confirmText = "Confirm",
    cancelText = "Cancel",
    isDangerous = false
}) {
    const titleId = useId();
    const descriptionId = useId();

    const handleCancel = () => {
        if (onCancel) onCancel();
        else if (onClose) onClose();
    };

    const handleConfirm = () => {
        onConfirm();
        handleCancel(); // Close after confirming
    };

    return (
        <AnimatePresence>
            {isOpen && (
                <div
                    className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
                    onClick={handleCancel}
                >
                    <Motion.div
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby={titleId}
                        aria-describedby={descriptionId}
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.15 }}
                        className="bg-gray-900 rounded-xl border border-gray-700 w-full max-w-md shadow-2xl"
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="p-6 space-y-4">
                            <div className="flex items-start gap-4">
                                <div className={`p-3 rounded-full flex-shrink-0 ${isDangerous ? 'bg-red-500/20 text-red-500' : 'bg-blue-500/20 text-blue-500'}`}>
                                    <AlertTriangle size={24} />
                                </div>
                                <div className="flex-1">
                                    <h3 id={titleId} className="text-lg font-bold text-white">{title}</h3>
                                    <p id={descriptionId} className="text-gray-400 mt-1 text-sm leading-relaxed">{message}</p>
                                </div>
                                <button
                                    onClick={handleCancel}
                                    aria-label="Close"
                                    className="text-gray-500 hover:text-white transition-colors"
                                >
                                    <X size={20} />
                                </button>
                            </div>

                            <div className="flex gap-3 pt-2">
                                <button
                                    onClick={handleCancel}
                                    className="flex-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors"
                                >
                                    {cancelText}
                                </button>
                                <button
                                    onClick={handleConfirm}
                                    className={`flex-1 px-4 py-2 rounded-lg font-medium text-white transition-colors ${isDangerous
                                        ? 'bg-red-600 hover:bg-red-500 shadow-lg shadow-red-900/20'
                                        : 'bg-blue-600 hover:bg-blue-500 shadow-lg shadow-blue-900/20'
                                        }`}
                                >
                                    {confirmText}
                                </button>
                            </div>
                        </div>
                    </Motion.div>
                </div>
            )}
        </AnimatePresence>
    );
}
