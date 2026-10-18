export const COMMANDS = [
    { cmd: '/silent', desc: 'Send silently without triggering AI reply', icon: '🤫', argPlaceholder: 'Message text...' },
    { cmd: '/story', desc: 'Insert a narrative event', icon: '📖', argPlaceholder: 'Story text...' },
    { cmd: '/puppet', desc: 'Speak as the character', icon: '🎭', argPlaceholder: 'Character speech...' },
    { cmd: '/impersonate', desc: 'Speak as the character (alias of /puppet)', icon: '🎭', argPlaceholder: 'Character speech...' },
    { cmd: '/me', desc: 'Perform a roleplay action', icon: '🏃', argPlaceholder: 'Action description...' },
    { cmd: '/action', desc: 'Perform an action (alias of /me)', icon: '🏃', argPlaceholder: 'Action description...' },
    { cmd: '/time', desc: 'Update story time', icon: '⏰', argPlaceholder: 'e.g. Midnight, +2 hours...' },
    { cmd: '/fastforward', desc: 'Update story time (alias of /time)', icon: '⏰', argPlaceholder: 'e.g. Midnight, +2 hours...' },
    { cmd: '/location', desc: 'Update story location', icon: '📍', argPlaceholder: 'e.g. The Library...' },
    { cmd: '/steer', desc: 'Attach a turn directive to guide the next response', icon: '🎯', argPlaceholder: 'e.g. Escalate drama, speak hesitantly...' },
    { cmd: '/directive', desc: 'Alias of /steer', icon: '🎯', argPlaceholder: 'e.g. Escalate drama, speak hesitantly...' },
    { cmd: '/suggest', desc: 'Auto-fill a suggested response', icon: '🪄', noArgs: true }
];
