# Player board parity snapshot refresh

This report records the intentional render changes merged in `feat/player-board-polish` and the CI setup needed to run the repository's full Node test gate.

## Render changes

The five refreshed NFL render snapshots capture the player board changes from commit `fa787117`:

- Card markup adds `quoted-card` or `research-card` so each card can use the appropriate responsive layout.
- The position filter summary appears in the captured page state.
- The live edge preview status and list appear in the captured page state.

The evaluation, projection, ledger, breaker configuration, detail modal, and DOM access snapshots did not change. No model outputs or betting decisions were re-baselined.

## CI setup and verification

The root `node --test` command discovers tests under `extensions/`. CI now installs that directory's locked workspace dependencies before running the production gate; otherwise imports of `@propstein/core` fail before those tests execute.

Refresh command: `PW_UPDATE_SNAPSHOTS=1 node --test test/nfl-parity.snapshot.mjs`.

Verification after the refresh: `npm run check:production` passed all 243 tests with the extension dependencies installed. The icon refresh also passed the 16, 32, 180, 192, and 512 px asset checks and the 100 root test files.
