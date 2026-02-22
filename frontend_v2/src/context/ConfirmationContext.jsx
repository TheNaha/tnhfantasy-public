import { createContext, useContext, useState, useCallback } from 'react';
import ConfirmationModal from '../components/ConfirmationModal';

/**
 * Global Confirmation Context
 * Provides a unified way to show confirmation dialogs across the app
 * without needing local state management in each component.
 */

const ConfirmationContext = createContext(null);

export function ConfirmationProvider({ children }) {
    const [state, setState] = useState({
        isOpen: false,
        title: 'Confirm Action',
        message: 'Are you sure you want to proceed?',
        confirmText: 'Confirm',
        cancelText: 'Cancel',
        isDangerous: false,
        onConfirm: null,
    });

    const confirm = useCallback(({
        title = 'Confirm Action',
        message = 'Are you sure you want to proceed?',
        confirmText = 'Confirm',
        cancelText = 'Cancel',
        isDangerous = false,
    }) => {
        return new Promise((resolve) => {
            setState({
                isOpen: true,
                title,
                message,
                confirmText,
                cancelText,
                isDangerous,
                onConfirm: () => {
                    setState(prev => ({ ...prev, isOpen: false }));
                    resolve(true);
                },
                onCancel: () => {
                    setState(prev => ({ ...prev, isOpen: false }));
                    resolve(false);
                },
            });
        });
    }, []);

    const handleClose = useCallback(() => {
        setState(prev => ({ ...prev, isOpen: false }));
        if (state.onCancel) state.onCancel();
    }, [state.onCancel]);

    return (
        <ConfirmationContext.Provider value={{ confirm }}>
            {children}
            <ConfirmationModal
                isOpen={state.isOpen}
                onClose={handleClose}
                onConfirm={state.onConfirm}
                title={state.title}
                message={state.message}
                confirmText={state.confirmText}
                cancelText={state.cancelText}
                isDangerous={state.isDangerous}
            />
        </ConfirmationContext.Provider>
    );
}

/**
 * Hook to access the confirmation dialog
 * 
 * Usage:
 * const { confirm } = useConfirmation();
 * 
 * const handleDelete = async () => {
 *     const confirmed = await confirm({
 *         title: 'Delete Item',
 *         message: 'This cannot be undone.',
 *         isDangerous: true
 *     });
 *     if (confirmed) {
 *         // proceed with delete
 *     }
 * };
 */
export function useConfirmation() {
    const context = useContext(ConfirmationContext);
    if (!context) {
        throw new Error('useConfirmation must be used within a ConfirmationProvider');
    }
    return context;
}
