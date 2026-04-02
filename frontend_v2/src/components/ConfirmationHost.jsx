import ConfirmationModal from './ConfirmationModal';
import { useConfirmationStore } from '../store/confirmationStore';

export default function ConfirmationHost() {
    const isOpen = useConfirmationStore((state) => state.isOpen);
    const title = useConfirmationStore((state) => state.title);
    const message = useConfirmationStore((state) => state.message);
    const confirmText = useConfirmationStore((state) => state.confirmText);
    const cancelText = useConfirmationStore((state) => state.cancelText);
    const isDangerous = useConfirmationStore((state) => state.isDangerous);
    const resolveConfirmation = useConfirmationStore((state) => state.resolveConfirmation);

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
