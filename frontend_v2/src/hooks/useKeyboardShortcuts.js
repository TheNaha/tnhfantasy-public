import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

/**
 * Custom hook to handle global keyboard shortcuts
 * 
 * Shortcuts:
 * - D: Navigate to Dashboard
 * - G: Navigate to Generate page
 * - M: Navigate to Models page
 * - A: Navigate to Advanced page
 * - C: Navigate to Direct ComfyUI page
 * - ?: Show keyboard shortcuts help (console log for now)
 * - Escape: Close modals (via callback)
 */
export const useKeyboardShortcuts = ({ onEscape, onShowHelp } = {}) => {
    const navigate = useNavigate();
    const location = useLocation();

    useEffect(() => {
        const handleKeyPress = (e) => {
            // Ignore if modifier keys are held (allow Ctrl+C, Ctrl+V, etc.)
            if (e.ctrlKey || e.metaKey || e.altKey) {
                return;
            }

            // Ignore if user is typing in an input/textarea
            if (
                e.target.tagName === 'INPUT' ||
                e.target.tagName === 'TEXTAREA' ||
                e.target.isContentEditable
            ) {
                // Still allow Escape to work
                if (e.key === 'Escape' && onEscape) {
                    onEscape();
                }
                return;
            }

            // Handle shortcuts
            switch (e.key.toLowerCase()) {
                case 'g':
                    if (location.pathname !== '/generate') {
                        navigate('/generate');
                    }
                    break;
                case 'd':
                    if (location.pathname !== '/') {
                        navigate('/');
                    }
                    break;
                case 'm':
                    if (location.pathname !== '/models') {
                        navigate('/models');
                    }
                    break;
                case 'a':
                    if (location.pathname !== '/advanced') {
                        navigate('/advanced');
                    }
                    break;
                case 'c':
                    if (location.pathname !== '/comfy') {
                        navigate('/comfy');
                    }
                    break;
                case '?':
                    // Show keyboard shortcuts help
                    if (onShowHelp) {
                        onShowHelp();
                    }
                    break;
                case 'escape':
                    if (onEscape) {
                        onEscape();
                    }
                    break;
                default:
                    break;
            }
        };

        window.addEventListener('keydown', handleKeyPress);
        return () => window.removeEventListener('keydown', handleKeyPress);
    }, [navigate, location, onEscape, onShowHelp]);
}

export default useKeyboardShortcuts;
