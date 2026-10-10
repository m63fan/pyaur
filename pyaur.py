#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""
pyaur - minimalista, biztonságtudatos AUR helper (yay/paru alternatíva).

Fő elvek:
  * Semmi shell=True, semmi felhasználói input közvetlen behelyettesítése parancsba.
  * A PKGBUILD SOHA nem fut le felülvizsgálat (review) nélkül - és a "már láttam"
    állapotot egy külön jelölő rögzíti, nem az, hogy a repó le van-e töltve.
  * Pontosan azt a commitot nézed át, ami utána lefordul (git object, nem munkafa).
  * A csomagnevek szigorú regex-validáción esnek át, mielőtt URL-be vagy útvonalba kerülnének.
  * Root-ként nem indul el (a makepkg sem engedné, de mi hamarabb szólunk).
  * A terminálra kiírt idegen adat (PKGBUILD, pkgdesc, git diff) escape- és
    bidi-mentesítve van (ANSI/OSC injection, "Trojan Source").
  * Heurisztikus PKGBUILD-szkenner és AUR metaadat alapú figyelmeztetések
    (új csomag, árva csomag, karbantartó-váltás, titkosítatlan forrás, ...).
  * Csak stdlib - nem kell külön a python-requests.

Használat:
    pyaur                       # TUI (telepített AUR csomagok listája)
    pyaur -S <csomag> [...]     # telepítés az AUR-ból
    pyaur -Ss <kifejezés>       # keresés
    pyaur -Si <csomag>          # infó
    pyaur -Syu                  # rendszer + AUR csomagok frissítése
    pyaur -Sua                  # csak az AUR csomagok frissítése
    pyaur -Qu                   # frissíthető AUR csomagok listája (nem telepít)
    pyaur -R <csomag> [...]     # eltávolítás (pacman -Rns)
    pyaur -Qdt                  # árva függőségek eltávolítása
    pyaur -G <csomag> [...]     # AUR repó letöltése az aktuális könyvtárba
    pyaur -Gp <csomag>          # PKGBUILD kiírása
    pyaur -Sc                   # build cache takarítás

Licenc: GNU General Public License v2 (csak v2).
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 8):  # pragma: no cover
    sys.exit("pyaur: Python 3.8 vagy újabb kell.")

import argparse
import fcntl
import functools
import http.client
import json
import os
import re
import shutil
import signal
import ssl
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

APP = "pyaur"
VERSION = "0.4.0"

AUR_HOST = "aur.archlinux.org"
AUR_RPC = f"https://{AUR_HOST}/rpc/v5"
AUR_GIT_BASE = f"https://{AUR_HOST}"
AUR_CGIT_PLAIN = f"https://{AUR_HOST}/cgit/aur.git/plain"
USER_AGENT = f"{APP}/{VERSION} (python-stdlib AUR helper)"

HTTP_TIMEOUT = 20            # másodperc
HTTP_MAX_BYTES = 16 << 20    # 16 MiB - DoS elleni felső korlát a válaszra
RPC_CHUNK = 100              # ennyi nevet kérünk le egy multiinfo hívásban (URL-hossz limit)
REVIEW_MAX_FILE = 512 << 10  # e fölött a fájlt nem írjuk ki a review-ba, csak jelezzük
NEW_PKG_DAYS = 14            # ennél fiatalabb AUR csomagra külön figyelmeztetünk
LOW_VOTES = 3                # ennél kevesebb szavazat: figyelmeztetés

# Arch csomagnév szabály: alfanumerikussal kezdődik, utána @ . _ + - is lehet.
# Ez zárja ki a '..', '/', szóköz, '-' kezdet, vezérlőkarakter eseteket.
PKG_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9@._+-]{0,127}$")
# Függőség-sztring: 'foo>=1.2', 'bar=1:2.3-4', 'baz: leírás' (optdepends)
DEP_SPLIT_RE = re.compile(r"[<>=:]")
# Terminál-escape és egyéb vezérlőkarakterek (kivéve \n és \t)
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# Láthatatlan / irányváltó Unicode karakterek ("Trojan Source", CVE-2021-42574)
BIDI_RE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

DEFAULT_CACHE = Path(os.environ.get("PYAUR_CACHE") or (Path.home() / ".cache" / APP))

# Minden git hívásnál: hookok tiltása, csak HTTPS protokoll.
GIT_HARDEN = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.allow=never",
    "-c", "protocol.https.allow=always",
]


# --------------------------------------------------------------------------- #
#  Alapok: hibák, színek, sanitizálás, parancsfuttatás
# --------------------------------------------------------------------------- #

class PyaurError(Exception):
    """Kezelt hiba - a main() szépen kiírja és kilép."""


class C:
    """Színek. NO_COLOR és nem-tty esetén automatikusan kikapcsol."""
    _on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    reset = "\033[0m" if _on else ""
    bold = "\033[1m" if _on else ""
    dim = "\033[2m" if _on else ""
    red = "\033[31m" if _on else ""
    green = "\033[32m" if _on else ""
    yellow = "\033[33m" if _on else ""
    blue = "\033[34m" if _on else ""
    cyan = "\033[36m" if _on else ""


def info(msg: str) -> None:
    print(f"{C.blue}[*]{C.reset} {msg}")


def ok(msg: str) -> None:
    print(f"{C.green}[+]{C.reset} {msg}")


def warn(msg: str) -> None:
    print(f"{C.yellow}[!]{C.reset} {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"{C.red}[-]{C.reset} {msg}", file=sys.stderr)


def sanitize(text: str, keep_newlines: bool = True) -> str:
    """
    Idegen forrásból (AUR, PKGBUILD, pacman metaadat) származó szöveg
    terminálra írás előtt. Kivédi az ANSI/OSC injectiont és a láthatatlan
    bidi-karaktereket, amik elrejthetnének egy rosszindulatú sort a review közben.
    """
    if not keep_newlines:
        text = text.replace("\n", " ")
    text = CTRL_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", text)
    return BIDI_RE.sub(lambda m: f"<U+{ord(m.group()):04X}>", text)


def validate_pkgname(name: str) -> str:
    name = name.strip()
    if not PKG_NAME_RE.match(name):
        raise PyaurError(f"Érvénytelen csomagnév: {sanitize(name, False)!r}")
    return name


def clean_dep_name(dep: str) -> str:
    """'python>=3.9' -> 'python';  'foo: optional' -> 'foo'"""
    return DEP_SPLIT_RE.split(dep, 1)[0].strip()


def fmt_date(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "?"


def child_env(c_locale: bool) -> dict[str, str]:
    """
    Gyerekfolyamat környezete.
    LC_ALL=C csak a parsolt kimenetű hívásoknál kell (különben magyar locale-lal
    a 'Required By' mező neve más lenne); a makepkg-t NEM kényszerítjük C-re,
    mert az ASCII locale sok (pl. Python) buildet eltör.
    """
    env = os.environ.copy()
    if c_locale:
        env["LC_ALL"] = "C"
    env["GIT_TERMINAL_PROMPT"] = "0"   # a git ne kérjen interaktívan jelszót
    env["GIT_ALLOW_PROTOCOL"] = "https"
    env["LESSSECURE"] = "1"            # less: nincs shell escape, nincs fájlnyitás
    return env


def run(
    cmd: Sequence[str],
    *,
    check: bool = False,
    capture: bool = False,
    cwd: Path | None = None,
    input_text: str | None = None,
    quiet: bool = False,
) -> subprocess.CompletedProcess:
    """Egységes subprocess wrapper. shell=True SOHA."""
    try:
        return subprocess.run(
            list(cmd),
            check=check,
            cwd=str(cwd) if cwd else None,
            env=child_env(c_locale=capture or quiet),
            input=input_text,
            text=True,
            errors="replace",
            stdout=subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else None),
            stderr=subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else None),
        )
    except FileNotFoundError as e:
        raise PyaurError(f"Nem található program: {cmd[0]}") from e


def run_bytes(cmd: Sequence[str], cwd: Path | None = None) -> bytes | None:
    """Bináris kimenet (pl. git cat-file). Hiba esetén None."""
    res = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, env=child_env(True),
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return res.stdout if res.returncode == 0 else None


def require_tools(*tools: str) -> None:
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise PyaurError("Hiányzó program(ok): " + ", ".join(missing)
                         + " (pacman -S --needed base-devel git)")


def sudo_cmd(opts, args: Sequence[str]) -> list[str]:
    return [opts.sudo, *args] if opts.sudo else list(args)


def confirm(question: str, default: bool = True) -> bool:
    if not sys.stdin.isatty():
        raise PyaurError("Megerősítés kellene, de a bemenet nem terminál.")
    suffix = "[I/n]" if default else "[i/N]"
    while True:
        try:
            answer = input(f"{C.bold}:: {question} {suffix} {C.reset}").strip().lower()
        except EOFError:
            return False
        if not answer:
            return default
        if answer in ("i", "y", "igen", "yes"):
            return True
        if answer in ("n", "nem", "no"):
            return False


def pager(text: str, force_plain: bool = False) -> None:
    """Hosszú szöveg megjelenítése. -R szándékosan NINCS: az escape-eket
    láthatóvá tesszük, nem értelmezzük. LESSSECURE=1 a child_env-ben."""
    text = sanitize(text)
    less = shutil.which("less")
    height = shutil.get_terminal_size((80, 25)).lines
    if less and sys.stdout.isatty() and not force_plain and text.count("\n") > height - 2:
        try:
            subprocess.run([less, "-c", "-K"], input=text, text=True, env=child_env(False))
            return
        except (OSError, subprocess.SubprocessError):
            pass
    print(text)


# --------------------------------------------------------------------------- #
#  Cache könyvtár: jogosultság-ellenőrzés és zárolás
# --------------------------------------------------------------------------- #

def prepare_cache(cache: Path) -> Path:
    """
    Létrehozza (0700) és ellenőrzi a build cache-t. Ha más felhasználó is írhatná,
    egy helyi támadó kicserélhetné a már felülvizsgált PKGBUILD-et (cache-mérgezés).
    """
    cache = Path(cache).expanduser()
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        real = cache.resolve()
        st = real.stat()
    except OSError as e:
        raise PyaurError(f"A cache könyvtár nem használható ({cache}): {e}") from e
    if not stat.S_ISDIR(st.st_mode):
        raise PyaurError(f"A cache nem könyvtár: {real}")
    if st.st_uid != os.geteuid():
        raise PyaurError(f"A cache könyvtár ({real}) nem a te tulajdonod - nem használom.")
    if st.st_mode & 0o022:
        warn(f"A cache ({real}) mások által írható volt; jogosultság szigorítva (0700).")
        os.chmod(real, 0o700)
    return real


class CacheLock:
    """Egyszerre csak egy pyaur dolgozhat ugyanabban a cache-ben."""

    def __init__(self, cache: Path) -> None:
        self.path = cache / ".pyaur.lock"
        self.fd: int | None = None

    def __enter__(self) -> "CacheLock":
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            self.fd = os.open(self.path, flags, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise PyaurError("Egy másik pyaur példány már fut ezen a cache-en.") from e
        except OSError as e:
            raise PyaurError(f"Nem tudom zárolni a cache-t ({self.path}): {e}") from e
        return self

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None


# --------------------------------------------------------------------------- #
#  pacman réteg
# --------------------------------------------------------------------------- #

@functools.lru_cache(maxsize=4096)
def _vercmp(a: str, b: str) -> int:
    res = run(["vercmp", "--", a, b], capture=True)
    try:
        return int(res.stdout.strip())
    except ValueError:
        return 0


class Pacman:
    """pacman lekérdezések cache-elve (a rekurzió miatt sokszor ismétlődnének)."""

    def __init__(self) -> None:
        self._installed: dict[str, bool] = {}
        self._satisfied: dict[str, bool] = {}
        self._repo: dict[str, bool] = {}
        if not shutil.which("pacman"):
            raise PyaurError("Nincs 'pacman' a PATH-on. Ez a szkript Arch-alapú rendszert vár.")

    def is_installed(self, pkg: str) -> bool:
        if pkg not in self._installed:
            self._installed[pkg] = run(["pacman", "-Qq", "--", pkg], quiet=True).returncode == 0
        return self._installed[pkg]

    def dep_satisfied(self, dep: str) -> bool:
        """pacman -T: figyelembe veszi a verziókorlátot ÉS a provides-t is."""
        if dep not in self._satisfied:
            self._satisfied[dep] = run(["pacman", "-T", "--", dep], quiet=True).returncode == 0
        return self._satisfied[dep]

    def repo_exact(self, name: str) -> bool:
        """Pontosan ilyen NEVŰ csomag van-e a hivatalos tárolókban (provides nélkül).
        Explicit célpontnál ez kell, hogy egy véletlen provides ne térítsen el."""
        key = "!exact!" + name
        if key not in self._repo:
            self._repo[key] = run(["pacman", "-Si", "--", name], quiet=True).returncode == 0
        return self._repo[key]

    def in_repos(self, dep: str) -> bool:
        """
        Hivatalos tárolóban van-e (provides-t is feloldva).
        A -Si nem oldja fel a provides-t (pl. 'sh'), a -Sddp igen.
        """
        if dep not in self._repo:
            res = run(
                ["pacman", "-Sddp", "--noconfirm", "--print-format", "%n", "--", dep],
                capture=True,
            )
            self._repo[dep] = res.returncode == 0 and bool(res.stdout.strip())
        return self._repo[dep]

    @staticmethod
    def foreign() -> list[tuple[str, str]]:
        """Idegen (nem tárolóból való, jellemzően AUR) csomagok: [(név, verzió)]"""
        res = run(["pacman", "-Qm"], capture=True)
        out = []
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2:
                out.append((parts[0], parts[1]))
        return out

    @staticmethod
    def orphans() -> set[str]:
        res = run(["pacman", "-Qdtq"], capture=True)
        return {l.strip() for l in res.stdout.splitlines() if l.strip()}

    @staticmethod
    def explicit() -> set[str]:
        res = run(["pacman", "-Qeq"], capture=True)
        return {l.strip() for l in res.stdout.splitlines() if l.strip()}

    @staticmethod
    def query_info(pkgs: Sequence[str]) -> dict[str, dict[str, str]]:
        """pacman -Qi parse (LC_ALL=C miatt stabil mezőnevek)."""
        if not pkgs:
            return {}
        res = run(["pacman", "-Qi", "--", *pkgs], capture=True)
        blocks: dict[str, dict[str, str]] = {}
        cur: dict[str, str] = {}
        last_key = ""
        for line in res.stdout.splitlines():
            if not line.strip():
                if cur.get("Name"):
                    blocks[cur["Name"]] = cur
                cur, last_key = {}, ""
                continue
            m = re.match(r"^(\S.*?)\s*:\s?(.*)$", line)
            if m:
                last_key = m.group(1).strip()
                cur[last_key] = m.group(2).strip()
            elif last_key:
                cur[last_key] += " " + line.strip()
        if cur.get("Name"):
            blocks[cur["Name"]] = cur
        return blocks

    @staticmethod
    def vercmp(a: str, b: str) -> int:
        return _vercmp(a, b)


# --------------------------------------------------------------------------- #
#  AUR RPC réteg (stdlib urllib, TLS >= 1.2, szigorú host-ellenőrzéssel)
# --------------------------------------------------------------------------- #

class StrictRedirect(urllib.request.HTTPRedirectHandler):
    """Csak az AUR-on belüli HTTPS átirányítást engedjük."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname != AUR_HOST:
            raise PyaurError(f"Gyanús átirányítás: {sanitize(newurl, False)}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()          # tanúsítvány + hostname ellenőrzés
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=_ssl_context()), StrictRedirect
)


def _http_get(url: str, accept: str = "*/*") -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != AUR_HOST:
        raise PyaurError(f"Nem engedélyezett URL: {sanitize(url, False)}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with _opener.open(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                raise PyaurError(f"AUR HTTP {resp.status}")
            raw = resp.read(HTTP_MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise PyaurError(f"AUR HTTP hiba: {e.code}") from e
    except urllib.error.URLError as e:
        raise PyaurError(f"Hálózati hiba az AUR elérésekor: {e.reason}") from e
    except TimeoutError as e:
        raise PyaurError("Időtúllépés az AUR elérésekor.") from e
    except (OSError, http.client.HTTPException) as e:
        raise PyaurError(f"Hálózati hiba az AUR elérésekor: {e}") from e
    if len(raw) > HTTP_MAX_BYTES:
        raise PyaurError("Az AUR válasza gyanúsan nagy, megszakítva.")
    return raw


def _http_json(url: str) -> dict:
    raw = _http_get(url, accept="application/json")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise PyaurError(f"Értelmezhetetlen AUR válasz: {e}") from e
    if not isinstance(data, dict):
        raise PyaurError("Váratlan formátumú AUR válasz.")
    if data.get("type") == "error":
        raise PyaurError(f"AUR RPC hiba: {sanitize(str(data.get('error')), False)}")
    return data


def _results(data: dict) -> list[dict]:
    res = data.get("results")
    return [r for r in res if isinstance(r, dict)] if isinstance(res, list) else []


def aur_info(names: Iterable[str]) -> dict[str, dict]:
    """Kötegelt multiinfo lekérés. Kulcs: Name."""
    names = [n for n in dict.fromkeys(names) if n]
    out: dict[str, dict] = {}
    for i in range(0, len(names), RPC_CHUNK):
        chunk = names[i:i + RPC_CHUNK]
        query = urllib.parse.urlencode([("arg[]", n) for n in chunk])
        data = _http_json(f"{AUR_RPC}/info?{query}")
        for res in _results(data):
            if isinstance(res.get("Name"), str):
                out[res["Name"]] = res
    return out


def aur_provider(dep: str) -> dict | None:
    """Ha nincs ilyen nevű AUR csomag, hátha valami provides-olja."""
    q = urllib.parse.quote(dep, safe="")
    try:
        data = _http_json(f"{AUR_RPC}/search/{q}?by=provides")
    except PyaurError:
        return None
    results = _results(data)
    for res in results:
        provides = [clean_dep_name(p) for p in res.get("Provides", []) or []]
        if dep in provides or res.get("Name") == dep:
            return res
    return results[0] if len(results) == 1 else None


SEARCH_FIELDS = ("name", "name-desc", "maintainer", "depends", "makedepends",
                 "optdepends", "checkdepends", "provides", "conflicts",
                 "replaces", "keywords", "groups", "submitter")


def aur_search(term: str, by: str = "name-desc") -> list[dict]:
    if by not in SEARCH_FIELDS:
        raise PyaurError(f"Ismeretlen keresési mező: {by}")
    q = urllib.parse.quote(term, safe="")
    data = _http_json(f"{AUR_RPC}/search/{q}?by={by}")
    return _results(data)


def aur_risk_flags(meta: dict) -> tuple[list[str], bool]:
    """
    AUR metaadat alapú figyelmeztetések. Visszaad: (címkék, magas_kockázat).
    A friss feltöltésű és árva csomagok a jellemző malware-vektorok az AUR-ban.
    """
    flags: list[str] = []
    high = False
    if not meta.get("Maintainer"):
        flags.append("ÁRVA (nincs karbantartó)")
        high = True
    first = meta.get("FirstSubmitted")
    if isinstance(first, int):
        age_days = (time.time() - first) / 86400
        if age_days < NEW_PKG_DAYS:
            flags.append(f"ÚJ csomag ({max(0, int(age_days))} napos)")
            high = True
    votes = meta.get("NumVotes")
    if isinstance(votes, int) and votes < LOW_VOTES:
        flags.append(f"kevés szavazat ({votes})")
    if meta.get("OutOfDate"):
        flags.append(f"elavultnak jelölve ({fmt_date(meta['OutOfDate'])})")
    return flags, high


# --------------------------------------------------------------------------- #
#  Függőségfeloldás
# --------------------------------------------------------------------------- #

@dataclass
class Build:
    """Egy AUR *pkgbase*, amit le kell fordítani."""
    base: str
    version: str = ""
    pkgs: set[str] = field(default_factory=set)   # ebből a base-ből kellő pkgname-ek
    explicit: bool = False                        # a user kérte, vagy csak függőség
    maintainer: str = ""
    flags: list[str] = field(default_factory=list)
    high_risk: bool = False


class Resolver:
    def __init__(self, pac: Pacman, opts) -> None:
        self.pac = pac
        self.opts = opts
        self.builds: dict[str, Build] = {}   # base -> Build
        self.order: list[str] = []           # base-ek build sorrendben
        self.repo_targets: list[str] = []    # explicit célpont, ami hivatalos tárolóban van
        self.seen: set[str] = set()
        self.stack: list[str] = []
        self._info_cache: dict[str, dict] = {}

    def prefetch(self, names: Iterable[str]) -> None:
        """Egy kötegelt RPC hívás a célpontokra (kevesebb kérés az AUR felé)."""
        self._info_cache.update(aur_info(names))

    def _lookup(self, name: str) -> dict | None:
        if name not in self._info_cache:
            found = aur_info([name]).get(name)
            if found is None:
                found = aur_provider(name)
            if found is not None:
                self._info_cache[name] = found
        return self._info_cache.get(name)

    def resolve(self, targets: Sequence[str]) -> list[Build]:
        for t in targets:
            self._walk(t, explicit=True)
        return [self.builds[b] for b in self.order]

    def _walk(self, dep: str, explicit: bool = False) -> None:
        name = clean_dep_name(dep)
        if not name:
            return

        if name in self.stack:
            warn(f"Körkörös függőség: {' -> '.join(self.stack)} -> {sanitize(name, False)} (átugorva)")
            return
        if name in self.seen:
            if explicit and (b := self._build_of(name)):
                b.explicit = True
            return
        self.seen.add(name)

        # 1) Már kielégített függőség? (verziókorláttal és provides-szal együtt)
        if not explicit and self.pac.dep_satisfied(dep):
            return
        if explicit and self.pac.is_installed(name) and not self.opts.rebuild:
            aur = self._lookup(name)
            if aur and Pacman.vercmp(str(aur.get("Version", "0")), self._local_version(name)) <= 0:
                info(f"{name} már telepítve és naprakész (--rebuild a kényszerítéshez).")
                return

        # 2) Hivatalos tárolóban?
        #    - explicit célpont: a pacman telepítse, ne az AUR (pontos névegyezés kell)
        #    - függőség: a makepkg -s úgyis behúzza
        validate_pkgname(name)
        if explicit:
            if self.pac.repo_exact(name):
                self.repo_targets.append(name)
                return
        elif self.pac.in_repos(dep):
            return

        # 3) Marad az AUR.
        aur = self._lookup(name)
        if aur is None:
            if self.pac.in_repos(dep):
                return
            raise PyaurError(
                f"'{sanitize(name, False)}' nem található sem a hivatalos tárolókban, sem az AUR-ban."
            )

        aur_name = validate_pkgname(str(aur.get("Name") or ""))
        base = validate_pkgname(str(aur.get("PackageBase") or aur_name))
        build = self.builds.get(base)
        if build is None:
            flags, high = aur_risk_flags(aur)
            build = Build(base=base, version=str(aur.get("Version", "")),
                          maintainer=str(aur.get("Maintainer") or ""),
                          flags=flags, high_risk=high)
            self.builds[base] = build
        build.pkgs.add(aur_name)
        build.explicit = build.explicit or explicit

        self.stack.append(name)
        try:
            deps = (list(aur.get("Depends") or [])
                    + list(aur.get("MakeDepends") or [])
                    + list(aur.get("CheckDepends") or []))
            for d in deps:
                if isinstance(d, str):
                    self._walk(d)
        finally:
            self.stack.pop()

        if base not in self.order:
            self.order.append(base)

    def _build_of(self, pkgname: str) -> Build | None:
        for b in self.builds.values():
            if pkgname in b.pkgs:
                return b
        return None

    @staticmethod
    def _local_version(pkg: str) -> str:
        res = run(["pacman", "-Q", "--", pkg], capture=True)
        parts = res.stdout.split()
        return parts[1] if res.returncode == 0 and len(parts) == 2 else "0"


# --------------------------------------------------------------------------- #
#  Git
# --------------------------------------------------------------------------- #

def pkg_dir_for(base: str, cache: Path) -> Path:
    """Path traversal elleni dupla védelem: regex + resolve() ellenőrzés.
    Egy cache-be ültetett symlink is itt bukik el (a resolve() kivezetne)."""
    validate_pkgname(base)
    cache = cache.resolve()
    target = (cache / base).resolve()
    if target.parent != cache:
        raise PyaurError(f"Gyanús build útvonal: {target}")
    return target


def git(args: Sequence[str], cwd: Path | None = None, capture: bool = False):
    return run(["git", *GIT_HARDEN, *args], cwd=cwd, capture=capture)


def git_out(args: Sequence[str], cwd: Path) -> str:
    res = git(args, cwd=cwd, capture=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def git_blob(d: Path, sha: str) -> bytes | None:
    return run_bytes(["git", *GIT_HARDEN, "cat-file", "blob", sha], cwd=d)


def commit_exists(d: Path, rev: str) -> bool:
    if not GIT_SHA_RE.match(rev or ""):
        return False
    return git(["cat-file", "-e", f"{rev}^{{commit}}"], cwd=d, capture=True).returncode == 0


def has_local_mods(d: Path) -> bool:
    res = git(["status", "--porcelain", "--untracked-files=no"], cwd=d, capture=True)
    return res.returncode == 0 and bool(res.stdout.strip())


def discard_pkgver_bump(d: Path) -> None:
    """
    VCS (-git) csomagoknál a makepkg maga írja át a PKGBUILD pkgver= sorát.
    Ha a helyi módosítás CSAK ennyi, visszaállítjuk - ez nem a felhasználó
    szándékos módosítása, és ne akassza meg a következő ff-only merge-et.
    """
    res = git(["diff", "--no-color", "--no-ext-diff", "-U0", "HEAD"], cwd=d, capture=True)
    if res.returncode != 0 or not res.stdout.strip():
        return
    files = set()
    for line in res.stdout.splitlines():
        if line.startswith("diff --git "):
            files.add(line)
        elif line.startswith(("+++", "---", "@@", "index ")):
            continue
        elif line.startswith(("+", "-")) and not re.match(r"^[+-]pkgver=\S*$", line):
            return
    if files == {"diff --git a/PKGBUILD b/PKGBUILD"}:
        git(["checkout", "--quiet", "--", "PKGBUILD"], cwd=d)


# A felülvizsgálati állapot a .git könyvtárban él: nem követett, nem jön a remote-ról.
META_FILE = "pyaur.json"


def read_meta(d: Path) -> dict:
    p = d / ".git" / META_FILE
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(d: Path, meta: dict) -> None:
    p = d / ".git" / META_FILE
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(meta, indent=1))
        os.replace(tmp, p)
    except OSError as e:
        warn(f"Nem tudtam menteni a review-állapotot ({p}): {e}")


def fetch_repo(build: Build, opts) -> tuple[Path, str | None, str]:
    """
    Klónoz vagy frissít. Visszaad: (könyvtár, jelenlegi_HEAD|None, távoli_revízió)
    Sosem 'git pull' - fetch + ellenőrzés + review + ff-only merge.
    """
    cache = prepare_cache(Path(opts.cache))
    d = pkg_dir_for(build.base, cache)
    url = f"{AUR_GIT_BASE}/{build.base}.git"

    if opts.clean_build and d.exists():
        info(f"{build.base}: tiszta build, régi könyvtár törlése")
        shutil.rmtree(d)

    if d.exists():
        if not (d / ".git").is_dir():
            raise PyaurError(f"{d} létezik, de nem git repó. Töröld kézzel vagy használd a --clean-build kapcsolót.")
        remote = git_out(["remote", "get-url", "origin"], cwd=d)
        if remote != url:
            raise PyaurError(
                f"{d} origin URL-je nem stimmel ({sanitize(remote, False)} != {url}). "
                "Cache-mérgezés gyanúja - használd a --clean-build kapcsolót."
            )
        head = git_out(["rev-parse", "--verify", "HEAD"], cwd=d)
        info(f"{build.base}: git fetch")
        if git(["fetch", "--quiet", "--no-recurse-submodules", "origin"], cwd=d).returncode != 0:
            raise PyaurError(f"{build.base}: a git fetch nem sikerült.")
        upstream = (git_out(["rev-parse", "--verify", "origin/HEAD^{commit}"], cwd=d)
                    or git_out(["rev-parse", "--verify", "origin/master^{commit}"], cwd=d))
        if not GIT_SHA_RE.match(upstream):
            raise PyaurError(f"{build.base}: nem találom a távoli ágat.")
        return d, head or None, upstream

    info(f"{build.base}: git clone")
    if git(["clone", "--quiet", "--no-recurse-submodules", "--", url, str(d)]).returncode != 0:
        raise PyaurError(f"{build.base}: a git clone nem sikerült ({url}).")
    new = git_out(["rev-parse", "--verify", "HEAD^{commit}"], cwd=d)
    if not GIT_SHA_RE.match(new):
        raise PyaurError(f"{build.base}: üres vagy sérült repó (nem létező AUR csomag?).")
    return d, None, new


# --------------------------------------------------------------------------- #
#  Felülvizsgálat: heurisztikus szkenner + review szöveg
# --------------------------------------------------------------------------- #

@dataclass
class Finding:
    path: str
    line: int
    high: bool
    msg: str
    snippet: str = ""


# Heurisztika, NEM garancia. Célja, hogy a hosszú PKGBUILD-ben a szem
# a gyanús sorokra essen. (minta, magas_kockázat, leírás)
SUSPICIOUS: list[tuple[re.Pattern, bool, str]] = [
    (re.compile(r"\b(curl|wget|fetch)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da|k|fi)?sh\b"), True,
     "letöltött tartalom közvetlenül shellbe csövezve"),
    (re.compile(r"\bbase64\s+(-\w*d|--decode)"), True, "base64 dekódolás (obfuszkáció?)"),
    (re.compile(r"\b(xxd\s+-r|openssl\s+enc\s+-d)"), True, "kódolt tartalom visszafejtése"),
    (re.compile(r"(^|[;&|\s])eval\s"), False, "eval használat"),
    (re.compile(r"/dev/(tcp|udp)/"), True, "nyers hálózati socket (/dev/tcp)"),
    (re.compile(r"\b(nc|ncat|netcat|socat)\s+-"), True, "netcat/socat hívás"),
    (re.compile(r"\bchmod\s+(-\w+\s+)*([ugoa]*\+\w*s|[2-7][0-7]{3}\b)"), True,
     "setuid/setgid bit beállítása"),
    (re.compile(r"(^|[;&|\s(`])(sudo|doas|pkexec|su)\s"), True, "jogosultság-emelés a szkriptben"),
    (re.compile(r"\brm\s+-\w*[rR]\w*\s+(-\w+\s+)*(/|~|\$HOME|\$\{HOME\})(\s|/?\*|[;&|)]|$)"), True,
     "rekurzív törlés a gyökérben vagy a home-ban"),
    (re.compile(r"\b(python[0-9.]*|perl|ruby|node|php)\s+-[ce]\s"), False, "inline interpreter kód"),
    (re.compile(r"(~|\$HOME|\$\{HOME\}|/home/[^/\s]+|/root)/\.(ssh|gnupg|bashrc|zshrc|profile|"
                r"bash_profile|config/autostart|mozilla|local/share/keyrings)"), True,
     "felhasználói érzékeny fájl/könyvtár elérése"),
    (re.compile(r"/etc/(sudoers|passwd|shadow|gshadow|profile\.d|ld\.so\.preload|pam\.d)"), True,
     "érzékeny rendszerfájl elérése"),
    (re.compile(r"\bLD_PRELOAD\b"), True, "LD_PRELOAD manipuláció"),
    (re.compile(r"\b(crontab|systemctl\s+(--\w+\s+)*(enable|start|daemon-reload))\b"), False,
     "időzített / automatikusan induló szolgáltatás"),
    (re.compile(r"\b(xmrig|minerd|cpuminer|stratum\+tcp)\b", re.I), True, "kriptobányász nyom"),
    (re.compile(r"\bhttps?://(\d{1,3}\.){3}\d{1,3}\b"), True, "nyers IP-cím URL-ben"),
    (re.compile(r"\b(pastebin\.com|paste\.ee|transfer\.sh|0x0\.st|ngrok(-free)?\.(io|app)|"
                r"discord(app)?\.com/api/webhooks|api\.telegram\.org)", re.I), True,
     "gyakran visszaélt hoszt"),
    (re.compile(r"[A-Za-z0-9+/]{160,}={0,2}"), False, "hosszú base64-szerű blob"),
    (re.compile(r"(\\x[0-9a-fA-F]{2}){16,}"), False, "hex-kódolt bájtsorozat"),
]

SCAN_SUFFIXES = (".install", ".sh", ".bash", ".zsh", ".hook", ".py", ".pl",
                 ".service", ".timer", ".desktop", ".rules")


def scan_text(path: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    if BIDI_RE.search(text):
        out.append(Finding(path, 0, True, "láthatatlan/irányváltó Unicode karakter (Trojan Source?)"))
    for no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for rx, high, msg in SUSPICIOUS:
            if rx.search(line):
                out.append(Finding(path, no, high, msg, stripped[:160]))
    return out


SUM_PREFIXES = ("md5sums", "sha1sums", "sha224sums", "sha256sums", "sha384sums",
                "sha512sums", "b2sums", "cksums")
VCS_PREFIXES = ("git+", "svn+", "hg+", "bzr+", "fossil+")


def parse_srcinfo_text(text: str) -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        data.setdefault(k.strip(), []).append(v.strip())
    return data


def parse_srcinfo(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    return parse_srcinfo_text(path.read_text(errors="replace"))


def analyze_srcinfo(src: dict[str, list[str]]) -> tuple[list[str], list[Finding]]:
    """Források listája + figyelmeztetések (titkosítatlan letöltés, SKIP checksum, install szkript)."""
    lines: list[str] = []
    findings: list[Finding] = []
    for key, vals in sorted(src.items()):
        if not (key == "source" or key.startswith("source_")):
            continue
        suffix = key[len("source"):]
        sums: list[str] | None = None
        for p in SUM_PREFIXES:
            if p + suffix in src:
                sums = src[p + suffix]
                break
        for i, s in enumerate(vals):
            url = s.split("::", 1)[-1]
            is_vcs = url.startswith(VCS_PREFIXES + ("git://", "svn://"))
            scheme = urllib.parse.urlsplit(url.split("+", 1)[-1] if is_vcs else url).scheme
            if not scheme:
                continue                         # helyi fájl a repóból - a review része
            lines.append(f"  {key}: {s}")
            if scheme in ("http", "ftp", "git") or url.startswith(("git+http:", "git+git:")):
                findings.append(Finding(".SRCINFO", 0, True,
                                        f"titkosítatlan letöltés ({scheme}): {s}"))
            if sums and i < len(sums) and sums[i] == "SKIP" and not is_vcs:
                findings.append(Finding(".SRCINFO", 0, True,
                                        f"nincs ellenőrzőösszeg (SKIP) nem-VCS forrásnál: {s}"))
    for inst in src.get("install", []):
        findings.append(Finding(".SRCINFO", 0, False,
                                f"install szkript ({inst}) - ROOTKÉNT fut telepítéskor, olvasd el!"))
    return lines, findings


def tree_files(d: Path, rev: str) -> list[tuple[str, str, str]]:
    """git ls-tree: [(mode, sha, path)] a megadott commitban."""
    raw = run_bytes(["git", *GIT_HARDEN, "ls-tree", "-r", "-z", "--full-tree", rev], cwd=d) or b""
    out = []
    for entry in raw.split(b"\0"):
        if not entry or b"\t" not in entry:
            continue
        meta, _, path = entry.partition(b"\t")
        parts = meta.split()
        if len(parts) != 3:
            continue
        out.append((parts[0].decode(), parts[2].decode(), path.decode("utf-8", "replace")))
    order = {"PKGBUILD": 0, ".SRCINFO": 1}
    out.sort(key=lambda t: (order.get(t[2], 2), t[2]))
    return out


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "  (a heurisztikus szkenner nem talált gyanús mintát - ez NEM garancia)"
    rows = []
    for f in sorted(findings, key=lambda f: (not f.high, f.path, f.line)):
        tag = "[!!]" if f.high else "[ !]"
        loc = f"{f.path}:{f.line}" if f.line else f.path
        rows.append(f"  {tag} {loc}  {f.msg}")
        if f.snippet:
            rows.append(f"         > {f.snippet}")
    return "\n".join(rows)


def build_review(d: Path, base_rev: str | None, upstream: str,
                 local_mods: bool) -> tuple[str, list[Finding]]:
    """
    A review szövege PONTOSAN az `upstream` commit tartalmából készül (git objektumokból,
    nem a munkafából), így amit látsz, az fordul le. Frissítésnél a legutóbb
    jóváhagyott commithoz képesti diff, első alkalommal minden fájl teljes egészében.
    """
    findings: list[Finding] = []
    file_sections: list[str] = []
    listing: list[str] = []
    sources: list[str] = []

    for mode, sha, path in tree_files(d, upstream):
        note = ""
        if mode == "120000":
            target = (git_blob(d, sha) or b"").decode("utf-8", "replace")
            findings.append(Finding(path, 0, True, f"szimbolikus link a repóban -> {target}"))
            note = f" -> {target}"
        elif mode == "160000":
            findings.append(Finding(path, 0, True, "git submodule a repóban"))
            note = " (submodule)"
        elif mode == "100755":
            note = " (futtatható)"
        listing.append(f"  {mode} {path}{note}")
        if mode not in ("100644", "100755"):
            continue
        data = git_blob(d, sha)
        if data is None:
            continue
        is_text = b"\0" not in data[:8192]
        if is_text:
            text = data.decode("utf-8", "replace")
            if path == ".SRCINFO":
                src_lines, src_findings = analyze_srcinfo(parse_srcinfo_text(text))
                findings.extend(src_findings)
                sources.extend(src_lines)
            elif path == "PKGBUILD" or path.endswith(SCAN_SUFFIXES):
                findings.extend(scan_text(path, text))
        else:
            findings.append(Finding(path, 0, False, f"bináris fájl a repóban ({len(data)} bájt)"))
        if base_rev is None:
            if not is_text:
                file_sections.append(f"--- {path} --- (bináris, {len(data)} bájt - nem jelenítem meg)")
            elif len(data) > REVIEW_MAX_FILE:
                file_sections.append(f"--- {path} --- (túl nagy, {len(data)} bájt - nézd meg kézzel: {d / path})")
            else:
                file_sections.append(f"--- {path} ---\n{data.decode('utf-8', 'replace')}")

    parts = [f"=== Heurisztikus figyelmeztetések ===\n{format_findings(findings)}",
             "=== Fájlok a repóban ===\n" + "\n".join(listing)]
    if sources:
        parts.append("=== Letöltött források (.SRCINFO) ===\n" + "\n".join(sources))

    log_range = f"{base_rev}..{upstream}" if base_rev else upstream
    log = git(["--no-pager", "log", "--no-color", "--date=short", "-n", "20",
               "--format=%h %ad %an <%ae>%n      %s", log_range], cwd=d, capture=True).stdout
    parts.append(f"=== Commitok ({'új' if base_rev else 'utolsó 20'}) ===\n{log.rstrip()}")

    if base_rev:
        diff = git(["--no-pager", "diff", "--no-color", "--no-ext-diff", "--no-textconv",
                    "--stat", "--patch", f"{base_rev}..{upstream}"], cwd=d, capture=True)
        parts.append(f"=== git diff {base_rev[:8]}..{upstream[:8]} "
                     f"(a legutóbb jóváhagyott állapothoz képest) ===\n{diff.stdout}")
    else:
        parts.extend(file_sections)

    if local_mods:
        ldiff = git(["--no-pager", "diff", "--no-color", "--no-ext-diff", "--no-textconv", "HEAD"],
                    cwd=d, capture=True)
        parts.append("=== HELYI MÓDOSÍTÁSOK a munkafában (ezek is lefordulnak!) ===\n"
                     + ldiff.stdout)
    return "\n\n".join(parts), findings


def review_and_apply(build: Build, opts) -> Path:
    """Letölt, felülvizsgáltat, majd ff-only merge-el a jóváhagyott commitra."""
    d, head, upstream = fetch_repo(build, opts)
    meta = read_meta(d)
    reviewed = meta.get("reviewed") if isinstance(meta.get("reviewed"), str) else None
    if reviewed and not commit_exists(d, reviewed):
        reviewed = None
    discard_pkgver_bump(d)
    local_mods = has_local_mods(d)

    old_maint = meta.get("maintainer")
    if old_maint and build.maintainer and old_maint != build.maintainer:
        warn(f"{C.red}{build.base}: KARBANTARTÓ-VÁLTÁS: {sanitize(str(old_maint), False)} -> "
             f"{sanitize(build.maintainer, False)}. Fokozottan nézd át a változásokat!{C.reset}")

    if reviewed == upstream and not local_mods:
        info(f"{build.base}: nincs változás a legutóbb jóváhagyott állapot óta.")
    else:
        text, findings = build_review(d, reviewed, upstream, local_mods)
        high = [f for f in findings if f.high]
        if opts.noreview:
            warn(f"{build.base}: felülvizsgálat kihagyva (--noreview). Ez futtatható kódot telepít vakon.")
            if high:
                warn(f"{build.base}: a szkenner {len(high)} magas kockázatú mintát talált:\n"
                     + sanitize(format_findings(high)))
        else:
            print(f"\n{C.bold}{'=' * 60}\n  Felülvizsgálat: {build.base}\n{'=' * 60}{C.reset}")
            pager(text)
            print(f"\n{C.bold}Szkenner összegzés ({build.base}):{C.reset}")
            print(sanitize(format_findings(findings)))
            if build.flags:
                warn(f"{build.base}: " + "; ".join(build.flags))
            if not confirm(f"Megbízol a(z) {build.base} PKGBUILD-jében és folytatod?", default=False):
                raise PyaurError(f"{build.base}: a felhasználó megszakította a felülvizsgálatnál.")
            meta["reviewed"] = upstream

    if head and head != upstream:
        res = git(["merge", "--ff-only", "--quiet", upstream], cwd=d, capture=True)
        if res.returncode != 0:
            warn(f"{build.base}: nem fast-forward frissítés (upstream force-push vagy helyi módosítás).")
            if not confirm("Hard reset a jóváhagyott távoli állapotra? (helyi módosítások elvesznek)",
                           default=False):
                raise PyaurError(f"{build.base}: megszakítva.")
            if git(["reset", "--hard", "--quiet", upstream], cwd=d).returncode != 0:
                raise PyaurError(f"{build.base}: a git reset nem sikerült.")

    if git_out(["rev-parse", "--verify", "HEAD"], cwd=d) != upstream:
        raise PyaurError(f"{build.base}: a munkafa nem a jóváhagyott commiton áll - megszakítva.")

    if build.maintainer:
        meta["maintainer"] = build.maintainer
    write_meta(d, meta)
    return d


def verify_srcinfo_deps(d: Path, pac: Pacman, planned: set[str]) -> None:
    """
    Az RPC metaadat elavult lehet a repóhoz képest. Ha a .SRCINFO olyan AUR
    függőséget említ, ami nincs a tervben, arról szólunk - ne csendben bukjon el.
    """
    src = parse_srcinfo(d / ".SRCINFO")
    deps: list[str] = []
    for key, vals in src.items():
        if key.split("_")[0] in ("depends", "makedepends", "checkdepends"):
            deps.extend(vals)
    missing = []
    for dep in deps:
        name = clean_dep_name(dep)
        if not name or name in planned:
            continue
        if pac.dep_satisfied(dep) or pac.in_repos(dep):
            continue
        missing.append(name)
    if missing:
        warn("A .SRCINFO olyan függőségeket említ, amik nincsenek a tervben: "
             + ", ".join(sorted(set(sanitize(m, False) for m in missing))))


# --------------------------------------------------------------------------- #
#  Build + telepítés
# --------------------------------------------------------------------------- #

def package_files(d: Path) -> list[Path]:
    """makepkg --packagelist: a lefordítandó fájlok elérési útja (PKGDEST-tel is jó)."""
    res = run(["makepkg", "--packagelist"], cwd=d, capture=True)
    if res.returncode != 0:
        return []
    return [Path(l.strip()) for l in res.stdout.splitlines() if l.strip()]


def pkgname_from_file(p: Path) -> str:
    """foo-bar-1.2.3-1-x86_64.pkg.tar.zst -> foo-bar"""
    name = p.name
    for suf in (".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar.bz2", ".pkg.tar"):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    return name.rsplit("-", 3)[0]


def build_and_install(build: Build, d: Path, opts, pac: Pacman) -> None:
    print(f"\n{C.bold}{'=' * 60}\n  Fordítás: {build.base}\n{'=' * 60}{C.reset}")

    mk = ["makepkg", "-s", "--needed", "--noprogressbar"]
    if opts.clean:
        mk.append("-c")
    if opts.noconfirm:
        mk.append("--noconfirm")
    if opts.rebuild:
        mk.append("-f")
    if opts.rmdeps:
        mk.append("--rmdeps")

    res = run(mk, cwd=d)
    if res.returncode != 0:
        raise PyaurError(f"{build.base}: a makepkg hibával állt le.")

    files = [p for p in package_files(d) if p.is_file()]
    if not files:
        raise PyaurError(f"{build.base}: nem találom a lefordított csomagfájlokat.")

    wanted = build.pkgs or {build.base}
    explicit_files = [p for p in files if pkgname_from_file(p) in wanted]
    dep_files = [p for p in files if p not in explicit_files]
    if not explicit_files:                      # split package edge case
        explicit_files, dep_files = files, []

    # Frissítésnél a pacman -U megtartja a meglévő install reason-t;
    # új függőséget --asdeps-szel telepítünk, hogy a -Qdt később eltakaríthassa.
    if build.explicit:
        cmd = sudo_cmd(opts, ["pacman", "-U", "--needed"])
    else:
        cmd = sudo_cmd(opts, ["pacman", "-U", "--needed", "--asdeps"])
    if opts.noconfirm:
        cmd.append("--noconfirm")
    cmd.append("--")
    cmd += [str(p) for p in explicit_files]

    if run(cmd).returncode != 0:
        raise PyaurError(f"{build.base}: a pacman -U hibával állt le.")

    if dep_files and opts.install_split_deps:
        dcmd = sudo_cmd(opts, ["pacman", "-U", "--needed", "--asdeps"])
        if opts.noconfirm:
            dcmd.append("--noconfirm")
        dcmd.append("--")
        dcmd += [str(p) for p in dep_files]
        if run(dcmd).returncode != 0:
            warn(f"{build.base}: a split alcsomagok telepítése nem sikerült.")

    ok(f"{build.base} telepítve.")


# --------------------------------------------------------------------------- #
#  Parancsok
# --------------------------------------------------------------------------- #

def cmd_install(opts, targets: Sequence[str]) -> int:
    pac = Pacman()
    require_tools("git", "makepkg")
    targets = [validate_pkgname(t) for t in targets]
    cache = prepare_cache(Path(opts.cache))

    with CacheLock(cache):
        info("Telepítési terv készítése...")
        resolver = Resolver(pac, opts)
        resolver.prefetch(targets)
        builds = resolver.resolve(targets)
        repo_targets = list(dict.fromkeys(resolver.repo_targets))

        if not builds and not repo_targets:
            ok("Minden kért csomag telepítve és naprakész.")
            return 0

        if repo_targets:
            print(f"\n{C.bold}Hivatalos tárolóból (pacman):{C.reset}")
            print("  " + "  ".join(repo_targets))

        if not builds:
            cmd = sudo_cmd(opts, ["pacman", "-S", "--needed"])
            if opts.noconfirm:
                cmd.append("--noconfirm")
            return run([*cmd, "--", *repo_targets]).returncode

        print(f"\n{C.bold}AUR build sorrend:{C.reset}")
        any_high = False
        for i, b in enumerate(builds, 1):
            tag = f"{C.green}explicit{C.reset}" if b.explicit else f"{C.dim}függőség{C.reset}"
            pkgs = ", ".join(sorted(b.pkgs))
            print(f"  {i:2}. {b.base} {C.dim}{sanitize(b.version, False)}{C.reset}  ({pkgs}) [{tag}]")
            if b.flags:
                color = C.red if b.high_risk else C.yellow
                print(f"      {color}! {'; '.join(b.flags)}{C.reset}")
            any_high = any_high or b.high_risk
        print()
        if any_high:
            warn("Magas kockázatú AUR csomag van a tervben (új vagy árva). "
                 "Az AUR-ban terjesztett malware jellemzően ilyen. Alaposan nézd át!")

        if not opts.noconfirm and not confirm("Folytatod?", default=not any_high):
            return 1

        # 0. fázis: hivatalos csomagok a pacmannel
        if repo_targets:
            cmd = sudo_cmd(opts, ["pacman", "-S", "--needed"])
            if opts.noconfirm:
                cmd.append("--noconfirm")
            if run([*cmd, "--", *repo_targets]).returncode != 0:
                raise PyaurError("A pacman hibával állt le a hivatalos csomagoknál.")

        # 1. fázis: minden repó letöltése és felülvizsgálata (build előtt!)
        dirs: dict[str, Path] = {}
        planned = {p for b in builds for p in b.pkgs} | {b.base for b in builds}
        for b in builds:
            d = review_and_apply(b, opts)
            verify_srcinfo_deps(d, pac, planned)
            dirs[b.base] = d

        # 2. fázis: fordítás és telepítés sorrendben
        for b in builds:
            build_and_install(b, dirs[b.base], opts, pac)

    ok("Kész.")
    return 0


def cmd_search(opts, term: str) -> int:
    term = term.strip()
    if len(term) < 2:
        raise PyaurError("A keresőkifejezés legalább 2 karakter legyen.")
    results = aur_search(term, opts.by)
    if not results:
        print("Nincs találat.")
        return 1
    pac = Pacman()
    results.sort(key=lambda r: (-(r.get("Popularity") or 0), str(r.get("Name", ""))))
    lines = []
    for r in results[: opts.limit]:
        rname = str(r.get("Name", ""))
        name = sanitize(rname, False)
        ver = sanitize(str(r.get("Version", "")), False)
        votes = r.get("NumVotes", 0)
        pop = r.get("Popularity", 0) or 0
        oo = " [ELAVULT]" if r.get("OutOfDate") else ""
        orphan = " [ÁRVA]" if not r.get("Maintainer") else ""
        inst = f" {C.cyan}[telepítve]{C.reset}" if PKG_NAME_RE.match(rname) and pac.is_installed(rname) else ""
        desc = sanitize(str(r.get("Description") or ""), False)
        lines.append(f"{C.bold}aur/{name}{C.reset} {C.green}{ver}{C.reset} "
                     f"{C.dim}(+{votes} {pop:.2f}){C.reset}{C.yellow}{oo}{orphan}{C.reset}{inst}\n    {desc}")
    if opts.quiet:
        print("\n".join(sanitize(str(r.get("Name", "")), False) for r in results[: opts.limit]))
    else:
        pager("\n".join(lines))
    return 0


def cmd_info(opts, pkg: str) -> int:
    pkg = validate_pkgname(pkg)
    data = aur_info([pkg]).get(pkg)
    if not data:
        err(f"Nincs ilyen AUR csomag: {sanitize(pkg, False)}")
        return 1
    fields = ["Name", "PackageBase", "Version", "Description", "URL", "License",
              "Maintainer", "CoMaintainers", "Submitter", "NumVotes", "Popularity",
              "FirstSubmitted", "LastModified", "OutOfDate", "Keywords",
              "Depends", "MakeDepends", "CheckDepends", "OptDepends",
              "Conflicts", "Provides", "Replaces"]
    for f in fields:
        v = data.get(f)
        if v in (None, "", [], {}):
            if f == "Maintainer":
                v = f"{C.red}(nincs - árva csomag){C.reset}"
                print(f"{C.bold}{f:<14}{C.reset}: {v}")
            continue
        if f in ("FirstSubmitted", "LastModified", "OutOfDate"):
            v = fmt_date(v)
        if isinstance(v, list):
            v = "  ".join(str(x) for x in v)
        print(f"{C.bold}{f:<14}{C.reset}: {sanitize(str(v), False)}")
    base = urllib.parse.quote(str(data.get("PackageBase") or pkg), safe="")
    print(f"{C.bold}{'AUR oldal':<14}{C.reset}: https://{AUR_HOST}/packages/{base}")
    flags, high = aur_risk_flags(data)
    if flags:
        (warn if high else info)("Figyelem: " + "; ".join(flags))
    return 0


def find_outdated() -> tuple[list[tuple[str, str, str]], list[str]]:
    """Visszaad: ([(név, helyi, távoli)], [AUR-ban nem található])"""
    foreign = Pacman.foreign()
    if not foreign:
        return [], []
    remote = aur_info([n for n, _ in foreign])
    outdated: list[tuple[str, str, str]] = []
    unknown: list[str] = []
    for name, local_ver in foreign:
        r = remote.get(name)
        if not r:
            unknown.append(name)
            continue
        rver = str(r.get("Version", "0"))
        if Pacman.vercmp(rver, local_ver) > 0:
            outdated.append((name, local_ver, rver))
    return outdated, unknown


def cmd_check(opts) -> int:
    """-Qu: csak listáz. Kilépési kód: 0 ha van frissítés, 2 ha nincs (mint a checkupdates)."""
    Pacman()
    outdated, _ = find_outdated()
    for name, lv, rv in outdated:
        if opts.quiet:
            print(name)
        else:
            print(f"{name} {sanitize(lv, False)} -> {sanitize(rv, False)}")
    return 0 if outdated else 2


def cmd_upgrade(opts) -> int:
    Pacman()   # korai ellenőrzés: elérhető-e a pacman

    # Részleges frissítés elkerülése: előbb a rendszer, aztán az AUR (mint yay -Syu).
    if not opts.aur_only:
        info("Rendszerfrissítés (pacman -Syu)...")
        cmd = sudo_cmd(opts, ["pacman", "-Syu"])
        if opts.noconfirm:
            cmd.append("--noconfirm")
        if run(cmd).returncode != 0:
            raise PyaurError("A pacman -Syu hibával állt le - az AUR frissítést kihagyom.")

    info("AUR csomagok ellenőrzése...")
    outdated, unknown = find_outdated()
    if unknown:
        warn("Nincsenek az AUR-ban (helyi build vagy törölt csomag): "
             + ", ".join(sanitize(u, False) for u in unknown))
    if not outdated:
        ok("Minden AUR csomag naprakész.")
        return 0

    print(f"\n{C.bold}Frissíthető:{C.reset}")
    for name, lv, rv in outdated:
        print(f"  {name}  {C.red}{sanitize(lv, False)}{C.reset} -> {C.green}{sanitize(rv, False)}{C.reset}")
    print()
    if not opts.noconfirm and not confirm("Frissíted őket?", default=True):
        return 1
    return cmd_install(opts, [n for n, _, _ in outdated])


def cmd_remove(opts, targets: Sequence[str]) -> int:
    targets = [validate_pkgname(t) for t in targets]
    cmd = sudo_cmd(opts, ["pacman", "-Rns"])
    if opts.noconfirm:
        cmd.append("--noconfirm")
    cmd.append("--")
    cmd += targets
    return run(cmd).returncode


def cmd_orphans(opts) -> int:
    Pacman()
    orphans = sorted(Pacman.orphans())
    if not orphans:
        ok("Nincs árva függőség.")
        return 0
    print(f"{C.bold}Árva függőségek ({len(orphans)}):{C.reset}")
    print("  " + "  ".join(orphans))
    cmd = sudo_cmd(opts, ["pacman", "-Rns"])
    if opts.noconfirm:
        cmd.append("--noconfirm")
    return run([*cmd, "--", *orphans]).returncode   # a pacman maga is megerősítést kér


def cmd_getpkgbuild(opts, targets: Sequence[str]) -> int:
    """-G: AUR repó klónozása az aktuális könyvtárba, build nélkül."""
    require_tools("git")
    targets = [validate_pkgname(t) for t in targets]
    found = aur_info(targets)
    rc = 0
    cwd = Path.cwd().resolve()
    for t in targets:
        meta = found.get(t)
        if not meta:
            err(f"Nincs ilyen AUR csomag: {t}")
            rc = 1
            continue
        base = validate_pkgname(str(meta.get("PackageBase") or t))
        dest = pkg_dir_for(base, cwd)
        if dest.exists():
            err(f"{dest} már létezik - kihagyva.")
            rc = 1
            continue
        url = f"{AUR_GIT_BASE}/{base}.git"
        if git(["clone", "--quiet", "--no-recurse-submodules", "--", url, str(dest)]).returncode != 0:
            err(f"{base}: a git clone nem sikerült.")
            rc = 1
            continue
        ok(f"{base} -> {dest}  (build előtt olvasd el a PKGBUILD-et!)")
    return rc


def cmd_printpkgbuild(opts, pkg: str) -> int:
    """-Gp: a PKGBUILD kiírása stdout-ra (escape-mentesítve)."""
    pkg = validate_pkgname(pkg)
    meta = aur_info([pkg]).get(pkg)
    if not meta:
        err(f"Nincs ilyen AUR csomag: {pkg}")
        return 1
    base = validate_pkgname(str(meta.get("PackageBase") or pkg))
    raw = _http_get(f"{AUR_CGIT_PLAIN}/PKGBUILD?{urllib.parse.urlencode({'h': base})}",
                    accept="text/plain")
    text = raw.decode("utf-8", "replace")
    findings = scan_text("PKGBUILD", text)
    pager(text)
    if findings and sys.stdout.isatty():
        print(f"\n{C.bold}Szkenner:{C.reset}\n{sanitize(format_findings(findings))}")
    return 0


def _is_dangerous_dir(p: Path) -> bool:
    home = Path.home().resolve()
    return p == Path("/") or p == home or p in home.parents


def cmd_clean(opts) -> int:
    cache = Path(opts.cache).expanduser()
    if not cache.exists():
        ok("A cache üres.")
        return 0
    cache = prepare_cache(cache)
    if _is_dangerous_dir(cache):
        raise PyaurError(f"Nem törlöm: {cache} (gyökér vagy home könyvtár).")
    with CacheLock(cache):
        entries = [e for e in cache.iterdir() if e.name != ".pyaur.lock"]
        size = 0
        for e in entries:
            if e.is_dir() and not e.is_symlink():
                for root, _dirs, files in os.walk(e):
                    for f in files:
                        try:
                            size += os.lstat(os.path.join(root, f)).st_size
                        except OSError:
                            pass
        print(f"Cache: {cache}  ({len(entries)} bejegyzés, {size / 1e6:.1f} MB)")
        if not entries:
            return 0
        if not confirm("Törlöd a teljes build cache-t?", default=False):
            return 1
        for e in entries:
            if e.is_symlink() or not e.is_dir():
                e.unlink()                        # symlinket sosem követünk
            else:
                shutil.rmtree(e)
    ok("Cache törölve.")
    return 0


# --------------------------------------------------------------------------- #
#  TUI (curses, csak stdlib)
# --------------------------------------------------------------------------- #

@dataclass
class Row:
    name: str
    version: str
    remote_version: str = ""
    desc: str = ""
    size: str = ""
    required_by: str = ""
    orphan: bool = False
    explicit: bool = True
    marked: bool = False
    status: str = ""

    def compute_status(self) -> None:
        # Egyszer, betöltéskor - nem minden kirajzolásnál (vercmp = subprocess).
        if not self.remote_version:
            self.status = "nincs az AUR-ban"
        elif Pacman.vercmp(self.remote_version, self.version) > 0:
            self.status = f"frissítés: {self.remote_version}"
        else:
            self.status = "naprakész"


class Tui:
    HELP = "↑↓ mozgás  SPACE jelöl  S-Del/d törlés  u frissítés  / keresés  i infó  r újratölt  q kilép"

    def __init__(self, opts) -> None:
        self.opts = opts
        self.rows: list[Row] = []
        self.view: list[Row] = []
        self.cursor = 0
        self.top = 0
        self.filter = ""
        self.status = "Betöltés..."

    # ---- adat ----
    def load(self, check_aur: bool = True) -> None:
        foreign = Pacman.foreign()
        names = [n for n, _ in foreign]
        qi = Pacman.query_info(names)
        orphans = Pacman.orphans()
        explicit = Pacman.explicit()
        remote = {}
        aur_failed = ""
        if check_aur and names:
            try:
                remote = aur_info(names)
            except PyaurError as e:
                aur_failed = f"AUR lekérdezés sikertelen: {e}"

        self.rows = []
        for name, ver in sorted(foreign):
            meta = qi.get(name, {})
            req = meta.get("Required By", "None")
            row = Row(
                name=sanitize(name, False),
                version=sanitize(ver, False),
                remote_version=sanitize(str((remote.get(name) or {}).get("Version", "")), False),
                desc=sanitize(meta.get("Description", ""), False),
                size=meta.get("Installed Size", ""),
                required_by="" if req in ("None", "") else sanitize(req, False),
                orphan=name in orphans,
                explicit=name in explicit,
            )
            row.compute_status()
            self.rows.append(row)
        self.apply_filter()
        if aur_failed:
            self.status = aur_failed
        else:
            up = sum(1 for r in self.rows if r.status.startswith("frissítés"))
            self.status = f"{len(self.rows)} AUR csomag, {up} frissíthető"

    def apply_filter(self) -> None:
        f = self.filter.lower()
        self.view = [r for r in self.rows if not f or f in r.name.lower() or f in r.desc.lower()]
        self.cursor = min(self.cursor, max(0, len(self.view) - 1))
        self.top = min(self.top, self.cursor)

    @property
    def current(self) -> Row | None:
        return self.view[self.cursor] if self.view else None

    def selection(self) -> list[Row]:
        marked = [r for r in self.rows if r.marked]
        if marked:
            return marked
        return [self.current] if self.current else []

    # ---- rajzolás ----
    def draw(self, stdscr) -> None:
        import curses
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < 8 or w < 50:
            try:
                stdscr.addstr(0, 0, "Túl kicsi a terminál.")
            except curses.error:
                pass
            stdscr.refresh()
            return

        title = f" {APP} {VERSION} - telepített AUR csomagok "
        if self.filter:
            title += f"[szűrő: {sanitize(self.filter, False)}] "
        stdscr.attron(curses.A_REVERSE | curses.A_BOLD)
        stdscr.addstr(0, 0, title.ljust(w - 1)[: w - 1])
        stdscr.attroff(curses.A_REVERSE | curses.A_BOLD)

        header = f"{'':3}{'CSOMAG':<28}{'VERZIÓ':<20}{'ÁLLAPOT':<22}{'MÉRET'}"
        stdscr.addstr(1, 0, header[: w - 1], curses.A_UNDERLINE)

        list_h = h - 5
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + list_h:
            self.top = self.cursor - list_h + 1

        for i in range(list_h):
            idx = self.top + i
            if idx >= len(self.view):
                break
            r = self.view[idx]
            mark = "[x]" if r.marked else "[ ]"
            flags = ""
            if r.orphan:
                flags += "*"
            if not r.explicit:
                flags += "d"
            line = (f"{mark}{r.name[:27]:<28}{r.version[:19]:<20}"
                    f"{r.status[:21]:<22}{r.size} {flags}")
            # FONTOS: két color_pair() nem OR-olható össze (a bitmaszkból
            # inicializálatlan párszám lenne) - pontosan egyet választunk.
            if r.orphan:
                pair = 4
            elif r.status.startswith("frissítés"):
                pair = 2
            elif r.status.startswith("nincs"):
                pair = 3
            else:
                pair = 0
            attr = curses.color_pair(pair)
            if idx == self.cursor:
                attr |= curses.A_REVERSE | curses.A_BOLD
            if r.marked:
                attr |= curses.A_BOLD
            try:
                stdscr.addstr(2 + i, 0, line.ljust(w - 1)[: w - 1], attr)
            except curses.error:
                pass

        cur = self.current
        desc = f"  {cur.desc}" if cur else ""
        try:
            stdscr.addstr(h - 3, 0, desc.ljust(w - 1)[: w - 1], curses.A_DIM)
            stdscr.addstr(h - 2, 0, (" " + self.status).ljust(w - 1)[: w - 1],
                          curses.color_pair(1))
            stdscr.addstr(h - 1, 0, self.HELP.ljust(w - 1)[: w - 1], curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()

    # ---- billentyűk ----
    @staticmethod
    def read_key(stdscr) -> tuple[int, str]:
        """
        Visszaad: (curses kód, nyers escape-szekvencia).
        A Shift+Delete a legtöbb terminálban '\\x1b[3;2~' - ncurses ezt KEY_SDC-ként
        adja vissza, HA a terminfo-ban van kDC. Ha nincs, kézzel olvassuk ki.
        """
        ch = stdscr.getch()
        if ch != 27:
            return ch, ""
        seq = ""
        stdscr.nodelay(True)
        try:
            for _ in range(12):
                c = stdscr.getch()
                if c == -1:
                    break
                if 0 <= c < 256:
                    seq += chr(c)
                if seq.endswith("~") or (seq and seq[-1].isalpha() and len(seq) > 1):
                    break
        finally:
            stdscr.nodelay(False)
        return ch, seq

    def prompt(self, stdscr, question: str) -> str:
        import curses
        h, w = stdscr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        try:
            stdscr.addstr(h - 2, 0, (" " + question).ljust(w - 1)[: w - 1], curses.A_REVERSE)
            stdscr.refresh()
            raw = stdscr.getstr(h - 2, len(question) + 2, 64)
            return raw.decode("utf-8", "replace").strip()
        except curses.error:
            return ""
        finally:
            curses.noecho()
            curses.curs_set(0)

    def ask_yes(self, stdscr, question: str) -> bool:
        import curses
        h, w = stdscr.getmaxyx()
        try:
            stdscr.addstr(h - 2, 0, (" " + question + " [i/n]").ljust(w - 1)[: w - 1],
                          curses.color_pair(3) | curses.A_BOLD)
            stdscr.refresh()
        except curses.error:
            pass
        while True:
            c = stdscr.getch()
            if c in (ord("i"), ord("y"), ord("I"), ord("Y")):
                return True
            if c in (ord("n"), ord("N"), 27, ord("q")):
                return False

    def _shell_out(self, stdscr, fn) -> None:
        """curses felfüggesztése egy külső művelet idejére."""
        import curses
        curses.def_prog_mode()
        curses.endwin()
        try:
            fn()
        except PyaurError as e:
            err(str(e))
        except KeyboardInterrupt:
            print("\nMegszakítva.")
        print("\n-- Nyomj Entert a visszatéréshez --")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        curses.reset_prog_mode()
        stdscr.clear()

    # ---- műveletek ----
    def do_remove(self, stdscr) -> None:
        sel = [r for r in self.selection() if r]
        if not sel:
            return
        names = [r.name for r in sel]
        blocked = []
        for r in sel:
            if r.required_by:
                deps = [d for d in r.required_by.split() if d not in names]
                if deps:
                    blocked.append((r.name, deps))

        if blocked:
            lines = "; ".join(f"{n} <- {', '.join(d[:3])}" for n, d in blocked)
            self.status = f"FIGYELEM, más csomag függ tőlük: {lines}"
            self.draw(stdscr)
            if not self.ask_yes(stdscr, "Mégis megpróbálod? (a pacman megvédhet)"):
                self.status = "Törlés megszakítva."
                return
        else:
            self.draw(stdscr)
            if not self.ask_yes(stdscr, f"Törlöd: {', '.join(names[:6])}"
                                        f"{' ...' if len(names) > 6 else ''}?"):
                self.status = "Törlés megszakítva."
                return

        rc_box = [1]

        def _remove() -> None:
            cmd = sudo_cmd(self.opts, ["pacman", "-Rns", "--", *names])
            print(f"\n$ {' '.join(cmd)}\n")
            rc_box[0] = run(cmd).returncode

        self._shell_out(stdscr, _remove)
        for r in sel:
            r.marked = False
        self.load()
        self.status = "Törölve." if rc_box[0] == 0 else f"A pacman hibakóddal tért vissza ({rc_box[0]})."

    def do_upgrade(self, stdscr) -> None:
        targets = [r.name for r in self.rows if r.status.startswith("frissítés")]
        if not targets:
            self.status = "Nincs frissíthető csomag."
            return
        self.draw(stdscr)
        if not self.ask_yes(stdscr, f"{len(targets)} csomag frissítése?"):
            return
        self._shell_out(stdscr, lambda: cmd_install(self.opts, targets))
        self.load()

    def show_info(self, stdscr) -> None:
        r = self.current
        if not r:
            return
        self._shell_out(stdscr, lambda: run(["pacman", "-Qi", "--", r.name]))

    # ---- főciklus ----
    def run_ui(self, stdscr) -> None:
        import curses
        curses.curs_set(0)
        curses.use_default_colors()
        for i, fg in enumerate([curses.COLOR_CYAN, curses.COLOR_GREEN,
                                curses.COLOR_RED, curses.COLOR_YELLOW], start=1):
            curses.init_pair(i, fg, -1)
        stdscr.keypad(True)

        self.load()
        while True:
            self.draw(stdscr)
            ch, seq = self.read_key(stdscr)

            shift_del = (ch == curses.KEY_SDC) or seq in ("[3;2~", "[3;6~", "O3;2~")
            plain_del = (ch == curses.KEY_DC) or seq == "[3~"

            if ch in (ord("q"), ord("Q")):
                return
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.cursor = min(self.cursor + 1, max(0, len(self.view) - 1))
            elif ch in (curses.KEY_UP, ord("k")):
                self.cursor = max(self.cursor - 1, 0)
            elif ch == curses.KEY_NPAGE:
                self.cursor = min(self.cursor + 10, max(0, len(self.view) - 1))
            elif ch == curses.KEY_PPAGE:
                self.cursor = max(self.cursor - 10, 0)
            elif ch == curses.KEY_HOME:
                self.cursor = 0
            elif ch == curses.KEY_END:
                self.cursor = max(0, len(self.view) - 1)
            elif ch == ord(" "):
                if self.current:
                    self.current.marked = not self.current.marked
                    self.cursor = min(self.cursor + 1, max(0, len(self.view) - 1))
            elif shift_del or plain_del or ch == ord("d"):
                self.do_remove(stdscr)
            elif ch in (ord("u"), ord("U")):
                self.do_upgrade(stdscr)
            elif ch in (ord("i"), ord("I")):
                self.show_info(stdscr)
            elif ch in (ord("r"), ord("R")):
                self.status = "Újratöltés..."
                self.draw(stdscr)
                self.load()
            elif ch == ord("/"):
                self.filter = self.prompt(stdscr, "Keresés:")
                self.apply_filter()
            elif ch == 27 and not seq:
                if self.filter:
                    self.filter = ""
                    self.apply_filter()
            elif ch == curses.KEY_RESIZE:
                stdscr.clear()


def cmd_tui(opts) -> int:
    import curses
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        raise PyaurError("A TUI-hoz terminál kell.")
    Pacman()  # korai ellenőrzés: van-e pacman
    tui = Tui(opts)
    curses.wrapper(tui.run_ui)
    return 0


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

PACMAN_ALIASES: dict[str, list[str]] = {
    "-S": ["install"], "--sync": ["install"],
    "-Ss": ["search"], "-Ssq": ["search", "-q"],
    "-Si": ["info"], "-Sii": ["info"],
    "-Syu": ["upgrade"], "-Su": ["upgrade"], "-Syyu": ["upgrade"],
    "-Sua": ["upgrade", "--aur-only"], "-Syua": ["upgrade", "--aur-only"],
    "-Qu": ["check"], "-Qua": ["check"], "-Quq": ["check", "-q"],
    "-R": ["remove"], "-Rs": ["remove"], "-Rns": ["remove"], "-Rsn": ["remove"],
    "-Qdt": ["orphans"], "-Qdtq": ["orphans"], "-Yc": ["orphans"],
    "-G": ["getpkgbuild"], "-Gp": ["pkgbuild"],
    "-Sc": ["clean"], "-Scc": ["clean"],
    "-Qm": ["tui"], "-Q": ["tui"],
}


def translate_argv(argv: list[str]) -> list[str]:
    """pacman-stílusú kapcsolók -> alparancsok, hogy megmaradjon a megszokott UX."""
    for i, a in enumerate(argv):
        if a in PACMAN_ALIASES:
            return argv[:i] + PACMAN_ALIASES[a] + argv[i + 1:]
        if not a.startswith("-"):
            break
    return argv


def positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("egész szám kell")
    if n < 1:
        raise argparse.ArgumentTypeError("legalább 1 legyen")
    return n


def default_sudo() -> str:
    env = os.environ.get("PYAUR_SUDO")
    if env is not None:
        return env
    for cand in ("sudo", "doas", "run0"):
        if shutil.which(cand):
            return cand
    return "sudo"


def add_common(p: argparse.ArgumentParser, suppress: bool) -> None:
    """
    Globális kapcsolók. Az alparancsokra is felkerülnek SUPPRESS alapértékkel,
    így a `pyaur -S foo --noconfirm` is működik (nem csak a `pyaur --noconfirm -S foo`).
    """
    def dflt(v):
        return argparse.SUPPRESS if suppress else v

    p.add_argument("--cache", default=dflt(str(DEFAULT_CACHE)), help="build cache könyvtár")
    p.add_argument("--sudo", default=dflt(default_sudo()),
                   help="privilégium-emelő parancs (sudo / doas / run0 / üres)")
    p.add_argument("--noconfirm", action="store_true", default=dflt(False),
                   help="kérdések kihagyása (a PKGBUILD review-t NEM hagyja ki)")
    p.add_argument("--noreview", action="store_true", default=dflt(False),
                   help="PKGBUILD felülvizsgálat kihagyása (NEM AJÁNLOTT)")
    p.add_argument("--clean-build", action="store_true", default=dflt(False),
                   help="repó törlése klónozás előtt")
    p.add_argument("--clean", dest="clean", action="store_true", default=dflt(True),
                   help="makepkg -c: forrásfák takarítása build után (alapértelmezett)")
    p.add_argument("--no-clean", dest="clean", action="store_false", default=dflt(True))
    p.add_argument("--rebuild", action="store_true", default=dflt(False),
                   help="újrafordítás akkor is, ha naprakész")
    p.add_argument("--rmdeps", action="store_true", default=dflt(False),
                   help="makepkg --rmdeps: build-függőségek eltávolítása utána")
    p.add_argument("--install-split-deps", action="store_true", default=dflt(False),
                   help="split package minden alcsomagját telepítse --asdeps módon")
    p.add_argument("--limit", type=positive_int, default=dflt(25), help="találatok száma kereséskor")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=APP,
        description=f"{APP} {VERSION} - minimalista, biztonságtudatos AUR helper",
        epilog="pacman-stílusú kapcsolók is mennek: -S, -Ss, -Si, -Syu, -Sua, -Qu, "
               "-R, -Qdt, -G, -Gp, -Sc",
    )
    p.add_argument("--version", action="version", version=f"{APP} {VERSION}")
    add_common(p, suppress=False)

    common = argparse.ArgumentParser(add_help=False)
    add_common(common, suppress=True)

    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("install", parents=[common], help="csomag(ok) telepítése az AUR-ból")
    s.add_argument("packages", nargs="+")
    s = sub.add_parser("search", parents=[common], help="keresés az AUR-ban")
    s.add_argument("term")
    s.add_argument("--by", choices=SEARCH_FIELDS, default="name-desc", help="keresési mező")
    s.add_argument("-q", "--quiet", action="store_true", help="csak a csomagnevek")
    s = sub.add_parser("info", parents=[common], help="AUR csomag adatai")
    s.add_argument("package")
    s = sub.add_parser("upgrade", parents=[common], help="rendszer + AUR csomagok frissítése")
    s.add_argument("--aur-only", action="store_true", help="a pacman -Syu kihagyása")
    s = sub.add_parser("check", parents=[common], help="frissíthető AUR csomagok listája")
    s.add_argument("-q", "--quiet", action="store_true", help="csak a csomagnevek")
    s = sub.add_parser("remove", parents=[common], help="eltávolítás (pacman -Rns)")
    s.add_argument("packages", nargs="+")
    sub.add_parser("orphans", parents=[common], help="árva függőségek eltávolítása")
    s = sub.add_parser("getpkgbuild", parents=[common], help="AUR repó letöltése ide (build nélkül)")
    s.add_argument("packages", nargs="+")
    s = sub.add_parser("pkgbuild", parents=[common], help="PKGBUILD kiírása")
    s.add_argument("package")
    sub.add_parser("clean", parents=[common], help="build cache törlése")
    sub.add_parser("tui", parents=[common], help="interaktív lista (alapértelmezett)")
    return p


def main() -> int:
    if hasattr(signal, "SIGPIPE"):   # ne dobjon BrokenPipeError-t a `pyaur -Ss x | head`
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    if os.geteuid() == 0:
        err("Ne futtasd rootként! A makepkg sem engedi, és a build szkriptek "
            "root joggal futnának. Sima felhasználóként indítsd; a pacman-hívásokhoz "
            "sudo-t kérünk majd.")
        return 1

    os.umask(0o022)
    parser = build_parser()
    opts = parser.parse_args(translate_argv(sys.argv[1:]))
    if opts.sudo and not shutil.which(opts.sudo):
        warn(f"'{opts.sudo}' nem található; privilégium-emelés nélkül próbálom.")
        opts.sudo = ""

    command = opts.command or "tui"
    try:
        if command == "install":
            return cmd_install(opts, opts.packages)
        if command == "search":
            return cmd_search(opts, opts.term)
        if command == "info":
            return cmd_info(opts, opts.package)
        if command == "upgrade":
            return cmd_upgrade(opts)
        if command == "check":
            return cmd_check(opts)
        if command == "remove":
            return cmd_remove(opts, opts.packages)
        if command == "orphans":
            return cmd_orphans(opts)
        if command == "getpkgbuild":
            return cmd_getpkgbuild(opts, opts.packages)
        if command == "pkgbuild":
            return cmd_printpkgbuild(opts, opts.package)
        if command == "clean":
            return cmd_clean(opts)
        return cmd_tui(opts)
    except PyaurError as e:
        err(str(e))
        return 1
    except KeyboardInterrupt:
        print("\nMegszakítva.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
