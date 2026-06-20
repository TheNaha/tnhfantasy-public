import { Image as ImageIcon } from 'lucide-react';

/**
 * GeneratorFloatingButton Component
 * @param {object} props
 * @param {() => void} props.onClick - Handler to navigate to the generator
 */
export default function GeneratorFloatingButton({ onClick }) {
    return (
        <button
            onClick={onClick}
            className="fixed bottom-6 right-6 z-40 md:hidden bg-blue-600 hover:bg-blue-500 text-white p-4 rounded-full shadow-lg transition-all transform hover:scale-110 flex items-center gap-2"
            title="Go to Generator"
            aria-label="Go to Generator"
            type="button"
        >
            <ImageIcon size={24} />
        </button>
    );
}
