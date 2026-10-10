# pyaur

🌐 **Magyar** · [English](README.en.md) · [Deutsch](README.de.md) · [Polski](README.pl.md)

**Minimalista, biztonságtudatos AUR helper Pythonban, a `yay` és a `paru` alternatívája.**

A `pyaur` egyetlen Python fájl, ami csak a standard library-t használja. Telepít, frissít,
keres és eltávolít csomagokat az [Arch User Repository](https://aur.archlinux.org)-ból.
Ugyanúgy a megszokott pacman-stílusú kapcsolókkal használható (`-S`, `-Ss`, `-Syu`, `-R`…),
van benne egy egyszerű `curses` TUI is, és fő szempont volt, hogy **semmilyen idegen kód ne
fusson le úgy, hogy előtte nem nézted át**.

> ⚠️ Az AUR csomagokat felhasználók töltik fel, és **nem** ellenőrzi őket senki.
> A PKGBUILD egy bash szkript, ami a gépeden fut. A `pyaur` ebben segít, de a
> felülvizsgálatot nem végzi el helyetted.

---

## Tartalom

- [Funkciók](#funkciók)
- [Követelmények](#követelmények)
- [Telepítés](#telepítés)
- [Használat](#használat)
- [Kapcsolók](#kapcsolók)
- [TUI](#tui)
- [Biztonsági modell](#biztonsági-modell)
- [Hogyan működik egy telepítés](#hogyan-működik-egy-telepítés)
- [Környezeti változók](#környezeti-változók)
- [Kilépési kódok](#kilépési-kódok)
- [Korlátok](#korlátok)
- [Licenc](#licenc)

---

## Funkciók

- **Telepítés** az AUR-ból, rekurzív függőségfeloldással (AUR → AUR függőségek is),
  helyes build-sorrenddel és split package támogatással.
- **Hivatalos tárolók felismerése**: ha egy kért csomag a hivatalos tárolóban van, a
  `pacman` telepíti, nem az AUR-ból fordul le.
- **Rendszerfrissítés** (`-Syu`): előbb `pacman -Syu`, aztán az AUR csomagok, így
  elkerülhető a részleges frissítés. `-Sua` esetén csak az AUR csomagok frissülnek.
- **Keresés** (`-Ss`) népszerűség szerint rendezve, a telepített, elavult és árva
  csomagok jelölésével, és több keresési mezővel (`--by maintainer`, `--by provides`…).
- **Csomaginfó** (`-Si`) dátumokkal, karbantartóval és kockázati jelzésekkel.
- **Frissítések listázása** (`-Qu`), ami telepítés nélkül, szkriptből is használható.
- **Árva függőségek** eltávolítása (`-Qdt` / `-Yc`).
- **PKGBUILD letöltése** (`-G`) vagy kiírása (`-Gp`) build nélkül.
- **Build cache takarítás** (`-Sc`).
- **Interaktív TUI**: a telepített AUR csomagok listája, ahol lehet jelölni, törölni,
  frissíteni és szűrni.
- Nincs külső függőség: `python`, `pacman`, `git` és `base-devel` kell hozzá.

## Követelmények

- Arch Linux vagy Arch-alapú disztribúció (pl. EndeavourOS, Manjaro, CachyOS…)
- Python ≥ 3.8
- `pacman`, `git`, `base-devel` (`makepkg`, `vercmp`)
- `sudo`, `doas` vagy `run0` a jogosultság-emeléshez
- opcionálisan `less` a hosszú felülvizsgálati szöveg lapozásához

```bash
sudo pacman -S --needed python git base-devel less
```

## Telepítés

Klónozd vagy töltsd le ezt a repót (a GitHub oldalon: **Code → Download ZIP**), majd a
könyvtárában futtasd:

```bash
install -Dm755 pyaur.py ~/.local/bin/pyaur
```

Ügyelj rá, hogy a `~/.local/bin` benne legyen a `PATH`-ban. Rendszerszintű telepítéshez
ez a parancs:

```bash
sudo install -Dm755 pyaur.py /usr/local/bin/pyaur
```

> A `pyaur`-t **ne futtasd rootként**, ezt meg is tagadja. Sima felhasználóként indítsd,
> a `pacman` hívásokhoz magától kér `sudo`-t.

## Használat

| Parancs | Alparancs | Mit csinál |
|---|---|---|
| `pyaur` | `tui` | Interaktív lista a telepített AUR csomagokról |
| `pyaur -S <csomag>…` | `install` | Telepítés (AUR vagy hivatalos tároló) |
| `pyaur -Ss <kifejezés>` | `search` | Keresés az AUR-ban |
| `pyaur -Ssq <kifejezés>` | `search -q` | Keresés, csak a csomagneveket írja ki |
| `pyaur -Si <csomag>` | `info` | AUR csomag adatai |
| `pyaur -Syu` | `upgrade` | `pacman -Syu`, majd az AUR csomagok frissítése |
| `pyaur -Sua` | `upgrade --aur-only` | Csak az AUR csomagok frissítése |
| `pyaur -Qu` | `check` | Frissíthető AUR csomagok listája, telepítés nélkül |
| `pyaur -R <csomag>…` | `remove` | Eltávolítás (`pacman -Rns`) |
| `pyaur -Qdt` / `-Yc` | `orphans` | Árva függőségek eltávolítása |
| `pyaur -G <csomag>…` | `getpkgbuild` | Az AUR git repó letöltése az aktuális könyvtárba |
| `pyaur -Gp <csomag>` | `pkgbuild` | PKGBUILD kiírása, gyorsszkenneléssel |
| `pyaur -Sc` | `clean` | Build cache törlése |

Példák:

```bash
pyaur -S google-chrome
pyaur -Ss --by maintainer jguer
pyaur -Syu
pyaur -Qu -q | wc -l                   # hány AUR frissítés van
pyaur -S foo --noconfirm               # a kapcsoló a parancs után is jó
pyaur -Gp yay | less                   # PKGBUILD megnézése telepítés előtt
```

## Kapcsolók

Az alábbi kapcsolók a parancs előtt és után is megadhatók.

| Kapcsoló | Leírás |
|---|---|
| `--noconfirm` | Kihagyja a „Folytatod?” jellegű kérdéseket. **A PKGBUILD felülvizsgálatot nem hagyja ki.** |
| `--noreview` | Kihagyja a PKGBUILD felülvizsgálatot. **Nem ajánlott.** A szkenner magas kockázatú találatait ilyenkor is kiírja. |
| `--rebuild` | Akkor is újrafordít, ha a csomag naprakész (`makepkg -f`) |
| `--clean-build` | Klónozás előtt törli a csomag cache-könyvtárát |
| `--clean` / `--no-clean` | Build után takarítja a `src/` és `pkg/` könyvtárat (`makepkg -c`, ez az alapértelmezés) |
| `--rmdeps` | Build után eltávolítja a build-függőségeket (`makepkg --rmdeps`) |
| `--install-split-deps` | Split package esetén a többi alcsomagot is telepíti `--asdeps` módon |
| `--sudo CMD` | Jogosultság-emelő parancs (`sudo`, `doas`, `run0`, vagy üres) |
| `--cache DIR` | Build cache helye (alapértelmezés: `~/.cache/pyaur`) |
| `--limit N` | Keresési találatok maximális száma (alapértelmezés: 25) |
| `--by FIELD` | (`search`) Keresési mező: `name`, `name-desc`, `maintainer`, `depends`, `makedepends`, `optdepends`, `checkdepends`, `provides`, `conflicts`, `replaces`, `keywords`, `groups`, `submitter` |
| `-q`, `--quiet` | (`search`, `check`) Csak a csomagneveket írja ki |
| `--aur-only` | (`upgrade`) Kihagyja a `pacman -Syu`-t |

## TUI

Argumentum nélkül indítva a `pyaur` megmutatja a telepített idegen (AUR) csomagokat, a
helyi és az AUR-beli verziót, az állapotot és a méretet.

| Billentyű | Művelet |
|---|---|
| `↑` `↓` / `j` `k` | mozgás |
| `PgUp` `PgDn` `Home` `End` | lapozás |
| `Space` | jelölés |
| `Shift+Del` / `Del` / `d` | jelöltek (vagy az aktuális) törlése |
| `u` | az összes frissíthető csomag frissítése |
| `/` | szűrés név vagy leírás alapján (`Esc` törli) |
| `i` | `pacman -Qi` az aktuális csomagra |
| `r` | újratöltés |
| `q` | kilépés |

Színek: zöld = frissíthető, piros = nincs az AUR-ban, sárga + `*` = árva függőség,
`d` = függőségként telepítve.

## Biztonsági modell

A `pyaur` alapelve, hogy az AUR-ból érkező minden adat **megbízhatatlan**, amíg a
felhasználó jóvá nem hagyja.

### Felülvizsgálat (review)

- **A PKGBUILD soha nem fut le jóváhagyás nélkül.** A `--noconfirm` sem hagyja ki ezt a
  lépést, és ha nincs terminál, a `pyaur` inkább hibával kilép.
- **Pontosan azt nézed át, ami lefordul.** A review szövege közvetlenül a git
  objektumokból készül a jóváhagyandó commitra, nem a munkafából. Jóváhagyás után a
  munkafa erre a commitra áll (`git merge --ff-only`), és a `pyaur` ellenőrzi, hogy a
  `HEAD` valóban ez lett.
- **A jóváhagyás rögzítve van.** A legutóbb elfogadott commit a repó `.git/pyaur.json`
  fájljába kerül. Ha megszakítod a review-t, a következő futás **újra kéri** (a régi
  változatban ilyenkor review nélkül lefordult volna). Frissítéskor a review a legutóbb
  elfogadott commithoz képesti `git diff`, első alkalommal minden fájl teljes tartalma.
- **A helyi módosítások is látszanak.** Ha a cache-ben lévő fájlokat valami módosította,
  a diffjük bekerül a review-ba. Kivétel a `makepkg` által átírt `pkgver=` sor a `-git`
  csomagoknál, azt a `pyaur` automatikusan visszaállítja.
- A review tartalmazza a **repó fájllistáját** (futtatható fájlok, szimbolikus linkek és
  submodule-ok jelölve), az **új commitokat a szerzőkkel**, és a `.SRCINFO` alapján
  **letöltött forrásokat**.

### Heurisztikus szkenner

A review elején és végén összesítés látható a gyanús mintákról. Amit keres:

| Súlyosság | Minta |
|---|---|
| `[!!]` | `curl … \| sh`, `base64 -d`, `xxd -r`, `/dev/tcp/`, `nc`/`socat`, setuid `chmod`, `sudo`/`doas`/`su` a szkriptben, `rm -rf /` vagy `~`, `~/.ssh`, `~/.gnupg`, `.bashrc`, `/etc/sudoers`, `/etc/shadow`, `LD_PRELOAD`, kriptobányász nyomok, nyers IP-cím URL-ben, gyakran visszaélt hosztok (pastebin, transfer.sh, Discord webhook, Telegram API…), láthatatlan és irányváltó Unicode karakterek, symlink és submodule a repóban, titkosítatlan (`http`/`ftp`/`git://`) forrás, `SKIP` ellenőrzőösszeg nem-VCS forrásnál |
| `[ !]` | `eval`, inline `python -c`/`perl -e`, `systemctl enable`, `crontab`, hosszú base64 vagy hex blob, bináris fájl a repóban, `.install` szkript (ez rootként fut) |

> A szkenner **heurisztika, nem garancia.** Arra jó, hogy egy hosszú PKGBUILD-ben a
> szem a gyanús sorokra essen. Ha nincs találat, attól még a csomag nem biztonságos.

### AUR metaadat alapú figyelmeztetések

Telepítési terv készítésekor minden AUR csomag mellett megjelenik:

- **ÚJ csomag** (14 napnál fiatalabb). Az AUR-ban terjesztett malware jellemzően így néz ki.
- **ÁRVA** csomag, aminek nincs karbantartója, így bárki átveheti.
- **kevés szavazat**
- **elavultnak jelölve**
- **KARBANTARTÓ-VÁLTÁS**: a `pyaur` megjegyzi a csomag karbantartóját, és ha ez
  frissítéskor megváltozik, hangosan szól.

Ha a tervben magas kockázatú csomag van, a „Folytatod?” kérdés alapértelmezett válasza
**nem** lesz.

### Egyéb védelmek

| Terület | Védelem |
|---|---|
| Parancsfuttatás | Soha nincs `shell=True`, minden argumentum listában megy, a csomagnevek előtt `--` áll |
| Csomagnevek | Szigorú regex (`^[a-zA-Z0-9][a-zA-Z0-9@._+-]{0,127}$`), mielőtt URL-be vagy útvonalba kerülnének |
| Útvonalak | Path traversal és symlink elleni védelem (`resolve()` + szülő-ellenőrzés) |
| Terminál | Minden idegen szöveg ANSI/OSC escape- és bidi-mentesítve van. A `less` `-R` nélkül és `LESSSECURE=1`-gyel fut (shell escape tiltva) |
| HTTP | Csak `https://aur.archlinux.org`, TLS ≥ 1.2 tanúsítvány-ellenőrzéssel, átirányítás csak az AUR-on belül, 16 MiB válaszlimit, timeout |
| Git | Csak HTTPS protokoll (`GIT_ALLOW_PROTOCOL`, `protocol.allow`), hookok és fsmonitor tiltva, nincs submodule-rekurzió, a meglévő repó origin URL-je ellenőrizve (cache-mérgezés ellen), nincs `git pull` |
| Cache | `0700` jogosultság, tulajdonos-ellenőrzés, és a mások által írható cache-t szigorítja. Fájlzár (`flock`) véd a párhuzamos futtatás ellen. A `-Sc` nem követ symlinket, és a home vagy a `/` törlését megtagadja |
| Jogosultság | Rootként nem indul. A `makepkg` sima felhasználóként fut, csak a `pacman` kap `sudo`-t |
| Telepítés | A függőségek `--asdeps` módon kerülnek fel, így a `-Qdt` később eltakarítja őket |

## Hogyan működik egy telepítés

1. **Tervezés.** A `pyaur` lekéri az AUR RPC-ből a csomagadatokat, rekurzívan feloldja a
   függőségeket (`pacman -T`, ami a verziókorlátot és a provides-t is figyelembe veszi), és
   kiírja a build-sorrendet a kockázati jelzésekkel.
2. **Hivatalos csomagok.** Ami a tárolóban van, azt a `pacman -S` telepíti.
3. **Letöltés és felülvizsgálat.** A `pyaur` minden AUR repót klónoz vagy fetch-el, és
   **mindegyiket átnézeted, még a fordítás előtt.** Így nem fordul le félig egy lánc,
   mielőtt a harmadik PKGBUILD-ről kiderülne, hogy gyanús.
4. **Fordítás és telepítés.** Sorrendben jön a `makepkg -s`, majd a `pacman -U`.

## Környezeti változók

| Változó | Jelentés |
|---|---|
| `PYAUR_CACHE` | Build cache könyvtár (felülírja a `~/.cache/pyaur`-t) |
| `PYAUR_SUDO` | Jogosultság-emelő parancs. Üres érték esetén nincs emelés |
| `NO_COLOR` | Kikapcsolja a színeket |

## Kilépési kódok

| Kód | Jelentés |
|---|---|
| `0` | Siker. `check` esetén: van frissítés |
| `1` | Hiba vagy megszakítás |
| `2` | (`check`) Nincs frissítés, ugyanúgy, mint a `checkupdates` |
| `130` | Ctrl+C |

## Korlátok

- A `-git` és más VCS csomagokat a `-Syu` csak akkor frissíti, ha az AUR-ban nőtt a
  verziószám (nincs `--devel` mód).
- Nincs PGP-kulcs import. Ha a `validpgpkeys` kulcs hiányzik, a `makepkg` hibát ad, és
  a kulcsot neked kell importálnod (`gpg --recv-keys …`).
- A heurisztikus szkenner nem helyettesíti a saját szemedet.

## Licenc

A `pyaur` szabad szoftver: a **GNU General Public License 2-es verziója** (GPL-2.0-only)
szerint terjesztheted és módosíthatod. A teljes szöveg a [LICENSE](LICENSE) fájlban van.

Ezt a programot abban a reményben terjesztjük, hogy hasznos lesz, de **mindenféle
garancia nélkül**, még az eladhatóságra vagy egy adott célra való alkalmasságra
vonatkozó hallgatólagos garancia nélkül is.
