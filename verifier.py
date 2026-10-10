# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de Wesnoth, Dominions 6, DDNet).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp ne référence que des fichiers présents, le port principal existe et part au lanceur,
   le bloc Console.* / Limits.* est complet, la console d'AMP écrit dans le serveur, arrêt SIGTERM ;
3. chaque réglage exposé dans AMP arrive dans le modèle scripts/AMP_reglages.txt (rendu par AMP en
   reglages-amp.txt), sauf la version (utilisée seulement par l'Update), et chaque {{...}} du modèle
   a son réglage ; chaque clé du modèle est connue du lanceur (table du perl) et inversement ;
4. valeurs par défaut : nom, description et accueil en français avec TeamKit et le Discord,
   longueurs sous les limites de LMP, enums et cases à cocher cohérents avec le lanceur ;
5. aller-retour réel : on rend le modèle comme AMP (remplacement brut), on lance le VRAI code du
   lanceur (bash + perl, variable TK_ESSAI_REGLAGES) et on relit les XML produits avec un lecteur
   XML : la valeur relue doit être identique (vide, espaces, accents, & < > " ', \\n, %Name%) ;
   valeurs refusées (case à cocher, nombre, enum) : le lanceur doit sortir en erreur ;
   fichier XML déjà écrit par LMP (commentaires, élément vide <X />) : mis à jour sans rien perdre ;
6. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest, et
   l'archive de LMP suit le réglage de version ;
7. le lanceur : fins de ligne LF, aucun {{, garde-fous présents (SIGINT, entrée de la console,
   fifo hors de l'instance, pdeathsig), et `bash -n` s'il y a un bash sous la main ;
8. les regex de console reconnaissent les vraies lignes de LMP 0.29.2 (relevées le 10 oct. 2026
   dans un conteneur jetable cubecoders/ampbase:debian, avec un client d'essai) et pas les autres.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'lunamultiplayer'
MODELE = 'scripts/AMP_reglages.txt'
LANCEUR = 'scripts/lancer-lmp.sh'
REGLAGES_UPDATE = {'VersionLMP'}          # utilisés par l'Update, pas écrits dans les XML
soucis = []


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        print('ok   %-30s JSON valide' % nom)
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for l in kvp.splitlines():
    if l != l.rstrip():
        soucis.append('espace en fin de ligne dans le .kvp : %s' % l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref'] for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond à aucun port')
if [p['Protocol'] for p in ports] != ['UDP']:
    soucis.append('LMP n’utilise qu’un port, en UDP')
cmd = cles.get('App.CommandLineArgs', '')
for r in re.findall(r'\{\{\$(\w+)\}\}', cmd):
    if r not in refs and r != 'FullBaseDir':
        soucis.append('{{$%s}} : aucun port ne porte ce Ref' % r)
if '{{$%s}}' % cles.get('App.PrimaryApplicationPortRef') not in cmd:
    soucis.append('le port principal n’est pas passé au lanceur')
print('ok   ports                          %s' % ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex', 'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex', 'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex', 'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex', 'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart', 'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    print('ok   kvp complet                    les %d clés Console/Limits sont là' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') == 'RegexMatch' and not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch sans AppReadyRegex : l’instance ne serait jamais déclarée prête')
if cles.get('App.HasWriteableConsole') != 'True' or cles.get('App.AdminMethod') != 'STDIO':
    soucis.append('la console d’AMP doit écrire dans le serveur (HasWriteableConsole=True, AdminMethod=STDIO)')
if cles.get('App.ExitMethod') != 'SIGTERM':
    soucis.append('App.ExitMethod doit être SIGTERM : le lanceur le traduit en SIGINT (sauvegarde de l’univers)')
if int(cles.get('App.ExitTimeout', '0')) < 50:
    soucis.append('App.ExitTimeout doit laisser au lanceur ses 45 s de filet')
if cles.get('Meta.URL') != data['manifest.json']['url']:
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')

# ── 3. réglages ↔ modèle ↔ lanceur ───────────────────────────────────────────
modele = lire(MODELE)
lanceur = lire(LANCEUR)
dans_modele = re.findall(r'\{\{([A-Za-z0-9_]+)\}\}', modele)
lignes_modele = {}
for l in modele.splitlines():
    if l.startswith('#') or not l.strip():
        continue
    m = re.match(r'^([A-Za-z]+)=\{\{([A-Za-z0-9_]+)\}\}$', l)
    if not m:
        soucis.append('ligne du modèle inattendue (attendu Cle={{Cle}}) : %s' % l)
        continue
    if m.group(1) != m.group(2):
        soucis.append('ligne du modèle : la clé et le réglage diffèrent : %s' % l)
    lignes_modele[m.group(1)] = l
params = {}
for c in config:
    p = c.get('ParamFieldName')
    if p in params:
        soucis.append('réglage en double : %s' % p)
    params[p] = c
    if c['FieldName'] != p and not (c['FieldName'] == '$MaxUsers' and p == 'MaxPlayers'):
        soucis.append('%s : FieldName et ParamFieldName différents (%s)' % (p, c['FieldName']))
    if c.get('IncludeInCommandLine') is not False:
        soucis.append('%s : IncludeInCommandLine doit être false (tout passe par reglages-amp.txt)' % p)
    if p in REGLAGES_UPDATE:
        if p in dans_modele:
            soucis.append('%s est un réglage d’Update, il n’a rien à faire dans le modèle' % p)
        continue
    if p not in dans_modele:
        soucis.append('réglage %s exposé dans AMP mais absent de %s' % (p, MODELE))
    if dans_modele.count(p) > 1:
        soucis.append('{{%s}} écrit deux fois dans le modèle' % p)
    if c['InputType'] == 'number' and not str(c.get('DefaultValue', '')).isdigit():
        soucis.append('%s : valeur par défaut non numérique' % p)
orphelins = set(dans_modele) - set(params)
if orphelins:
    soucis.append('{{...}} sans réglage dans AMP : %s' % ', '.join(sorted(orphelins)))
else:
    print('ok   correspondance                 %d réglages, %d dans %s, %d pour l’Update' % (len(params), len(dans_modele), MODELE, len(REGLAGES_UPDATE)))
# table du perl du lanceur
table = dict(re.findall(r'^\s+([A-Za-z]+)\s+=> \["\w+", "([^"]+)"', lanceur, re.M))
if set(table) != set(lignes_modele):
    soucis.append('clés du lanceur (%s) et du modèle (%s) différentes' % (sorted(table), sorted(lignes_modele)))
for p, c in params.items():
    if p in REGLAGES_UPDATE or p not in table:
        continue
    genre = table[p]
    t = c['InputType']
    if t == 'checkbox':
        if genre != 'bool' or c.get('EnumValues') != {'False': 'false', 'True': 'true'} or c['DefaultValue'] not in ('true', 'false'):
            soucis.append('%s : case à cocher mal câblée (genre %s, %s)' % (p, genre, c.get('EnumValues')))
    elif t == 'enum':
        if set(c['EnumValues']) != set(genre.split('|')) or c['DefaultValue'] not in c['EnumValues']:
            soucis.append('%s : valeurs de la liste (%s) différentes du lanceur (%s)' % (p, sorted(c['EnumValues']), genre))
    elif t == 'number':
        if genre != 'entier' or not (1 <= int(c['MinValue']) <= int(c['DefaultValue']) <= int(c['MaxValue']) <= 1000):
            soucis.append('%s : nombre mal borné' % p)
    elif t in ('text', 'password'):
        if genre != 'texte':
            soucis.append('%s : texte côté AMP, %s côté lanceur' % (p, genre))
meta = data[NOM + 'metaconfig.json']
racine = cles['App.RootDir'].strip('./').strip('/')
if len(meta) != 1 or meta[0].get('ConfigType') != 'template' or meta[0].get('ConfigFileTemplate') != racine + '/AMP_reglages.txt':
    soucis.append('metaconfig : un seul fichier, ConfigType template, ConfigFileTemplate %s/AMP_reglages.txt' % racine)
if meta and meta[0].get('ConfigFile') != 'reglages-amp.txt' or 'REGLAGES="$ICI/reglages-amp.txt"' not in lanceur:
    soucis.append('le fichier rendu par AMP (ConfigFile) n’est pas celui que lit le lanceur')
if cles.get('App.MaxUsers') != params['MaxPlayers']['DefaultValue']:
    soucis.append('App.MaxUsers doit valoir la valeur par défaut de MaxPlayers')

# ── 4. valeurs par défaut ────────────────────────────────────────────────────
LIMITES = {'ServerName': 30, 'Description': 200, 'WebsiteText': 15, 'Website': 60, 'ServerMotd': 255, 'Password': 30, 'AdminPassword': 30}
for p, n in LIMITES.items():
    d = params[p]['DefaultValue']
    if len(d) > n:
        soucis.append('%s par défaut : %d caractères, LMP en garde %d' % (p, len(d), n))
    if re.search(r'\b%s\s+=> \["\w+", "texte", %d\]' % (p, n), lanceur) is None:
        soucis.append('%s : limite %d absente de la table du lanceur' % (p, n))
for p in ('Description', 'ServerMotd'):
    d = params[p]['DefaultValue']
    if 'TeamKit.fr' not in d or 'discord.gg/EuAjGMYPHY' not in d:
        soucis.append('%s par défaut doit citer TeamKit.fr et le Discord' % p)
if 'TeamKit' not in params['ServerName']['DefaultValue']:
    soucis.append('le nom par défaut doit citer TeamKit')
if not params['Website']['DefaultValue'].startswith('https://'):
    soucis.append('le lien doit commencer par https:// (le jeu l’ouvre avec Application.OpenURL)')
if not re.fullmatch(r'\d+\.\d+\.\d+', params['VersionLMP']['DefaultValue']):
    soucis.append('version par défaut : un numéro de version stable, pas %r' % params['VersionLMP']['DefaultValue'])
print('ok   valeurs par défaut             françaises, TeamKit + Discord, sous les limites de LMP')


# ── 5. aller-retour réel : modèle rendu par AMP → lanceur (bash + perl) → XML ─
def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


bash = shutil.which('bash')
perl_ok = False
if bash:
    r = subprocess.run([bash, '-c', 'command -v perl'], capture_output=True, text=True)
    perl_ok = r.returncode == 0


def lancer_reglages(valeurs, xml_existants=None):
    """Rend le modèle, lance le vrai lanceur en mode essai, renvoie (code, sortie, {fichier: arbre})."""
    d = tempfile.mkdtemp(prefix='tk-lmp-')
    try:
        shutil.copy(os.path.join(ICI, LANCEUR), os.path.join(d, 'lancer-lmp.sh'))
        os.makedirs(os.path.join(d, 'serveur', 'Config'))
        open(os.path.join(d, 'serveur', 'Server'), 'w').close()
        with io.open(os.path.join(d, 'reglages-amp.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(rendre(valeurs))
        for nom, contenu in (xml_existants or {}).items():
            with io.open(os.path.join(d, 'serveur', 'Config', nom), 'w', encoding='utf-8', newline='\n') as f:
                f.write(contenu)
        env = dict(os.environ, TK_ESSAI_REGLAGES='1')
        r = subprocess.run([bash, 'lancer-lmp.sh', '8811'], cwd=d, capture_output=True, env=env)
        arbres = {}
        for nom in os.listdir(os.path.join(d, 'serveur', 'Config')):
            with open(os.path.join(d, 'serveur', 'Config', nom), 'rb') as f:
                brut = f.read()
            # LMP écrit encoding="utf-16" dans un fichier UTF-8 et le relit par un TextReader, qui
            # ignore la déclaration ; expat la refuserait : on la retire avant de lire.
            try:
                arbres[nom] = (ET.fromstring(re.sub(rb'^(?:\xef\xbb\xbf)?<\?xml[^>]*\?>', b'', brut)), brut)
            except ET.ParseError as e:
                soucis.append('%s illisible après le lanceur (%s) : LMP reprendrait ses valeurs par défaut' % (nom, e))
                arbres[nom] = (ET.Element('illisible'), brut)
        return r.returncode, r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace'), arbres
    finally:
        shutil.rmtree(d, ignore_errors=True)


defauts = {p: str(c.get('DefaultValue', '')) for p, c in params.items() if p not in REGLAGES_UPDATE}
FICHIER = {p: f + '.xml' for p, f in re.findall(r'^\s+([A-Za-z]+)\s+=> \["(\w+)"', lanceur, re.M)}
if bash and perl_ok:
    n = 0
    code, sortie, arbres = lancer_reglages(defauts)
    if code != 0:
        soucis.append('lanceur en erreur avec les valeurs par défaut : %s' % sortie.strip())
    else:
        for p in defauts:
            racine_xml = arbres[FICHIER[p]][0]
            lu = racine_xml.findtext(p)
            n += 1
            if (lu or '') != defauts[p]:
                soucis.append('défaut %s : écrit %r, relu %r' % (p, defauts[p], lu))
        imposes = {('ConnectionSettings.xml', 'Port'): '8811', ('ConnectionSettings.xml', 'Upnp'): 'false',
                   ('WebsiteSettings.xml', 'EnableWebsite'): 'false', ('LogSettings.xml', 'LogLevel'): 'Debug'}
        for (f, e), v in imposes.items():
            n += 1
            if f not in arbres or arbres[f][0].findtext(e) != v:
                soucis.append('valeur imposée %s/%s : attendu %r' % (f, e, v))
    ESSAIS_TEXTE = ['', '  espaces autour  ', 'Serveur hébergé — TeamKit.fr · Discord',
                    'a & b < c > d "e" \'f\' &amp; <x/>', 'ligne 1\\nligne 2 %Name% %PlayerCount%', '#pas un commentaire', '=égal=']
    textes = [p for p, c in params.items() if c['InputType'] in ('text', 'password') and p not in REGLAGES_UPDATE]
    for v in ESSAIS_TEXTE:
        vals = dict(defauts)
        for p in textes:
            vals[p] = v
        code, sortie, arbres = lancer_reglages(vals)
        if code != 0:
            soucis.append('texte %r refusé par le lanceur : %s' % (v, sortie.strip()))
            continue
        for p in textes:
            n += 1
            lu = arbres[FICHIER[p]][0].findtext(p) or ''
            if lu != v:
                soucis.append('aller-retour %s : écrit %r, relu %r' % (p, v, lu))
    # cases à cocher et listes : AMP peut écrire True/False, le XML de .NET veut true/false
    vals = dict(defauts)
    for p, c in params.items():
        if c['InputType'] == 'checkbox':
            vals[p] = 'True'
    code, sortie, arbres = lancer_reglages(vals)
    for p, c in params.items():
        if c['InputType'] == 'checkbox':
            n += 1
            if code != 0 or arbres[FICHIER[p]][0].findtext(p) != 'true':
                soucis.append('%s : True doit devenir true (XmlSerializer refuse True)' % p)
    for p, mauvais in [('MaxPlayers', 'vingt'), ('MaxPlayers', '0'), ('MaxPlayers', ''), ('Cheats', 'oui'), ('GameMode', 'Carriere'), ('WarpMode', '')]:
        vals = dict(defauts)
        vals[p] = mauvais
        code, sortie, arbres = lancer_reglages(vals)
        n += 1
        if code == 0 or 'ERREUR' not in sortie:
            soucis.append('%s=%r aurait dû être refusé' % (p, mauvais))
    # fichier déjà écrit par LMP : commentaires, élément vide, autres éléments gardés
    existant = ('<?xml version="1.0" encoding="utf-16"?>\n<GeneralSettingsDefinition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
                '  <!--Name of the server. Max 30 char-->\n  <ServerName>Luna Server</ServerName>\n'
                '  <!--Password for the server.-->\n  <Password />\n'
                '  <ServerMotd>Hi %Name%!\nWelcome to %ServerName%.\nOnline players: %PlayerCount%</ServerMotd>\n'
                '  <MaxVesselParts>350</MaxVesselParts>\n</GeneralSettingsDefinition>\n')
    vals = dict(defauts)
    vals['Password'] = 'nouveau'
    code, sortie, arbres = lancer_reglages(vals, {'GeneralSettings.xml': existant})
    n += 1
    if code != 0:
        soucis.append('mise à jour d’un fichier de LMP : %s' % sortie.strip())
    else:
        racine_xml, brut = arbres['GeneralSettings.xml']
        if racine_xml.findtext('Password') != 'nouveau' or racine_xml.findtext('MaxVesselParts') != '350' \
                or racine_xml.findtext('ServerName') != defauts['ServerName'] or racine_xml.findtext('ServerMotd') != defauts['ServerMotd'] \
                or b'<!--Name of the server. Max 30 char-->' not in brut or len(racine_xml.findall('ServerName')) != 1:
            soucis.append('mise à jour d’un fichier de LMP : valeurs ou commentaires perdus')
    print('ok   aller-retour (bash + perl)     %d valeurs relues dans les XML' % n)
else:
    print('--   aller-retour                   pas de bash + perl ici, non vérifié')

# ── 6. fichiers téléchargés à l'Update ───────────────────────────────────────
depot = data['manifest.json']['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
des_scripts = [e for e in fetch if 'raw.githubusercontent.com' in e['UpdateSourceData']]
for e in des_scripts:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
    else:
        print('ok   téléchargé à l’Update          scripts/%s' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in des_scripts} != {'AMP_reglages.txt', 'lancer-lmp.sh'}:
    soucis.append('l’Update doit déposer AMP_reglages.txt et lancer-lmp.sh')
archive = [e for e in fetch if 'LunaMultiplayer/LunaMultiplayer/releases' in e['UpdateSourceData']]
if len(archive) != 1 or archive[0]['UpdateSourceData'] != 'https://github.com/LunaMultiplayer/LunaMultiplayer/releases/download/{{VersionLMP}}/LunaMultiplayer-Server-linux-x64-Release.zip' \
        or not archive[0].get('UnzipUpdateSource') or not archive[0]['UpdateSourceTarget'].endswith('telechargement'):
    soucis.append('l’archive du serveur doit suivre {{VersionLMP}} et être décompressée dans telechargement/')
ordre = [e['UpdateSource'] + ':' + (e.get('UpdateSourceArgs') or '') for e in updates]
i_prep = next((i for i, o in enumerate(ordre) if o.endswith(' preparer')), -1)
i_inst = next((i for i, o in enumerate(ordre) if o.endswith(' installer')), -1)
i_zip = updates.index(archive[0]) if archive else -1
i_lanceur = next((i for i, e in enumerate(updates) if e.get('UpdateSourceArgs') == 'lancer-lmp.sh'), 99)
if not (i_lanceur < i_prep < i_zip < i_inst):
    soucis.append('ordre de l’Update : lanceur, preparer, archive, installer')
if any('{{' in e.get('UpdateStageName', '') for e in updates):
    soucis.append('pas de {{...}} dans les noms d’étapes (pas sûr qu’AMP les remplace)')

# ── 7. lanceur ───────────────────────────────────────────────────────────────
for nom in (LANCEUR, MODELE):
    brut = lire(nom, binaire=True)
    if b'\r' in brut:
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
if '{{' in lanceur:
    soucis.append('le lanceur contient {{ : AMP pourrait le remplacer')
for besoin, pourquoi in [
    ('env --default-signal=INT', 'sinon SIGINT reste ignoré et LMP quitte sans enregistrer'),
    ('kill -INT "$PID"', 'arrêt = Ctrl+C, seul signal où LMP enregistre l’univers'),
    ('<&3', 'la console d’AMP doit arriver sur l’entrée du serveur'),
    ('--pdeathsig TERM', 'le serveur ne doit pas survivre au lanceur'),
    ('TMPD="${XDG_RUNTIME_DIR:-/tmp}"', 'fifo hors du dossier de l’instance (sauvegardes AMP)'),
    ('"$NOUVEAU"/. "$SRV"/', 'l’installation copie dans serveur/ sans toucher Config/ ni Universe/'),
    ('Default settings will be used', 'une erreur de lecture d’un XML n’est pas un échec du démarrage'),
    ('s/&/&amp;/g', 'échappement XML'),
    ('All systems up and running', 'ligne prêt de LMP'),
]:
    if besoin not in lanceur:
        soucis.append('lanceur : %s (%s)' % (besoin, pourquoi))
if bash:
    r = subprocess.run([bash, '-n', os.path.join(ICI, LANCEUR)], capture_output=True, text=True)
    if r.returncode:
        soucis.append('bash -n %s : %s' % (LANCEUR, r.stderr.strip()))
    else:
        print('ok   bash -n                        %s' % LANCEUR)
else:
    print('--   bash -n                        pas de bash ici, syntaxe non vérifiée')

# ── 8. regex de console sur de vraies lignes (LMP 0.29.2, 10/10/2026) ─────────
ESSAIS = [
    ('Console.AppReadyRegex', '[17:58:14][LMP]: All systems up and running. Поехали!', {}),
    ('Console.UserJoinRegex', '[17:58:15][LMP]: Client Kevin_TK (b26635a2-0c4f-4339-91d4-ce2dbe13ef8f) handshake successful, LMP Version: 0.29.2, KSP Version: 1.12.5', {'username': 'Kevin_TK'}),
    ('Console.UserJoinRegex', '[17:58:30][LMP]: Client Marine-2 (e08b6073-0a8b-4563-b1b1-eb7d821196ac) handshake successful, LMP Version: 0.29.2, KSP Version: 1.12.5', {'username': 'Marine-2'}),
    ('Console.UserLeaveRegex', '[17:58:29][Debug]: Kevin_TK sent Connection end message, reason: Au revoir', {'username': 'Kevin_TK'}),
    ('Console.UserLeaveRegex', '[17:58:37][Debug]: Marine-2 sent Connection end message, reason: Kicked from the server: essai TeamKit', {'username': 'Marine-2'}),
    ('Console.UserChatRegex', '[17:58:15][Chat]: Kevin_TK: Salut à tous ! ça marche ?', {'username': 'Kevin_TK', 'message': 'Salut à tous ! ça marche ?'}),
    ('Console.UpdateAvailableRegex', '[18:30:00][Warning]: There is a new version of LMP! Please download it! Current: 0.29.2 Latest: 0.30.0', {}),
    ('Console.HideFromConsoleRegex', '[17:58:44][Debug]: Performing backups...', {}),
    ('Console.HideFromConsoleRegex', '[17:58:44][Debug]: Backups done', {}),
]
for cle, ligne, attendu in ESSAIS:
    m = py(cles.get(cle) or '^$').search(ligne)
    if not m or any(m.group(k) != v for k, v in attendu.items()):
        soucis.append('%s ne reconnaît pas : %r' % (cle, ligne))
PIEGES = [
    ('Console.UserJoinRegex', '[17:58:15][LMP]: New client Connection from ::ffff:127.0.0.1:50942'),
    ('Console.UserJoinRegex', '[17:58:15][LMP]: Client Intrus (0b1c) failed to handshake: Server full. Disconnecting'),
    ('Console.UserLeaveRegex', '[17:58:30][Debug]:  sent Connection end message, reason: Invalid password'),
    ('Console.UserLeaveRegex', '[17:58:15][Debug]: Online Players: 0, connected: 1'),
    ('Console.UserChatRegex', '[17:58:39][LMP]: Broadcasting Bonjour depuis la console AMP, ça va ?'),
    ('Console.AppReadyRegex', '[17:58:14][LMP]: Starting \'Serveur FR | TeamKit.fr\' on Address :: Port 8800... '),
    ('Console.HideFromConsoleRegex', '[17:58:02][LMP]: Exiting... Please wait until all threads are finished'),
    ('Console.HideFromConsoleRegex', '[17:58:15][Chat]: Kevin_TK: Performing backups...'),
]
for cle, ligne in PIEGES:
    if py(cles[cle] or '^$').search(ligne):
        soucis.append('%s attrape une ligne qui n’est pas pour lui : %r' % (cle, ligne))
print('ok   console                        %d lignes réelles, %d pièges' % (len(ESSAIS), len(PIEGES)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
