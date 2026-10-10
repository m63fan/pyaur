# pyaur

🌐 [Magyar](README.md) · [English](README.en.md) · [Deutsch](README.de.md) · **Polski**

**Minimalistyczny, nastawiony na bezpieczeństwo pomocnik AUR napisany w Pythonie. Alternatywa dla `yay` i `paru`.**

`pyaur` to pojedynczy plik Pythona, który korzysta wyłącznie z biblioteki standardowej.
Instaluje, aktualizuje, wyszukuje i usuwa pakiety z
[Arch User Repository](https://aur.archlinux.org). Obsługuje znane przełączniki w stylu pacmana
(`-S`, `-Ss`, `-Syu`, `-R`…) i ma prosty interfejs TUI oparty na `curses`. Główne założenie jest
takie, że **żaden obcy kod nie zostanie uruchomiony, zanim go nie przejrzysz**.

> ⚠️ Pakiety AUR wgrywają użytkownicy i **nikt** ich nie weryfikuje. PKGBUILD to skrypt
> bash uruchamiany na Twoim komputerze. `pyaur` pomaga Ci go przejrzeć, ale nie zrobi tego
> za Ciebie.

> ℹ️ Interfejs i komunikaty programu są po węgiersku.

---

## Spis treści

- [Funkcje](#funkcje)
- [Wymagania](#wymagania)
- [Instalacja](#instalacja)
- [Użycie](#użycie)
- [Opcje](#opcje)
- [TUI](#tui)
- [Model bezpieczeństwa](#model-bezpieczeństwa)
- [Jak przebiega instalacja](#jak-przebiega-instalacja)
- [Zmienne środowiskowe](#zmienne-środowiskowe)
- [Kody wyjścia](#kody-wyjścia)
- [Ograniczenia](#ograniczenia)
- [Licencja](#licencja)

---

## Funkcje

- **Instalacja** z AUR z rekurencyjnym rozwiązywaniem zależności (również AUR → AUR),
  poprawną kolejnością budowania i obsługą pakietów dzielonych (split packages).
- **Rozpoznawanie oficjalnych repozytoriów**: jeśli żądany pakiet jest w oficjalnym
  repozytorium, instaluje go `pacman` zamiast budować go z AUR.
- **Aktualizacja systemu** (`-Syu`): najpierw `pacman -Syu`, potem pakiety AUR, co pozwala
  uniknąć częściowych aktualizacji. `-Sua` aktualizuje tylko pakiety AUR.
- **Wyszukiwanie** (`-Ss`) posortowane według popularności. Pakiety zainstalowane,
  nieaktualne i osierocone są oznaczone, a do wyboru jest kilka pól wyszukiwania
  (`--by maintainer`, `--by provides`…).
- **Informacje o pakiecie** (`-Si`) z datami, opiekunem i wskaźnikami ryzyka.
- **Lista aktualizacji** (`-Qu`): pokazuje dostępne aktualizacje bez instalowania czegokolwiek,
  więc nadaje się też do skryptów.
- Usuwanie **osieroconych zależności** (`-Qdt` / `-Yc`).
- **Pobieranie PKGBUILD** (`-G`) lub jego wyświetlanie (`-Gp`) bez budowania.
- **Czyszczenie pamięci podręcznej budowania** (`-Sc`).
- **Interaktywny TUI**: lista zainstalowanych pakietów AUR, w której można je zaznaczać,
  usuwać, aktualizować i filtrować.
- Brak zewnętrznych zależności: wystarczą `python`, `pacman`, `git` i `base-devel`.

## Wymagania

- Arch Linux lub dystrybucja oparta na Archu (np. EndeavourOS, Manjaro, CachyOS…)
- Python ≥ 3.8
- `pacman`, `git`, `base-devel` (`makepkg`, `vercmp`)
- `sudo`, `doas` lub `run0` do podnoszenia uprawnień
- opcjonalnie `less` do przewijania długiego tekstu do przeglądu

```bash
sudo pacman -S --needed python git base-devel less
```

## Instalacja

Sklonuj lub pobierz to repozytorium (na stronie GitHub: **Code → Download ZIP**), a następnie
uruchom w jego katalogu:

```bash
install -Dm755 pyaur.py ~/.local/bin/pyaur
```

Upewnij się, że `~/.local/bin` jest w Twoim `PATH`. Do instalacji systemowej użyj tego polecenia:

```bash
sudo install -Dm755 pyaur.py /usr/local/bin/pyaur
```

> **Nie uruchamiaj `pyaur` jako root**, bo program odmówi startu. Uruchom go jako zwykły
> użytkownik; w razie potrzeby sam wywoła `sudo` dla `pacmana`.

## Użycie

| Polecenie | Podpolecenie | Co robi |
|---|---|---|
| `pyaur` | `tui` | Interaktywna lista zainstalowanych pakietów AUR |
| `pyaur -S <pakiet>…` | `install` | Instalacja (z AUR lub z oficjalnego repozytorium) |
| `pyaur -Ss <fraza>` | `search` | Wyszukiwanie w AUR |
| `pyaur -Ssq <fraza>` | `search -q` | Wyszukiwanie, wypisuje tylko nazwy pakietów |
| `pyaur -Si <pakiet>` | `info` | Szczegóły pakietu AUR |
| `pyaur -Syu` | `upgrade` | `pacman -Syu`, a potem aktualizacja pakietów AUR |
| `pyaur -Sua` | `upgrade --aur-only` | Aktualizacja tylko pakietów AUR |
| `pyaur -Qu` | `check` | Lista pakietów AUR do aktualizacji, bez instalowania |
| `pyaur -R <pakiet>…` | `remove` | Usunięcie (`pacman -Rns`) |
| `pyaur -Qdt` / `-Yc` | `orphans` | Usunięcie osieroconych zależności |
| `pyaur -G <pakiet>…` | `getpkgbuild` | Pobranie repozytorium git z AUR do bieżącego katalogu |
| `pyaur -Gp <pakiet>` | `pkgbuild` | Wyświetlenie PKGBUILD z szybkim skanem |
| `pyaur -Sc` | `clean` | Usunięcie pamięci podręcznej budowania |

Przykłady:

```bash
pyaur -S google-chrome
pyaur -Ss --by maintainer jguer
pyaur -Syu
pyaur -Qu -q | wc -l                   # ile jest aktualizacji AUR
pyaur -S foo --noconfirm               # opcje działają też po poleceniu
pyaur -Gp yay | less                   # przeczytaj PKGBUILD przed instalacją
```

## Opcje

Poniższe opcje można podać przed poleceniem lub po nim.

| Opcja | Opis |
|---|---|
| `--noconfirm` | Pomija pytania typu „Kontynuować?”. **Nie pomija przeglądu PKGBUILD.** |
| `--noreview` | Pomija przegląd PKGBUILD. **Niezalecane.** Znaleziska skanera o wysokim ryzyku i tak zostaną wypisane. |
| `--rebuild` | Buduje ponownie, nawet jeśli pakiet jest aktualny (`makepkg -f`) |
| `--clean-build` | Usuwa katalog pakietu w pamięci podręcznej przed klonowaniem |
| `--clean` / `--no-clean` | Czyści `src/` i `pkg/` po budowaniu (`makepkg -c`, domyślnie włączone) |
| `--rmdeps` | Usuwa zależności budowania po zakończeniu (`makepkg --rmdeps`) |
| `--install-split-deps` | Przy pakietach dzielonych instaluje też pozostałe podpakiety z `--asdeps` |
| `--sudo CMD` | Polecenie do podnoszenia uprawnień (`sudo`, `doas`, `run0` lub puste) |
| `--cache DIR` | Położenie pamięci podręcznej budowania (domyślnie: `~/.cache/pyaur`) |
| `--limit N` | Maksymalna liczba wyników wyszukiwania (domyślnie: 25) |
| `--by FIELD` | (`search`) Pole wyszukiwania: `name`, `name-desc`, `maintainer`, `depends`, `makedepends`, `optdepends`, `checkdepends`, `provides`, `conflicts`, `replaces`, `keywords`, `groups`, `submitter` |
| `-q`, `--quiet` | (`search`, `check`) Wypisuje tylko nazwy pakietów |
| `--aur-only` | (`upgrade`) Pomija `pacman -Syu` |

## TUI

Uruchomiony bez argumentów `pyaur` pokazuje zainstalowane obce pakiety (z AUR) wraz z wersją
lokalną i wersją w AUR, stanem i rozmiarem.

| Klawisz | Działanie |
|---|---|
| `↑` `↓` / `j` `k` | poruszanie się |
| `PgUp` `PgDn` `Home` `End` | przewijanie |
| `Spacja` | zaznaczanie |
| `Shift+Del` / `Del` / `d` | usunięcie zaznaczonych (lub bieżącego) pakietów |
| `u` | aktualizacja wszystkich pakietów, które mają aktualizacje |
| `/` | filtrowanie po nazwie lub opisie (`Esc` czyści filtr) |
| `i` | `pacman -Qi` dla bieżącego pakietu |
| `r` | ponowne wczytanie |
| `q` | wyjście |

Kolory: zielony = jest aktualizacja, czerwony = brak w AUR, żółty + `*` = osierocona
zależność, `d` = zainstalowany jako zależność.

## Model bezpieczeństwa

`pyaur` traktuje wszystkie dane z AUR jako **niezaufane**, dopóki ich nie zatwierdzisz.

### Przegląd (review)

- **Żaden PKGBUILD nie zostanie uruchomiony bez Twojej zgody.** `--noconfirm` też nie pomija
  tego kroku. Jeśli nie ma terminala, `pyaur` zamiast tego kończy działanie z błędem.
- **Przeglądasz dokładnie to, co zostanie zbudowane.** Tekst do przeglądu powstaje
  bezpośrednio z obiektów git zatwierdzanego commita, a nie z drzewa roboczego. Po
  zatwierdzeniu drzewo robocze zostaje ustawione na ten commit (`git merge --ff-only`),
  a `pyaur` sprawdza, czy `HEAD` to rzeczywiście on.
- **Zatwierdzenie jest zapisywane.** Ostatni zatwierdzony commit trafia do pliku
  `.git/pyaur.json` w repozytorium. Jeśli przerwiesz przegląd, przy następnym uruchomieniu
  **program zapyta ponownie**. (W starej wersji pakiet zostałby wtedy zbudowany bez
  przeglądu.) Przy aktualizacjach widzisz `git diff` względem ostatnio zatwierdzonego
  commita, a za pierwszym razem pełną treść wszystkich plików.
- **Lokalne zmiany też są widoczne.** Jeśli coś zmieniło pliki w pamięci podręcznej, ich
  diff trafia do przeglądu. Jedynym wyjątkiem jest linia `pkgver=`, którą `makepkg`
  nadpisuje w pakietach `-git`; `pyaur` przywraca ją automatycznie.
- Przegląd zawiera też **listę plików repozytorium** (pliki wykonywalne, dowiązania
  symboliczne i submoduły są oznaczone), **nowe commity wraz z autorami** oraz **pobierane
  źródła** z pliku `.SRCINFO`.

### Skaner heurystyczny

Na początku i na końcu przeglądu pojawia się podsumowanie podejrzanych wzorców. Skaner szuka:

| Waga | Wzorzec |
|---|---|
| `[!!]` | `curl … \| sh`, `base64 -d`, `xxd -r`, `/dev/tcp/`, `nc`/`socat`, `chmod` z setuid, `sudo`/`doas`/`su` w skrypcie, `rm -rf /` lub `~`, `~/.ssh`, `~/.gnupg`, `.bashrc`, `/etc/sudoers`, `/etc/shadow`, `LD_PRELOAD`, śladów koparek kryptowalut, surowych adresów IP w URL-ach, często nadużywanych hostów (pastebin, transfer.sh, webhooki Discorda, API Telegrama…), niewidocznych i dwukierunkowych znaków Unicode, dowiązań symbolicznych i submodułów w repozytorium, nieszyfrowanych źródeł (`http`/`ftp`/`git://`), sum kontrolnych `SKIP` przy źródłach innych niż VCS |
| `[ !]` | `eval`, wbudowanego kodu `python -c`/`perl -e`, `systemctl enable`, `crontab`, długich bloków base64 lub hex, plików binarnych w repozytorium, skryptów `.install` (uruchamianych jako root) |

> Skaner to **heurystyka, a nie gwarancja.** Pomaga wyłowić podejrzane linie w długim
> PKGBUILD. Pakiet bez znalezisk nie musi być bezpieczny.

### Ostrzeżenia na podstawie metadanych AUR

Kiedy `pyaur` tworzy plan instalacji, każdy pakiet AUR może dostać takie ostrzeżenia:

- **NOWY pakiet** (młodszy niż 14 dni). Tak zwykle wygląda złośliwe oprogramowanie
  rozpowszechniane przez AUR.
- **OSIEROCONY** pakiet bez opiekuna, który każdy może przejąć.
- **mało głosów**
- **oznaczony jako nieaktualny**
- **ZMIANA OPIEKUNA**: `pyaur` zapamiętuje opiekuna każdego pakietu i wyraźnie ostrzega,
  jeśli zmienił się przy aktualizacji.

Jeśli w planie jest pakiet wysokiego ryzyka, domyślną odpowiedzią na pytanie
„Kontynuować?” staje się **nie**.

### Inne zabezpieczenia

| Obszar | Zabezpieczenie |
|---|---|
| Uruchamianie poleceń | Nigdy `shell=True`. Wszystkie argumenty są przekazywane jako lista, z `--` przed nazwami pakietów |
| Nazwy pakietów | Ścisłe wyrażenie regularne (`^[a-zA-Z0-9][a-zA-Z0-9@._+-]{0,127}$`), zanim nazwa trafi do URL-a lub ścieżki |
| Ścieżki | Ochrona przed path traversal i dowiązaniami symbolicznymi (`resolve()` plus sprawdzenie katalogu nadrzędnego) |
| Terminal | W całym obcym tekście sekwencje ANSI/OSC i znaki bidi są neutralizowane. `less` działa bez `-R` i z `LESSSECURE=1` (wyłączone wywołania powłoki) |
| HTTP | Tylko `https://aur.archlinux.org`, z TLS ≥ 1.2 i weryfikacją certyfikatu. Przekierowania tylko w obrębie AUR, limit odpowiedzi 16 MiB i limit czasu |
| Git | Tylko HTTPS (`GIT_ALLOW_PROTOCOL`, `protocol.allow`). Wyłączone hooki i fsmonitor, brak rekursji submodułów, weryfikacja adresu origin istniejącego repozytorium (przeciw zatruciu pamięci podręcznej), brak `git pull` |
| Pamięć podręczna | Uprawnienia `0700` i sprawdzanie właściciela; pamięć podręczna zapisywalna przez innych zostaje zabezpieczona. Blokada pliku (`flock`) zapobiega równoległym uruchomieniom. `-Sc` nie podąża za dowiązaniami symbolicznymi i odmawia usunięcia katalogu domowego lub `/` |
| Uprawnienia | Nie uruchamia się jako root. `makepkg` działa jako zwykły użytkownik; tylko `pacman` dostaje `sudo` |
| Instalacja | Zależności są instalowane z `--asdeps`, dzięki czemu `-Qdt` może je później usunąć |

## Jak przebiega instalacja

1. **Planowanie.** `pyaur` pobiera dane pakietów przez AUR RPC i rekurencyjnie rozwiązuje
   zależności za pomocą `pacman -T`, który uwzględnia ograniczenia wersji i `provides`.
   Następnie wypisuje kolejność budowania ze wskaźnikami ryzyka.
2. **Oficjalne pakiety.** `pacman -S` instaluje wszystko, co jest w repozytoriach.
3. **Pobieranie i przegląd.** `pyaur` klonuje lub aktualizuje każde repozytorium AUR i **daje
   Ci do przejrzenia wszystkie, zanim cokolwiek zostanie zbudowane.** Dzięki temu łańcuch
   nie zostanie zbudowany w połowie, zanim okaże się, że trzeci PKGBUILD jest podejrzany.
4. **Budowanie i instalacja.** Dla każdego pakietu po kolei uruchamia się `makepkg -s`,
   a potem `pacman -U`.

## Zmienne środowiskowe

| Zmienna | Znaczenie |
|---|---|
| `PYAUR_CACHE` | Katalog pamięci podręcznej budowania (zastępuje `~/.cache/pyaur`) |
| `PYAUR_SUDO` | Polecenie do podnoszenia uprawnień. Pusta wartość oznacza brak podnoszenia |
| `NO_COLOR` | Wyłącza kolory |

## Kody wyjścia

| Kod | Znaczenie |
|---|---|
| `0` | Sukces. Dla `check`: są dostępne aktualizacje |
| `1` | Błąd lub przerwanie |
| `2` | (`check`) Brak aktualizacji, tak samo jak w `checkupdates` |
| `130` | Ctrl+C |

## Ograniczenia

- `-Syu` aktualizuje pakiety `-git` i inne pakiety VCS tylko wtedy, gdy ich numer wersji
  w AUR wzrósł (brak trybu `--devel`).
- Brak importu kluczy PGP. Jeśli brakuje klucza z `validpgpkeys`, `makepkg` zakończy się
  błędem i musisz sam zaimportować klucz (`gpg --recv-keys …`).
- Skaner heurystyczny nie zastąpi samodzielnego przeczytania PKGBUILD.

## Licencja

`pyaur` jest wolnym oprogramowaniem: możesz je rozpowszechniać i modyfikować na warunkach
**GNU General Public License w wersji 2** (GPL-2.0-only). Pełny tekst znajduje się w pliku
[LICENSE](LICENSE).

Ten program jest rozpowszechniany w nadziei, że będzie użyteczny, ale **BEZ JAKIEJKOLWIEK
GWARANCJI**, nawet bez dorozumianej gwarancji PRZYDATNOŚCI HANDLOWEJ lub PRZYDATNOŚCI DO
OKREŚLONEGO CELU.
