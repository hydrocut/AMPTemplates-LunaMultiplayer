# AMPTemplates-LunaMultiplayer — Luna Multiplayer (KSP) server for AMP

**AMP Generic Module** template for the server of **Luna Multiplayer** (LMP), the free and open-source
(MIT) multiplayer mod for **Kerbal Space Program 1.12** (<https://github.com/LunaMultiplayer/LunaMultiplayer>).
Written for TeamKit, a free French game host, on 10 Oct 2026.

CubeCoders ships no LMP template. One community template exists (`mf244/amp-ksp-luna`, April 2026):
it downloads a `0.29.0-Draft` asset that now returns 404, exposes no setting and does not pass AMP's
port to the server. This one was written from scratch.

> Résumé en français à la fin du fichier.

## Which version

| Release | Date | Server archive used | Runtime |
|---|---|---|---|
| **0.29.2** (latest stable, "35th BETA", KSP 1.12) | May 2026 | `LunaMultiplayer-Server-linux-x64-Release.zip` (12.7 MB, 33 MB unpacked) | **.NET 6.0.36 bundled** (self-contained) |
| 0.30.0-Draft (nightly, prerelease) | Sep 2026 | same name, folder `LMPServer/` inside | .NET 10 bundled |
| 0.29.0 and older | | framework-dependent only | needs a .NET 5 runtime |

The linux-x64 archive is **self-contained**: `Server` is an apphost next to `libcoreclr.so` and
`System.Private.CoreLib.dll` (`Server.runtimeconfig.json` → `includedFrameworks`), so **no .NET runtime
is installed**. The wiki's "install the .NET 6 runtime" applies to the framework-dependent
`LunaMultiplayer-Server-Release.zip`. The only native needs are ICU, OpenSSL and zlib, all already in
`cubecoders/ampbase:debian` (Debian 13: `libicu76`, `libssl3t64`) — checked with `ldd`, and the server
runs there.

The version is an AMP setting (`VersionLMP`, default `0.29.2`) used in the download URL
`releases/download/{{VersionLMP}}/LunaMultiplayer-Server-linux-x64-Release.zip`.

### Server and players must be on the same series

LMP compares **major.minor** only (`LmpVersioning.IsCompatibleWithPeer`, wiki *Versioning format*):
a 0.29.2 server accepts 0.29.x clients; a 0.30 client does not even list a 0.29 server
(`NetworkServerList` filters incompatible versions). When a newer LMP is out, the server prints
`There is a new version of LMP!` every 30 s — the start script shows it once an hour, and AMP flags an
update (`Console.UpdateAvailableRegex`). To move: change *Version de Luna Multiplayer*, **Update**, restart;
`Config/` and `Universe/` are kept.

### How players install the mod

- **CKAN** (recommended): the mod is indexed as **Luna Multiplayer Client** (identifier `LunaMultiplayer`,
  NetKAN `LunaMultiplayer.netkan`), built from the GitHub `LunaMultiplayer-Client-Release.zip`, with
  `Harmony2` pulled as a dependency. CKAN offers **0.29.2** as stable; the `-Draft` builds are indexed
  with `release_status: testing` and are only shown to users who allow testing releases — players
  should not. KSP must be **1.12.x**.
- **By hand**: download `LunaMultiplayer-Client-Release.zip` from **the same release as the server**,
  copy its `GameData` into the KSP folder (you get `GameData/LunaMultiplayer` and `GameData/000_Harmony`).
- In game: LMP window → **Server List** (French UI: *Liste de serveurs*), or add the server by
  IP and port. Player names: letters, digits, `-` and `_` only, 15 characters max (server rule).

## Files

| File | Role |
|---|---|
| `lunamultiplayer.kvp`, `lunamultiplayer*.json`, `manifest.json` | the AMP template |
| `scripts/AMP_reglages.txt` | settings model; AMP renders it to `reglages-amp.txt` (`ConfigType: template`) |
| `scripts/lancer-lmp.sh` | Update helper and start script (see below) |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

Both `scripts/` files are fetched from this repository (raw.githubusercontent.com, branch `main`) at
each Update, so **the repository must be public**.

## Update

1. fetch `lancer-lmp.sh` and `AMP_reglages.txt`;
2. `lancer-lmp.sh preparer` empties `telechargement/`;
3. FetchURL + unzip of the server archive into `telechargement/`;
4. `lancer-lmp.sh installer` copies the single folder found there (`LMPServer-linux-x64/` in 0.29,
   `LMPServer/` in the nightlies) into a **fixed** `serveur/` folder, makes `Server` executable (the
   zip stores no Unix permissions) and checks libraries with `ldd`.

LMP keeps `Config/`, `Universe/` and `logs/` **next to its executable** (`AppContext.BaseDirectory`),
so the fixed folder matters: with the archive's own folder name, a version change would start an
empty universe. Tested: reinstalling over an existing server keeps settings and universe.

## How the server is started

`/bin/bash lancer-lmp.sh <port>`, which:

1. copies the AMP settings from `reglages-amp.txt` into `serveur/Config/*.xml` (one key = one XML
   element of the same name), escaping `&`, `<`, `>`; values are checked (`true`/`false`, integers,
   enum names) and a wrong one stops the start with a French message. Missing XML files are created
   with only these elements; LMP fills in the rest and rewrites the file. Elements not managed by AMP
   are never touched, so hand edits (e.g. `MaxVesselParts`) survive;
2. forces `ConnectionSettings/Port` = AMP's port, `Upnp=false` (no router; saves a 5 s timeout),
   `WebsiteSettings/EnableWebsite=false` (JSON page on 8900/TCP, not opened by AMP) and
   `LogSettings/LogLevel=Debug` (the "player left" line is a Debug line);
3. refuses to start if the UDP port is already taken in the container;
4. starts `Server` under `setpriv --pdeathsig TERM` (dies with the script) and
   `env --default-signal=INT`, with the AMP console as its stdin;
5. on SIGTERM (AMP stop) sends **SIGINT**: LMP only saves the universe on Ctrl+C
   (`Console.CancelKeyPress`); on SIGTERM .NET exits without the final backup. Safety net: TERM then KILL
   after 45 s.

Details that cost a test each:

- **bash puts SIGINT on "ignore" for background commands**, and .NET then does not install its Ctrl+C
  handler (`SigIgn` bit set, Ctrl+C ignored). `env --default-signal=INT` restores it — checked in
  `/proc/<pid>/status`.
- **A trap does not interrupt a blocking `read` that started after the signal**: the stop was
  sometimes never done while LMP printed nothing. The output loop uses `read -t 1` and glues back lines
  split by the timeout; stop now takes 0.3–1 s.
- **Inside the trap, `IFS` is empty** (it runs during `IFS= read`), so `for _ in $(seq 1 90)` became a
  single iteration and the safety net killed LMP at once. A counter loop is used instead.
- **On a fatal start error LMP waits for a key** (`Console.ReadLine()` in `Main`'s `catch`), so the
  instance would look "running" with no server. The script watches for a `[Fatal]` line before
  `All systems up and running`; 3 s later it stops the server (tested with an unwritable `Universe`).
- **`/restartserver`** (console or the in-game Admin window) starts `…\Server.exe` — a Windows path —
  then hits the same `ReadLine`. The script says so in French and stops the server; restart from AMP.

## Settings exposed in AMP (French UI)

| AMP setting | LMP element | Default |
|---|---|---|
| Version de Luna Multiplayer | (Update URL) | `0.29.2` |
| Nom du serveur | `GeneralSettings/ServerName` (30 chars in the list) | `Serveur FR \| TeamKit.fr` |
| Description | `Description` (200) | French TeamKit text + Discord |
| Texte / adresse du lien | `WebsiteText` (15) / `Website` (60) | `Discord TeamKit` / `https://discord.gg/EuAjGMYPHY` |
| Message d'accueil | `ServerMotd` (255; `%Name%`, `%ServerName%`, `%PlayerCount%`, `\n`) | French TeamKit welcome |
| … aussi dans le chat | `PrintMotdInChat` | on |
| Liste publique des serveurs | `MasterServerSettings/RegisterWithMasterServer` | on |
| Mot de passe / mot de passe admin | `Password` / `AdminPassword` | empty |
| Joueurs maximum | `MaxPlayers` (also AMP's `$MaxUsers`) | 20 |
| Mode de jeu | `GameMode` Sandbox / Science / Career | Sandbox |
| Difficulté | `GameDifficulty` Easy / Normal / Moderate / Hard / Custom | Normal |
| Accélération du temps | `WarpSettings/WarpMode` Subspace / None | Subspace |
| Contrôle des mods | `ModControl` | on |
| Triche autorisée | `Cheats` | on (LMP default) |

**Game mode warning** (from `ScenarioSystem.GenerateDefaultScenarios`, tested): at each start LMP
deletes the scenario files of the other modes. Career → Science deletes `Funding`, `Reputation`,
`ContractSystem`…; → Sandbox also deletes `ResearchAndDevelopment`. Pick the mode before the first game.

### Mods

With *Contrôle des mods* on, LMP applies `serveur/Config/LMPModControl.xml`. The default file allows
stock parts only: a vessel with modded parts is sent back to the KSC. For a modded server: in KSP with
the mod set installed, LMP **Options → "Generate a server LMPModControl.xml"**, then upload the file
into `serveur/Config/` (AMP file manager) and restart. The file can also list mandatory/forbidden
plugins and required expansions (wiki *Mod file*). Players should install the same mods (CKAN can
export/import a mod list). The template never overwrites this file.

## Public server list (master servers)

The server registers every 5 s with the master servers listed in the LMP repository
(`MasterServersList.txt`, read at start; currently `ms.lmp.dasskelett.dev:8700` and
`lmp.nightshade.fun:8700`, the former official one is down since 2025). The list shows name,
description, mode, player count, password flag and the link. The test container saw itself as
`51.254.47.151:8800` through the STUN check of the master servers (no symmetric NAT, Docker keeps the
source port), so players can join from the list or with `IP:port`. **Registration was switched off in
every test** (no test server was published). Rainbow/colour highlighting needs an entry in LMP's
`DedicatedServersList.txt` (pull request to their repository).

## Console and player list

AMP console → server stdin: `/help`, `/listclients`, `/countclients`, `/kick <name> [reason]`,
`/ban`, `/dekessler`, `/nukeksc`, `/backup`, `/setfunds`, `/setscience`…; a line without `/` is
broadcast to players (`Broadcasting …`). Real lines (LMP 0.29.2, test client speaking the real protocol):

```
[17:58:14][LMP]: All systems up and running. Поехали!                         <- AppReadyRegex
[17:58:15][LMP]: Client Kevin_TK (b266…) handshake successful, LMP Version: 0.29.2, KSP Version: 1.12.5   <- UserJoinRegex
[17:58:15][Chat]: Kevin_TK: Salut à tous ! ça marche ?                        <- UserChatRegex
[17:58:29][Debug]: Kevin_TK sent Connection end message, reason: Au revoir    <- UserLeaveRegex
[17:58:37][Debug]: Marine-2 sent Connection end message, reason: Kicked from the server: essai TeamKit
```

`Performing backups...` / `Backups done` (every 30 s with players, at each departure) are hidden from
the AMP console (`HideFromConsoleRegex`); they stay in `serveur/logs/`.

## Resources (measured)

| | |
|---|---|
| RAM | 67 MB idle, 80 MB with 2 players (1 CPU); 98–104 MB idle to 8 players with 24 CPUs (server GC) — test clients had no vessels: plan **512 MB** |
| Start | ~1 s to the ready line (UPnP off) |
| Stop | 0.3–1 s, universe saved |
| Disk | 33 MB of server + universe (KB at start; grows with vessels, logs kept 14 days) |
| Network | one port, **8800/UDP**; vessel updates every 50 ms per player (`IntervalSettings`) |

## Before pushing

```
python verifier.py
```

Must print `Tout est bon.`: JSON, includes, port refs, complete `Console.*` / `Limits.*` block,
setting ↔ model ↔ start-script table, French defaults within LMP's length limits, a **real round trip**
(render the model like AMP → run the real start script with bash + perl → parse the XML: empty value,
spaces, accents, `& < > " '`, `\n`, `%Name%`; `True` → `true`; bad values refused; an existing LMP file
updated without losing comments or other elements), download URLs and order, LF endings, `bash -n`,
console regexes on real lines.

## Install in AMP

ADS → Configuration → Instance Deployment → **Configuration Repositories**: add
`hydrocut/AMPTemplates-LunaMultiplayer:main`, save, **Fetch latest**. Create Instance →
**Luna Multiplayer - KSP (TeamKit)** → **Update** (must end with `Serveur Luna Multiplayer installe dans
serveur/`) → **Start** (`Luna Server version: 0.29.2`, then `All systems up and running`).

## Credits

Luna Multiplayer is MIT-licensed software by the LMP team (gavazquez and contributors). This repository
only contains the template; the server is downloaded from their GitHub releases.

---

## Résumé en français

Template AMP pour le **serveur Luna Multiplayer** (mod multijoueur gratuit de Kerbal Space Program 1.12).
L'archive Linux officielle de LMP **contient déjà .NET 6** : rien à installer, tout tourne dans l'image
AMP Debian 13. Un seul port, **8800 en UDP**.

- **Version** : réglage *Version de Luna Multiplayer* (0.29.2 par défaut, la version stable). Les joueurs
  doivent avoir la **même série** (0.29.x). Ils installent le mod avec **CKAN** (« Luna Multiplayer
  Client », sans activer les versions « testing ») ou à la main depuis la même release GitHub, dans
  KSP **1.12**. Changer de version : modifier le réglage, Update, redémarrer (univers gardé).
- **Réglages en français dans AMP** : nom (« Serveur FR | TeamKit.fr »), description et message
  d'accueil TeamKit + Discord, lien Discord, liste publique des serveurs (oui par défaut), mot de passe,
  mot de passe admin, joueurs max (20), mode (bac à sable / science / carrière), difficulté,
  accélération du temps, contrôle des mods, triche. Accents, `&`, `<`, `>`, guillemets passent.
- **Attention au mode de jeu** : LMP efface les fichiers des autres modes au démarrage (passer de
  Carrière à Science supprime argent, réputation, contrats). Choisir avant la première partie.
- **Mods** : par défaut, pièces du jeu de base seulement. Pour un serveur moddé : générer
  `LMPModControl.xml` dans KSP (options de LMP) et le déposer dans `serveur/Config/`.
- **Arrêt propre** : le script transforme l'arrêt d'AMP en Ctrl+C, seul signal où LMP enregistre
  l'univers. Erreur fatale ou `/restartserver` (qui ne marche pas sous Linux) : le serveur est arrêté
  au lieu de rester bloqué.
- **Testé en vrai** le 10 oct. 2026 dans des conteneurs jetables avec un client d'essai qui parle le
  vrai protocole : connexion, mot de passe, accueil, chat, kick, serveur plein, arrêt. 67 à 104 Mo de
  RAM, prêt en 1 s. Pas testé : un vrai KSP, AMP lui-même, l'inscription sur la liste publique.
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
