# Rule templates

The bot grounds **every draft** in all `rules/*.md` files (loaded in filename
order). These templates show the expected structure — copy them and fill in your
own operation's facts:

```bash
cp rules-examples/*.md rules/
# then edit each file in rules/ with your names, addresses, policies
```

`rules/` holds your private operational data (addresses, phone numbers, key
locations) — it is gitignored in a fresh checkout and must never be committed to
a public repository.

`rules/07-learned.md` is created automatically the first time you use the
🎓 Teach button and grows with every lesson; edit or prune it freely.
