import ConfirmationModal from './ConfirmationModal';
import { useConfirmationStore } from '../store/confirmationStore';

export default function ConfirmationHost() {
    const {
        isOpen,
        title,
        message,
        confirmText,
        cancelText,
        isDangerous,
        resolveConfirmation,
    } = useConfirmationStore((state) => ({
        isOpen: state.isOpen,
        title: state.title,
        message: state.message,
        confirmText: state.confirmText,
        cancelText: state.cancelText,
        isDangerous: state.isDangerous,
        resolveConfirmation: state.resolveConfirmation,
    }));

    return (
        <ConfirmationModal
            isOpen={isOpen}
            onClose={() => resolveConfirmation(false)}
            onConfirm={() => resolveConfirmation(true)}
            title={title}
            message={message}
            confirmText={confirmText}
            cancelText={cancelText}
            isDangerous={isDangerous}
        />
    );
}
