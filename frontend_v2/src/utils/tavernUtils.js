/**
 * Tavern Utilities
 * 
 * SillyTavern-compatible template variable substitution and message parsing.
 * 
 * Supported variables:
 *   {{user}}            - The user's persona name (defaults to "User")
 *   {{char}}            - The character's name
 *   {{persona}}         - The user's persona description
 *   {{original}}        - Original system prompt text (passed explicitly)
 *   {{time}}            - Current local time (HH:MM format)
 *   {{date}}            - Current local date (YYYY-MM-DD format)
 *   {{random::a::b::c}} - Randomly pick one of the given options
 *   {{roll::NdX}}       - Roll N dice of X sides and sum them
 * 
 * Message segment types (from parseTavernMessage):
 *   "action"  - text wrapped in *asterisks* (narration, actions, expressions)
 *   "speech"  - text wrapped in "double quotes" (spoken dialogue)
 *   "prose"   - everything else (plain narrative text)
 */

/**
 * Substitute SillyTavern-compatible template variables in a string.
 * 
 * @param {string} text - Raw text potentially containing {{variables}}
 * @param {Object} vars - Variable values to substitute
 * @param {string} [vars.user="User"] - The user's persona name
 * @param {string} [vars.char=""] - The character's name
 * @param {string} [vars.persona=""] - The user's persona description
 * @param {string} [vars.original=""] - The original system prompt text
 * @returns {string} Text with variables substituted
 */
export function substituteTemplateVars(text, vars = {}) {
    if (!text || typeof text !== 'string') return text || '';

    const {
        user = 'User',
        char = '',
        persona = '',
        original = '',
    } = vars;

    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const dateStr = now.toISOString().slice(0, 10);

    return text.replace(/\{\{([^}]+)\}\}/g, (match, inner) => {
        const trimmed = inner.trim();

        // Simple named variables
        switch (trimmed.toLowerCase()) {
            case 'user':       return user;
            case 'char':       return char;
            case 'persona':    return persona;
            case 'original':   return original;
            case 'time':       return timeStr;
            case 'date':       return dateStr;
        }

        // {{random::option1::option2::...}}
        if (trimmed.toLowerCase().startsWith('random::')) {
            const options = trimmed.slice('random::'.length).split('::').map(o => o.trim()).filter(Boolean);
            if (options.length > 0) {
                return options[Math.floor(Math.random() * options.length)];
            }
            return match;
        }

        // {{roll::NdX}} - dice roll
        if (trimmed.toLowerCase().startsWith('roll::')) {
            const rollStr = trimmed.slice('roll::'.length).trim();
            const rollMatch = rollStr.match(/^(\d+)d(\d+)$/i);
            if (rollMatch) {
                const count = parseInt(rollMatch[1], 10);
                const sides = parseInt(rollMatch[2], 10);
                if (count > 0 && sides > 0 && count <= 100 && sides <= 1000) {
                    let total = 0;
                    for (let i = 0; i < count; i++) {
                        total += Math.floor(Math.random() * sides) + 1;
                    }
                    return String(total);
                }
            }
            return match;
        }

        // Unknown variable - leave as-is
        return match;
    });
}


/**
 * Parse a SillyTavern-style roleplay message into typed segments.
 * 
 * Segments:
 *   { type: 'action', content: '...' }  - *narration / action text* (italic)
 *   { type: 'speech', content: '...' }  - "spoken dialogue" (quoted)
 *   { type: 'prose',  content: '...' }  - plain narrative prose
 * 
 * @param {string} text - Raw message text from LLM / character card
 * @returns {Array<{type: string, content: string}>} Parsed segments
 */
export function parseTavernMessage(text) {
    if (!text || typeof text !== 'string') return [];

    const segments = [];
    let remaining = text;

    while (remaining.length > 0) {
        // Try to match *action*
        const actionMatch = remaining.match(/^\*([^*]+)\*/);
        if (actionMatch) {
            const content = actionMatch[1].trim();
            if (content) segments.push({ type: 'action', content });
            remaining = remaining.slice(actionMatch[0].length);
            continue;
        }

        // Try to match "speech"
        const speechMatch = remaining.match(/^"((?:[^"\\]|\\.)*)"/);
        if (speechMatch) {
            const content = speechMatch[1].trim();
            if (content) segments.push({ type: 'speech', content });
            remaining = remaining.slice(speechMatch[0].length);
            continue;
        }

        // Consume up to the next * or "
        const nextSpecial = remaining.search(/[*"]/);
        if (nextSpecial === -1) {
            // Rest is prose
            const content = remaining.trim();
            if (content) segments.push({ type: 'prose', content });
            break;
        } else if (nextSpecial > 0) {
            const content = remaining.slice(0, nextSpecial).trim();
            if (content) segments.push({ type: 'prose', content });
            remaining = remaining.slice(nextSpecial);
        } else {
            // Dangling * or " not forming a pair - treat as prose char
            segments.push({ type: 'prose', content: remaining[0] });
            remaining = remaining.slice(1);
        }
    }

    // Merge adjacent same-type segments
    const merged = [];
    for (const seg of segments) {
        if (merged.length > 0 && merged[merged.length - 1].type === seg.type) {
            merged[merged.length - 1].content += ' ' + seg.content;
        } else {
            merged.push({ ...seg });
        }
    }

    return merged.length > 0 ? merged : [{ type: 'prose', content: text }];
}


/**
 * Convenience: Apply template substitution to all string fields of a character card.
 * Useful when loading character cards before display or LLM submission.
 * 
 * @param {Object} character - Character entity from the backend
 * @param {Object} vars - Template variable values (user, persona, etc.)
 * @returns {Object} New character object with substituted fields
 */
export function substituteCharacterTemplates(character, vars = {}) {
    if (!character) return character;

    const effectiveVars = {
        char: character.name || '',
        ...vars,
    };

    return {
        ...character,
        description: substituteTemplateVars(character.description, effectiveVars),
        personality: substituteTemplateVars(character.personality, effectiveVars),
        scenario: substituteTemplateVars(character.scenario, effectiveVars),
        first_mes: substituteTemplateVars(character.first_mes, effectiveVars),
        mes_example: substituteTemplateVars(character.mes_example, effectiveVars),
        system_prompt: substituteTemplateVars(character.system_prompt, effectiveVars),
    };
}
