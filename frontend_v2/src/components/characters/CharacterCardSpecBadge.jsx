import { ShieldQuestion } from 'lucide-react';
import { cardSpecLabel, preservedCardMetadataGroups } from '../../api/characterCards';

/**
 * Provenance badge for an imported character card.
 *
 * Shows which card spec the character came from and, when the backend kept
 * fields that have no column in the vault, which groups of card data are
 * preserved in `card_metadata` (and therefore survive a re-export).
 */
export default function CharacterCardSpecBadge({ character }) {
    const specLabel = cardSpecLabel(character?.card_spec, character?.card_spec_version);
    const groups = preservedCardMetadataGroups(character?.card_metadata);
    if (!specLabel && groups.length === 0) return null;

    const metadataTitle = groups
        .map((group) => `Preserved ${group.label}: ${group.keys.join(', ')}`)
        .join('\n');

    return (
        <div className="flex flex-wrap gap-1" data-testid="card-spec-badge">
            {specLabel && (
                <span
                    className="px-1.5 py-0.5 text-xs bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 rounded"
                    title={`Imported card spec: ${character.card_spec}${character.card_spec_version ? ` ${character.card_spec_version}` : ''}`}
                >
                    {specLabel} card
                </span>
            )}
            {groups.length > 0 && (
                <span
                    className="flex items-center gap-1 px-1.5 py-0.5 text-xs bg-emerald-500/10 text-emerald-300 border border-emerald-500/25 rounded"
                    title={metadataTitle}
                >
                    <ShieldQuestion size={10} aria-hidden="true" />
                    {`${groups.length} metadata ${groups.length === 1 ? 'group' : 'groups'}`}
                </span>
            )}
        </div>
    );
}
