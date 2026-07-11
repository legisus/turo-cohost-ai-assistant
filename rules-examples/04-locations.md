# Location gating

> The conversation the bot reads begins with the trip's real pickup/drop-off
> location line ("📍 Trip pickup/drop-off location: ..."). Rules in this file
> must state clearly WHICH location they apply to — the bot is instructed to
> use instructions gated to a location ONLY when the trip's location matches.

## <LOCATION A — e.g. home base street parking>

- Exact parking description, permitted sides/hours, key handoff.

## <LOCATION B — e.g. airport lot>

- Lot name and address, shuttle instructions, what to tell the guest on
  landing. Never send these steps for trips at other locations.
