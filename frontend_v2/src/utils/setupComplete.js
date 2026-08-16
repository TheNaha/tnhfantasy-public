export const SETUP_COMPLETE_KEY = 'tnhcomfy_setup_complete';

export function isSetupComplete() {
    try {
        return JSON.parse(localStorage.getItem(SETUP_COMPLETE_KEY)) === true;
    } catch {
        return false;
    }
}

export function markSetupComplete() {
    localStorage.setItem(SETUP_COMPLETE_KEY, JSON.stringify(true));
}