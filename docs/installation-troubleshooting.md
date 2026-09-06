# Installation and plugin troubleshooting

`afriend` has two separate installation surfaces:

- `uv tool install afriend` installs the `afriend` command-line tool.
- A Claude Code marketplace installs the `/afriend`, `review`, `status`,
  `configure`, and `resolve` skills.

The Python wheel contains the portable skill payload used by the command-line
tool. Claude Code marketplaces use the repository's `plugins/` projection, so
they need a durable Git checkout.

## Claude Code: “Marketplace file not found”

If Claude reports that `plugins/.claude-plugin/marketplace.json` is missing,
the configured directory is incomplete. This commonly happens when a
scratchpad or copied directory omits hidden files.

Remove the broken marketplace entry, then add the `plugins/` directory from a
full checkout:

```bash
claude plugin marketplace remove afriend

cd /where/you/keep/repos
git clone https://github.com/livingstaccato/afriend.git
claude plugin marketplace add "$PWD/afriend/plugins"
claude plugin install afriend@afriend
```

If the checkout already exists, refresh it and add its exact `plugins/`
directory instead:

```bash
git -C /path/to/afriend pull --ff-only
claude plugin marketplace add /path/to/afriend/plugins
```

Before adding it, this file must exist:

```bash
test -f /path/to/afriend/plugins/.claude-plugin/marketplace.json
```

Use a stable checkout rather than a scratchpad or temporary directory. After
updating that checkout later, run:

```bash
claude plugin marketplace update afriend
```

## Confirm the active installation

```bash
afriend --version
claude plugin marketplace list
claude plugin list
```

The marketplace listing should show a durable directory ending in
`/afriend/plugins`. The command-line version and the plugin version may be
updated independently.
