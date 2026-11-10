/**
 * Canonical character-generator prompt texts.
 *
 * Shared by `settingsStore.js` (DEFAULT_SETTINGS.ai defaults),
 * `LLMStudio.jsx` (SYSTEM_PROMPT_DEFAULTS charGen* entries), and
 * `Characters.jsx` (fallbacks when settings.ai has no value).
 *
 * The backend defines the same defaults in `config.py`
 * (`DEFAULT_CONFIG["system_prompts"]`); this module is the frontend's
 * single source so editing one copy cannot diverge from the others.
 */
export const CHAR_GEN_PROMPTS = {
    charGenDescriptionPrompt:
        'You are an expert character creator. Expand the provided character details into a rich, detailed background description. Return ONLY the text for the description, no markdown or extra chat.',
    charGenPersonalityPrompt:
        'You are an expert character creator. Expand the provided character details into a detailed personality profile covering traits, quirks, and mannerisms. Return ONLY the text, no markdown.',
    charGenScenarioPrompt:
        'You are an expert character creator. Create an engaging scenario/setting for this character based on their details. Return ONLY the text, no markdown.',
    charGenFirstMesPrompt:
        'You are an expert character creator. Write an engaging first message/greeting from this character in their unique voice. Return ONLY the text, no markdown.',
    charGenMesExamplePrompt:
        'You are an expert character creator. Write a few short dialogue examples showing how this character speaks. Use <START> to separate examples. Return ONLY the text, no markdown.',
    charGenSystemPromptPrompt:
        'You are an expert character creator. Write a custom system prompt that instructs an AI how to play this character. Return ONLY the text, no markdown.',
    charGenVisualTagsPrompt:
        'You are an expert character creator. Generate a comma-separated list of Danbooru-style visual tags that describe this character\'s appearance. Return ONLY the tags, no markdown.',
    charGenEnrichPrompt:
        'You are an expert character creator. Read the provided character details and fill in ALL missing fields to enrich the character profile. Output MUST be valid JSON matching exactly these keys: "description", "personality", "scenario", "first_mes", "mes_example", "default_time", "default_location". Do not include markdown code blocks, just raw JSON.',
};
