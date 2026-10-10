# pyaur

🌐 [Magyar](README.md) · **English** · [Deutsch](README.de.md) · [Polski](README.pl.md)

**A minimalist, security-focused AUR helper written in Python. An alternative to `yay` and `paru`.**

`pyaur` is a single Python file that uses only the standard library. It installs, upgrades,
searches and removes packages from the [Arch User Repository](https://aur.archlinux.org).
It accepts the familiar pacman-style flags (`-S`, `-Ss`, `-Syu`, `-R`…) and includes a simple
`curses` TUI. The main design goal is that **no foreign code runs before you have reviewed it**.

> ⚠️ AUR packages are uploaded by users and **nobody** vets them. A PKGBUILD is a bash
> script that runs on your machine. `pyaur` helps you review it, but it does not do the
> review for you.

> ℹ️ The program's interface and messages are in Hungarian.

---

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Options](#options)
- [TUI](#tui)
- [Security model](#security-model)
- [How an installation works](#how-an-installation-works)
- [Environment variables](#environment-variables)
- [Exit codes](#exit-codes)
- [Limitations](#limitations)
- [License](#license)

---

## Features

- **Installation** from the AUR with recursive dependency resolution (including AUR → AUR
  dependencies), correct build order and split package support.
- **Official repository detection**: if a requested package is in an official repository,
  `pacman` installs it instead of building it from the AUR.
- **System upgrade** (`-Syu`): runs `pacman -Syu` first, then upgrades the AUR packages,
  which avoids partial upgrades. `-Sua` upgrades only the AUR packages.
- **Search** (`-Ss`), sorted by popularity. Installed, out-of-date and orphaned packages are
  marked, and several search fields are available (`--by maintainer`, `--by provides`…).
- **Package info** (`-Si`) with dates, maintainer and risk indicators.
- **Update listing** (`-Qu`): lists available updates without installing anything, so it
  also works in scripts.
- **Orphaned dependency** removal (`-Qdt` / `-Yc`).
- **PKGBUILD download** (`-G`) or printing (`-Gp`) without building.
- **Build cache cleanup** (`-Sc`).
- **Interactive TUI**: a list of installed AUR packages where you can mark, remove, upgrade
  and filter packages.
- No external dependencies: all it needs is `python`, `pacman`, `git` and `base-devel`.

## Requirements

- Arch Linux or an Arch-based distribution (e.g. EndeavourOS, Manjaro, CachyOS…)
- Python ≥ 3.8
- `pacman`, `git`, `base-devel` (`makepkg`, `vercmp`)
- `sudo`, `doas` or `run0` for privilege escalation
- optionally `less` for paging long review output

```bash
sudo pacman -S --needed python git base-devel less
```

## Installation

Clone or download this repository (on the GitHub page: **Code → Download ZIP**), then run
this in its directory:

```bash
install -Dm755 pyaur.py ~/.local/bin/pyaur
```

Make sure `~/.local/bin` is in your `PATH`. For a system-wide installation, use this command:

```bash
sudo install -Dm755 pyaur.py /usr/local/bin/pyaur
```

> **Do not run `pyaur` as root**; it refuses to start. Run it as a normal user and it will
> call `sudo` for `pacman` when needed.

## Usage

| Command | Subcommand | What it does |
|---|---|---|
| `pyaur` | `tui` | Interactive list of installed AUR packages |
| `pyaur -S <pkg>…` | `install` | Install (from the AUR or an official repository) |
| `pyaur -Ss <term>` | `search` | Search the AUR |
| `pyaur -Ssq <term>` | `search -q` | Search, printing package names only |
| `pyaur -Si <pkg>` | `info` | Show AUR package details |
| `pyaur -Syu` | `upgrade` | Run `pacman -Syu`, then upgrade AUR packages |
| `pyaur -Sua` | `upgrade --aur-only` | Upgrade AUR packages only |
| `pyaur -Qu` | `check` | List upgradable AUR packages without installing |
| `pyaur -R <pkg>…` | `remove` | Remove (`pacman -Rns`) |
| `pyaur -Qdt` / `-Yc` | `orphans` | Remove orphaned dependencies |
| `pyaur -G <pkg>…` | `getpkgbuild` | Download the AUR git repository into the current directory |
| `pyaur -Gp <pkg>` | `pkgbuild` | Print the PKGBUILD with a quick scan |
| `pyaur -Sc` | `clean` | Delete the build cache |

Examples:

```bash
pyaur -S google-chrome
pyaur -Ss --by maintainer jguer
pyaur -Syu
pyaur -Qu -q | wc -l                   # how many AUR updates are available
pyaur -S foo --noconfirm               # options also work after the command
pyaur -Gp yay | less                   # read the PKGBUILD before installing
```

## Options

The options below can go before or after the command.

| Option | Description |
|---|---|
| `--noconfirm` | Skips "Proceed?"-style questions. **It does not skip the PKGBUILD review.** |
| `--noreview` | Skips the PKGBUILD review. **Not recommended.** High-risk scanner findings are still printed. |
| `--rebuild` | Rebuilds even if the package is up to date (`makepkg -f`) |
| `--clean-build` | Deletes the package's cache directory before cloning |
| `--clean` / `--no-clean` | Cleans `src/` and `pkg/` after the build (`makepkg -c`, the default) |
| `--rmdeps` | Removes build dependencies after the build (`makepkg --rmdeps`) |
| `--install-split-deps` | For split packages, also installs the other subpackages with `--asdeps` |
| `--sudo CMD` | Privilege escalation command (`sudo`, `doas`, `run0`, or empty) |
| `--cache DIR` | Build cache location (default: `~/.cache/pyaur`) |
| `--limit N` | Maximum number of search results (default: 25) |
| `--by FIELD` | (`search`) Search field: `name`, `name-desc`, `maintainer`, `depends`, `makedepends`, `optdepends`, `checkdepends`, `provides`, `conflicts`, `replaces`, `keywords`, `groups`, `submitter` |
| `-q`, `--quiet` | (`search`, `check`) Prints package names only |
| `--aur-only` | (`upgrade`) Skips `pacman -Syu` |

## TUI

Run without arguments, `pyaur` lists the installed foreign (AUR) packages with their local
and AUR versions, status and size.

| Key | Action |
|---|---|
| `↑` `↓` / `j` `k` | move |
| `PgUp` `PgDn` `Home` `End` | scroll |
| `Space` | mark |
| `Shift+Del` / `Del` / `d` | remove the marked packages (or the current one) |
| `u` | upgrade all upgradable packages |
| `/` | filter by name or description (`Esc` clears it) |
| `i` | run `pacman -Qi` on the current package |
| `r` | reload |
| `q` | quit |

Colors: green = upgradable, red = not in the AUR, yellow + `*` = orphaned dependency,
`d` = installed as a dependency.

## Security model

`pyaur` treats all data coming from the AUR as **untrusted** until you approve it.

### Review

- **No PKGBUILD runs without your approval.** `--noconfirm` does not skip this step either.
  If there is no terminal, `pyaur` exits with an error instead.
- **You review exactly what gets built.** The review text comes straight from the git
  objects of the commit you are approving, not from the working tree. After you approve,
  the working tree moves to that commit (`git merge --ff-only`), and `pyaur` checks that
  `HEAD` really is that commit.
- **Your approval is recorded.** The last approved commit is stored in the repository's
  `.git/pyaur.json`. If you abort a review, the next run **asks again**. (In the old
  version, the package would have been built without a review in that case.) On updates
  you see a `git diff` against the last approved commit. The first time, you see the full
  contents of every file.
- **Local changes are shown too.** If something changed the files in the cache, their
  diff is included in the review. The one exception is the `pkgver=` line that `makepkg`
  rewrites in `-git` packages; `pyaur` restores it automatically.
- The review also includes the **repository's file list** (executables, symlinks and
  submodules are marked), the **new commits with their authors**, and the **downloaded
  sources** taken from `.SRCINFO`.

### Heuristic scanner

A summary of suspicious patterns appears at the start and at the end of the review. It looks for:

| Severity | Pattern |
|---|---|
| `[!!]` | `curl … \| sh`, `base64 -d`, `xxd -r`, `/dev/tcp/`, `nc`/`socat`, setuid `chmod`, `sudo`/`doas`/`su` in the script, `rm -rf /` or `~`, `~/.ssh`, `~/.gnupg`, `.bashrc`, `/etc/sudoers`, `/etc/shadow`, `LD_PRELOAD`, crypto miner traces, raw IP addresses in URLs, commonly abused hosts (pastebin, transfer.sh, Discord webhooks, Telegram API…), invisible and bidirectional Unicode characters, symlinks and submodules in the repository, unencrypted (`http`/`ftp`/`git://`) sources, `SKIP` checksums on non-VCS sources |
| `[ !]` | `eval`, inline `python -c`/`perl -e`, `systemctl enable`, `crontab`, long base64 or hex blobs, binary files in the repository, `.install` scripts (these run as root) |

> The scanner is **a heuristic, not a guarantee.** It helps you spot suspicious lines in a
> long PKGBUILD. A package with no findings is not necessarily safe.

### Warnings based on AUR metadata

When `pyaur` builds the installation plan, each AUR package can carry these warnings:

- **NEW package** (younger than 14 days). Malware distributed through the AUR typically
  looks like this.
- **ORPHANED** package with no maintainer, so anyone can adopt it.
- **few votes**
- **flagged out of date**
- **MAINTAINER CHANGE**: `pyaur` remembers each package's maintainer and warns loudly if it
  has changed at upgrade time.

If the plan contains a high-risk package, the default answer to "Proceed?" becomes **no**.

### Other protections

| Area | Protection |
|---|---|
| Command execution | Never `shell=True`. All arguments are passed as a list, with `--` before package names |
| Package names | Strict regex (`^[a-zA-Z0-9][a-zA-Z0-9@._+-]{0,127}$`) before a name goes into a URL or path |
| Paths | Protection against path traversal and symlinks (`resolve()` plus a parent check) |
| Terminal | All foreign text has ANSI/OSC escapes and bidi characters neutralised. `less` runs without `-R` and with `LESSSECURE=1` (shell escapes disabled) |
| HTTP | Only `https://aur.archlinux.org`, with TLS ≥ 1.2 and certificate verification. Redirects only within the AUR, a 16 MiB response limit and a timeout |
| Git | HTTPS only (`GIT_ALLOW_PROTOCOL`, `protocol.allow`). Hooks and fsmonitor disabled, no submodule recursion, the origin URL of an existing repository is verified (against cache poisoning), no `git pull` |
| Cache | `0700` permissions and an owner check; a cache that others can write to gets tightened. A file lock (`flock`) prevents concurrent runs. `-Sc` does not follow symlinks and refuses to delete your home directory or `/` |
| Privileges | Refuses to start as root. `makepkg` runs as a normal user; only `pacman` gets `sudo` |
| Installation | Dependencies are installed with `--asdeps`, so `-Qdt` can clean them up later |

## How an installation works

1. **Planning.** `pyaur` fetches package data from the AUR RPC and resolves dependencies
   recursively with `pacman -T`, which respects version constraints and provides. It then
   prints the build order with risk indicators.
2. **Official packages.** `pacman -S` installs everything that is in the repositories.
3. **Download and review.** `pyaur` clones or fetches every AUR repository and **has you
   review all of them before anything is built.** This way a chain is not half-built
   before the third PKGBUILD turns out to be suspicious.
4. **Build and install.** `makepkg -s` runs for each package in order, followed by `pacman -U`.

## Environment variables

| Variable | Meaning |
|---|---|
| `PYAUR_CACHE` | Build cache directory (overrides `~/.cache/pyaur`) |
| `PYAUR_SUDO` | Privilege escalation command. An empty value means no escalation |
| `NO_COLOR` | Disables colors |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. For `check`: updates are available |
| `1` | Error or abort |
| `2` | (`check`) No updates, same as `checkupdates` |
| `130` | Ctrl+C |

## Limitations

- `-Syu` upgrades `-git` and other VCS packages only when their version number has
  increased in the AUR (there is no `--devel` mode).
- No PGP key import. If a `validpgpkeys` key is missing, `makepkg` fails and you have to
  import the key yourself (`gpg --recv-keys …`).
- The heuristic scanner does not replace reading the PKGBUILD yourself.

## License

`pyaur` is free software: you can redistribute and modify it under the terms of the
**GNU General Public License, version 2** (GPL-2.0-only). The full text is in the
[LICENSE](LICENSE) file.

This program is distributed in the hope that it will be useful, but **WITHOUT ANY
WARRANTY**; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.
