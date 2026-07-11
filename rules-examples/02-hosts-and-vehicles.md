# Hosts & Vehicles — Reference

## People

- **<YOUR NAME>** — operator (you). Guest contact: **<YOUR PHONE>**.
- **<HOST ACCOUNT 1>** — host (owner) you co-host for. Outbound messages are
  labeled "<HOST ACCOUNT 1> (Host)". List EVERY host account here AND in
  config.json `host_names` — the bot must recognize their messages (including
  Turo's scheduled/automatic ones) as host messages, never as guest messages.
- Vehicles listed in your own Turo account carry no "(X's vehicle)" label; the
  bot shows them under your `signature` name.

## Per-host rules

- **<HOST ACCOUNT 1>** — e.g. where guests leave the key on return, whether the
  car may be locked from inside, spare-key availability, fuel/charge policy.

## Vehicles

- **<YEAR MAKE MODEL>** — owner, plate (see vehicles.json), key location,
  anything a guest commonly asks about (chargers, toll pass, child seats).
