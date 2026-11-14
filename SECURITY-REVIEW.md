# Security Review

## Scope

Review of player-visible information that could disclose hidden Werewolves roles after the role-privacy change.

## Finding

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟡 MEDIUM | [src/game_logic.py](src/game_logic.py#L210-L215) | 210-215 | The public game-state view removes individual roles but retains the living werewolf count. Comparing count changes with announced eliminations can reveal whether a player eliminated by vote was a werewolf. | 9/10 |

The server broadcasts this public state to all players during the game. The count is derived from hidden roles, so omitting role names alone does not fully protect role privacy. This is an aggregate-state side channel, not a timing attack.

## Recommendation

Omit the living werewolf count from player-facing state during play, or only reveal it after the game ends. Keep the full count in server-side state for win-condition checks.
