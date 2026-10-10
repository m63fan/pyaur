# pyaur

🌐 [Magyar](README.md) · [English](README.en.md) · **Deutsch** · [Polski](README.pl.md)

**Ein minimalistischer, sicherheitsbewusster AUR-Helper in Python – eine Alternative zu `yay` und `paru`.**

`pyaur` ist eine einzelne Python-Datei, die nur die Standardbibliothek verwendet. Das Programm
installiert, aktualisiert, sucht und entfernt Pakete aus dem
[Arch User Repository](https://aur.archlinux.org). Es versteht die gewohnten pacman-Optionen
(`-S`, `-Ss`, `-Syu`, `-R`…) und bringt eine einfache `curses`-TUI mit. Oberstes Ziel ist, dass
**kein fremder Code ausgeführt wird, bevor du ihn geprüft hast**.

> ⚠️ AUR-Pakete werden von Nutzern hochgeladen und von **niemandem** geprüft. Ein PKGBUILD
> ist ein Bash-Skript, das auf deinem Rechner läuft. `pyaur` hilft dir bei der Prüfung,
> nimmt sie dir aber nicht ab.

> ℹ️ Die Oberfläche und die Meldungen des Programms sind auf Ungarisch.

---

## Inhalt

- [Funktionen](#funktionen)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Verwendung](#verwendung)
- [Optionen](#optionen)
- [TUI](#tui)
- [Sicherheitsmodell](#sicherheitsmodell)
- [Ablauf einer Installation](#ablauf-einer-installation)
- [Umgebungsvariablen](#umgebungsvariablen)
- [Exit-Codes](#exit-codes)
- [Einschränkungen](#einschränkungen)
- [Lizenz](#lizenz)

---

## Funktionen

- **Installation** aus dem AUR mit rekursiver Abhängigkeitsauflösung (auch AUR → AUR),
  korrekter Build-Reihenfolge und Unterstützung für Split-Pakete.
- **Erkennung offizieller Repositories**: Liegt ein angefordertes Paket in einem offiziellen
  Repository, installiert es `pacman`, statt es aus dem AUR zu bauen.
- **Systemaktualisierung** (`-Syu`): zuerst `pacman -Syu`, danach die AUR-Pakete. So werden
  Teilaktualisierungen vermieden. Mit `-Sua` werden nur die AUR-Pakete aktualisiert.
- **Suche** (`-Ss`), nach Beliebtheit sortiert. Installierte, veraltete und verwaiste Pakete
  sind markiert, und es gibt mehrere Suchfelder (`--by maintainer`, `--by provides`…).
- **Paketinformationen** (`-Si`) mit Datumsangaben, Maintainer und Risikohinweisen.
- **Update-Liste** (`-Qu`): zeigt verfügbare Updates, ohne etwas zu installieren, und eignet
  sich damit auch für Skripte.
- Entfernen **verwaister Abhängigkeiten** (`-Qdt` / `-Yc`).
- **PKGBUILD herunterladen** (`-G`) oder ausgeben (`-Gp`), ohne zu bauen.
- **Build-Cache aufräumen** (`-Sc`).
- **Interaktive TUI**: eine Liste der installierten AUR-Pakete, in der du Pakete markieren,
  entfernen, aktualisieren und filtern kannst.
- Keine externen Abhängigkeiten: Es werden nur `python`, `pacman`, `git` und `base-devel`
  benötigt.

## Voraussetzungen

- Arch Linux oder eine Arch-basierte Distribution (z. B. EndeavourOS, Manjaro, CachyOS…)
- Python ≥ 3.8
- `pacman`, `git`, `base-devel` (`makepkg`, `vercmp`)
- `sudo`, `doas` oder `run0` zur Rechteausweitung
- optional `less`, um lange Prüfausgaben seitenweise anzuzeigen

```bash
sudo pacman -S --needed python git base-devel less
```

## Installation

Klone oder lade dieses Repository herunter (auf der GitHub-Seite: **Code → Download ZIP**)
und führe in seinem Verzeichnis aus:

```bash
install -Dm755 pyaur.py ~/.local/bin/pyaur
```

Achte darauf, dass `~/.local/bin` in deinem `PATH` liegt. Für eine systemweite Installation
nimm diesen Befehl:

```bash
sudo install -Dm755 pyaur.py /usr/local/bin/pyaur
```

> **Führe `pyaur` nicht als root aus**, das Programm verweigert dann den Start. Starte es als
> normaler Benutzer; für `pacman` ruft es bei Bedarf selbst `sudo` auf.

## Verwendung

| Befehl | Unterbefehl | Funktion |
|---|---|---|
| `pyaur` | `tui` | Interaktive Liste der installierten AUR-Pakete |
| `pyaur -S <paket>…` | `install` | Installieren (aus dem AUR oder einem offiziellen Repository) |
| `pyaur -Ss <begriff>` | `search` | Im AUR suchen |
| `pyaur -Ssq <begriff>` | `search -q` | Suchen und nur die Paketnamen ausgeben |
| `pyaur -Si <paket>` | `info` | Details eines AUR-Pakets anzeigen |
| `pyaur -Syu` | `upgrade` | `pacman -Syu` ausführen, danach die AUR-Pakete aktualisieren |
| `pyaur -Sua` | `upgrade --aur-only` | Nur die AUR-Pakete aktualisieren |
| `pyaur -Qu` | `check` | Aktualisierbare AUR-Pakete auflisten, ohne zu installieren |
| `pyaur -R <paket>…` | `remove` | Entfernen (`pacman -Rns`) |
| `pyaur -Qdt` / `-Yc` | `orphans` | Verwaiste Abhängigkeiten entfernen |
| `pyaur -G <paket>…` | `getpkgbuild` | Das AUR-Git-Repository ins aktuelle Verzeichnis laden |
| `pyaur -Gp <paket>` | `pkgbuild` | Den PKGBUILD mit einem Schnellscan ausgeben |
| `pyaur -Sc` | `clean` | Den Build-Cache löschen |

Beispiele:

```bash
pyaur -S google-chrome
pyaur -Ss --by maintainer jguer
pyaur -Syu
pyaur -Qu -q | wc -l                   # wie viele AUR-Updates verfügbar sind
pyaur -S foo --noconfirm               # Optionen funktionieren auch nach dem Befehl
pyaur -Gp yay | less                   # den PKGBUILD vor der Installation lesen
```

## Optionen

Die folgenden Optionen können vor oder nach dem Befehl stehen.

| Option | Beschreibung |
|---|---|
| `--noconfirm` | Überspringt Rückfragen wie „Fortfahren?“. **Die PKGBUILD-Prüfung wird dabei nicht übersprungen.** |
| `--noreview` | Überspringt die PKGBUILD-Prüfung. **Nicht empfohlen.** Funde des Scanners mit hohem Risiko werden trotzdem ausgegeben. |
| `--rebuild` | Baut neu, auch wenn das Paket aktuell ist (`makepkg -f`) |
| `--clean-build` | Löscht vor dem Klonen das Cache-Verzeichnis des Pakets |
| `--clean` / `--no-clean` | Räumt nach dem Build `src/` und `pkg/` auf (`makepkg -c`, Standard) |
| `--rmdeps` | Entfernt nach dem Build die Build-Abhängigkeiten (`makepkg --rmdeps`) |
| `--install-split-deps` | Installiert bei Split-Paketen auch die übrigen Unterpakete mit `--asdeps` |
| `--sudo CMD` | Befehl zur Rechteausweitung (`sudo`, `doas`, `run0` oder leer) |
| `--cache DIR` | Speicherort des Build-Caches (Standard: `~/.cache/pyaur`) |
| `--limit N` | Maximale Anzahl an Suchergebnissen (Standard: 25) |
| `--by FIELD` | (`search`) Suchfeld: `name`, `name-desc`, `maintainer`, `depends`, `makedepends`, `optdepends`, `checkdepends`, `provides`, `conflicts`, `replaces`, `keywords`, `groups`, `submitter` |
| `-q`, `--quiet` | (`search`, `check`) Gibt nur die Paketnamen aus |
| `--aur-only` | (`upgrade`) Überspringt `pacman -Syu` |

## TUI

Ohne Argumente zeigt `pyaur` die installierten fremden (AUR-)Pakete mit lokaler und
AUR-Version, Status und Größe an.

| Taste | Aktion |
|---|---|
| `↑` `↓` / `j` `k` | bewegen |
| `PgUp` `PgDn` `Home` `End` | blättern |
| `Leertaste` | markieren |
| `Shift+Entf` / `Entf` / `d` | markierte (oder das aktuelle) Paket(e) entfernen |
| `u` | alle aktualisierbaren Pakete aktualisieren |
| `/` | nach Name oder Beschreibung filtern (`Esc` setzt den Filter zurück) |
| `i` | `pacman -Qi` für das aktuelle Paket ausführen |
| `r` | neu laden |
| `q` | beenden |

Farben: grün = aktualisierbar, rot = nicht im AUR, gelb + `*` = verwaiste Abhängigkeit,
`d` = als Abhängigkeit installiert.

## Sicherheitsmodell

`pyaur` behandelt alle Daten aus dem AUR als **nicht vertrauenswürdig**, bis du sie freigibst.

### Prüfung (Review)

- **Kein PKGBUILD läuft ohne deine Freigabe.** Auch `--noconfirm` überspringt diesen Schritt
  nicht. Gibt es kein Terminal, bricht `pyaur` stattdessen mit einem Fehler ab.
- **Du prüfst genau das, was gebaut wird.** Der Prüftext entsteht direkt aus den
  Git-Objekten des Commits, den du freigibst, nicht aus dem Arbeitsverzeichnis. Nach der
  Freigabe wird das Arbeitsverzeichnis auf genau diesen Commit gesetzt
  (`git merge --ff-only`), und `pyaur` prüft, dass `HEAD` wirklich dieser Commit ist.
- **Die Freigabe wird gespeichert.** Der zuletzt freigegebene Commit steht in der Datei
  `.git/pyaur.json` des Repositorys. Brichst du eine Prüfung ab, **fragt der nächste Lauf
  erneut**. (In der alten Version wäre das Paket in diesem Fall ohne Prüfung gebaut worden.)
  Bei Updates siehst du einen `git diff` gegenüber dem zuletzt freigegebenen Commit, beim
  ersten Mal den vollständigen Inhalt aller Dateien.
- **Auch lokale Änderungen werden angezeigt.** Wurden Dateien im Cache verändert, kommt ihr
  Diff mit in die Prüfung. Einzige Ausnahme ist die `pkgver=`-Zeile, die `makepkg` bei
  `-git`-Paketen umschreibt; `pyaur` setzt sie automatisch zurück.
- Die Prüfung enthält außerdem die **Dateiliste des Repositorys** (ausführbare Dateien,
  symbolische Links und Submodule sind markiert), die **neuen Commits mit ihren Autoren**
  und die **heruntergeladenen Quellen** aus der `.SRCINFO`.

### Heuristischer Scanner

Am Anfang und am Ende der Prüfung erscheint eine Zusammenfassung verdächtiger Muster. Er sucht nach:

| Schwere | Muster |
|---|---|
| `[!!]` | `curl … \| sh`, `base64 -d`, `xxd -r`, `/dev/tcp/`, `nc`/`socat`, setuid-`chmod`, `sudo`/`doas`/`su` im Skript, `rm -rf /` oder `~`, `~/.ssh`, `~/.gnupg`, `.bashrc`, `/etc/sudoers`, `/etc/shadow`, `LD_PRELOAD`, Spuren von Krypto-Minern, rohe IP-Adressen in URLs, häufig missbrauchte Hosts (Pastebin, transfer.sh, Discord-Webhooks, Telegram-API…), unsichtbare und bidirektionale Unicode-Zeichen, symbolische Links und Submodule im Repository, unverschlüsselte Quellen (`http`/`ftp`/`git://`), `SKIP`-Prüfsummen bei Nicht-VCS-Quellen |
| `[ !]` | `eval`, Inline-`python -c`/`perl -e`, `systemctl enable`, `crontab`, lange Base64- oder Hex-Blöcke, Binärdateien im Repository, `.install`-Skripte (diese laufen als root) |

> Der Scanner ist **eine Heuristik, keine Garantie.** Er hilft dir, in einem langen PKGBUILD
> die verdächtigen Zeilen zu finden. Ein Paket ohne Funde ist nicht automatisch sicher.

### Warnungen anhand der AUR-Metadaten

Wenn `pyaur` den Installationsplan erstellt, kann jedes AUR-Paket diese Warnungen tragen:

- **NEUES Paket** (jünger als 14 Tage). Über das AUR verbreitete Malware sieht typischerweise
  so aus.
- **VERWAISTES** Paket ohne Maintainer, das jeder übernehmen kann.
- **wenige Stimmen**
- **als veraltet markiert**
- **MAINTAINER-WECHSEL**: `pyaur` merkt sich den Maintainer jedes Pakets und warnt deutlich,
  wenn er sich bei einem Update geändert hat.

Enthält der Plan ein Paket mit hohem Risiko, lautet die Standardantwort auf „Fortfahren?“ **nein**.

### Weitere Schutzmaßnahmen

| Bereich | Schutz |
|---|---|
| Befehlsausführung | Niemals `shell=True`. Alle Argumente werden als Liste übergeben, mit `--` vor den Paketnamen |
| Paketnamen | Strenger Regex (`^[a-zA-Z0-9][a-zA-Z0-9@._+-]{0,127}$`), bevor ein Name in eine URL oder einen Pfad gelangt |
| Pfade | Schutz vor Path Traversal und symbolischen Links (`resolve()` plus Prüfung des Elternverzeichnisses) |
| Terminal | Bei allem fremden Text werden ANSI/OSC-Escapes und Bidi-Zeichen entschärft. `less` läuft ohne `-R` und mit `LESSSECURE=1` (Shell-Escapes deaktiviert) |
| HTTP | Nur `https://aur.archlinux.org`, mit TLS ≥ 1.2 und Zertifikatsprüfung. Weiterleitungen nur innerhalb des AUR, 16 MiB Antwortlimit und ein Timeout |
| Git | Nur HTTPS (`GIT_ALLOW_PROTOCOL`, `protocol.allow`). Hooks und fsmonitor deaktiviert, keine Submodul-Rekursion, die Origin-URL eines vorhandenen Repositorys wird geprüft (gegen Cache-Poisoning), kein `git pull` |
| Cache | Rechte `0700` und Eigentümerprüfung; ein von anderen beschreibbarer Cache wird abgesichert. Eine Dateisperre (`flock`) verhindert parallele Läufe. `-Sc` folgt keinen symbolischen Links und verweigert das Löschen des Home-Verzeichnisses oder von `/` |
| Rechte | Startet nicht als root. `makepkg` läuft als normaler Benutzer; nur `pacman` erhält `sudo` |
| Installation | Abhängigkeiten werden mit `--asdeps` installiert, damit `-Qdt` sie später aufräumen kann |

## Ablauf einer Installation

1. **Planung.** `pyaur` holt die Paketdaten über die AUR-RPC und löst die Abhängigkeiten
   rekursiv mit `pacman -T` auf, das Versionsbeschränkungen und `provides` berücksichtigt.
   Danach gibt es die Build-Reihenfolge mit Risikohinweisen aus.
2. **Offizielle Pakete.** `pacman -S` installiert alles, was in den Repositories liegt.
3. **Download und Prüfung.** `pyaur` klont oder aktualisiert jedes AUR-Repository und **lässt
   dich alle prüfen, bevor irgendetwas gebaut wird.** So wird keine Kette halb gebaut, bevor
   sich beim dritten PKGBUILD herausstellt, dass er verdächtig ist.
4. **Bauen und installieren.** Für jedes Paket läuft der Reihe nach `makepkg -s`, danach `pacman -U`.

## Umgebungsvariablen

| Variable | Bedeutung |
|---|---|
| `PYAUR_CACHE` | Build-Cache-Verzeichnis (ersetzt `~/.cache/pyaur`) |
| `PYAUR_SUDO` | Befehl zur Rechteausweitung. Ein leerer Wert bedeutet: keine Rechteausweitung |
| `NO_COLOR` | Schaltet die Farben ab |

## Exit-Codes

| Code | Bedeutung |
|---|---|
| `0` | Erfolg. Bei `check`: Updates verfügbar |
| `1` | Fehler oder Abbruch |
| `2` | (`check`) Keine Updates, wie bei `checkupdates` |
| `130` | Strg+C |

## Einschränkungen

- `-Syu` aktualisiert `-git`- und andere VCS-Pakete nur, wenn ihre Versionsnummer im AUR
  gestiegen ist (es gibt keinen `--devel`-Modus).
- Kein Import von PGP-Schlüsseln. Fehlt ein Schlüssel aus `validpgpkeys`, schlägt `makepkg`
  fehl und du musst ihn selbst importieren (`gpg --recv-keys …`).
- Der heuristische Scanner ersetzt nicht, dass du den PKGBUILD selbst liest.

## Lizenz

`pyaur` ist freie Software: Du kannst sie unter den Bedingungen der **GNU General Public
License, Version 2** (GPL-2.0-only) weitergeben und verändern. Der vollständige Text steht
in der Datei [LICENSE](LICENSE).

Dieses Programm wird in der Hoffnung verbreitet, dass es nützlich ist, aber **OHNE JEDE
GEWÄHRLEISTUNG**, sogar ohne die implizite Gewährleistung der MARKTREIFE oder der EIGNUNG
FÜR EINEN BESTIMMTEN ZWECK.
