#!/bin/bash
# lancer-lmp.sh - pose par le template AMP TeamKit (recree a chaque Update).
#
#   lancer-lmp.sh preparer      Update, avant le telechargement : vide telechargement/
#   lancer-lmp.sh installer     Update, apres le telechargement : copie le serveur dans serveur/
#   lancer-lmp.sh <port>        demarrage (ligne de commande d'AMP)
#
# Au demarrage :
# 1. recopie les reglages d'AMP (reglages-amp.txt) dans serveur/Config/*.xml, en
#    echappant & < > ; impose le port d'AMP, coupe UPnP et la page web d'infos ;
# 2. lance le serveur LMP (.NET autonome, rien a installer) ;
# 3. la console d'AMP arrive directement sur l'entree du serveur (commandes /help, /kick...) ;
# 4. a l'arret demande par AMP (SIGTERM), envoie SIGINT (Ctrl+C) : c'est le seul signal
#    sur lequel LMP enregistre l'univers avant de quitter ;
# 5. si LMP plante au demarrage, il attend une touche au lieu de quitter (Console.ReadLine) :
#    on le detecte et on l'arrete pour qu'AMP voie l'echec.
cd "$(dirname "$0")" || exit 1
ICI="$PWD"
SRV="$ICI/serveur"
BIN="$SRV/Server"
CFG="$SRV/Config"
REGLAGES="$ICI/reglages-amp.txt"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

# ── Update ───────────────────────────────────────────────────────────────────
if [ "$1" = "preparer" ]; then
  rm -rf "$ICI/telechargement"
  mkdir -p "$ICI/telechargement" "$SRV"
  exit 0
fi

if [ "$1" = "installer" ]; then
  # L'archive de LMP contient un seul dossier (LMPServer-linux-x64/ en 0.29, LMPServer/ dans
  # les versions de developpement). On copie son contenu dans serveur/, toujours le meme
  # dossier : Config/, Universe/ et logs/ (crees par LMP a cote de son executable) restent.
  mapfile -t TROUVES < <(find "$ICI/telechargement" -mindepth 2 -maxdepth 2 -type f -name Server.dll -printf '%h\n')
  if [ "${#TROUVES[@]}" -ne 1 ]; then
    echo "ERREUR : archive inattendue (${#TROUVES[@]} dossier(s) avec Server.dll dans telechargement/)."
    echo "Verifie le reglage Version de Luna Multiplayer : il faut une version publiee avec l'archive LunaMultiplayer-Server-linux-x64-Release.zip (0.29.1 ou plus recente)."
    exit 1
  fi
  NOUVEAU="${TROUVES[0]}"
  if [ ! -f "$NOUVEAU/Server" ] || [ ! -f "$NOUVEAU/libcoreclr.so" ]; then
    echo "ERREUR : ce n'est pas la version Linux autonome du serveur (Server ou libcoreclr.so absent)."
    exit 1
  fi
  # Les fichiers de l'archive n'ont aucun droit enregistre : on rend tout lisible (et les
  # dossiers traversables) avant la copie.
  chmod -R u+rwX "$NOUVEAU"
  mkdir -p "$SRV"
  cp -a "$NOUVEAU"/. "$SRV"/ || { echo "ERREUR : copie vers serveur/ impossible."; exit 1; }
  rm -rf "$ICI/telechargement"
  chmod +x "$BIN"
  [ -f "$SRV/createdump" ] && chmod +x "$SRV/createdump"
  MANQUE=$(ldd "$BIN" "$SRV/libcoreclr.so" "$SRV/libSystem.Native.so" 2>/dev/null | grep "not found" | sort -u)
  if [ -n "$MANQUE" ]; then
    echo "ERREUR : bibliotheques manquantes :"
    echo "$MANQUE"
    exit 1
  fi
  NET=$(grep -o '"version": *"[0-9.]*"' "$SRV/Server.runtimeconfig.json" | head -n 1 | grep -o '[0-9][0-9.]*')
  echo "Serveur Luna Multiplayer installe dans serveur/ (.NET ${NET:-?} inclus dans l'archive, rien a installer)."
  echo "Le numero de version exact s'affiche au demarrage : Luna Server version ..."
  exit 0
fi

# ── Demarrage ────────────────────────────────────────────────────────────────
PORT="${1:-8800}"
if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "ERREUR : port invalide : '$PORT'."
  exit 1
fi
if [ ! -f "$BIN" ]; then
  echo "ERREUR : serveur absent ($BIN). Lance Update."
  exit 1
fi
if [ ! -f "$REGLAGES" ]; then
  echo "ERREUR : $REGLAGES absent. AMP l'ecrit au demarrage a partir de AMP_reglages.txt : lance Update."
  exit 1
fi
[ -x "$BIN" ] || chmod +x "$BIN"
mkdir -p "$CFG"

# Recopie des reglages : une cle de reglages-amp.txt = un element XML du meme nom.
# Si le fichier XML n'existe pas encore, on en ecrit un qui ne contient que nos elements :
# LMP complete les autres avec ses valeurs par defaut et reecrit le fichier en entier.
# Les autres elements (modifies a la main dans serveur/Config/) ne sont jamais touches.
PERL_REGLAGES='
use strict;
use warnings;
my ($fichier, $dossier, $port) = @ARGV;
my %TABLE = (
  ServerName               => ["GeneralSettings", "texte", 30],
  Description              => ["GeneralSettings", "texte", 200],
  WebsiteText              => ["GeneralSettings", "texte", 15],
  Website                  => ["GeneralSettings", "texte", 60],
  ServerMotd               => ["GeneralSettings", "texte", 255],
  PrintMotdInChat          => ["GeneralSettings", "bool"],
  Password                 => ["GeneralSettings", "texte", 30],
  AdminPassword            => ["GeneralSettings", "texte", 30],
  MaxPlayers               => ["GeneralSettings", "entier"],
  GameMode                 => ["GeneralSettings", "Sandbox|Science|Career"],
  GameDifficulty           => ["GeneralSettings", "Easy|Normal|Moderate|Hard|Custom"],
  WarpMode                 => ["WarpSettings", "Subspace|None"],
  Cheats                   => ["GeneralSettings", "bool"],
  ModControl               => ["GeneralSettings", "bool"],
  RegisterWithMasterServer => ["MasterServerSettings", "bool"],
);
my (%valeurs, @erreurs);
open(my $f, "<:raw", $fichier) or die "ERREUR : lecture de $fichier impossible\n";
while (my $l = <$f>) {
  $l =~ s/\r?\n\z//;
  next if $l =~ /^#/ || $l !~ /\S/;
  my ($cle, $v) = $l =~ /^([A-Za-z]+)=(.*)\z/s or do { push @erreurs, "ligne illisible : $l"; next };
  my $t = $TABLE{$cle} or do { print "TeamKit : reglage inconnu ignore : $cle\n"; next };
  my $genre = $t->[1];
  if ($genre eq "texte") {
    my $n = $v; utf8::decode($n);
    print "TeamKit : ATTENTION, $cle fait " . length($n) . " caracteres ; LMP n en garde que $t->[2] dans la liste des serveurs ou le message d accueil.\n" if length($n) > $t->[2];
    $v =~ s/&/&amp;/g; $v =~ s/</&lt;/g; $v =~ s/>/&gt;/g;
  } elsif ($genre eq "bool") {
    if (lc($v) eq "true" || lc($v) eq "false") { $v = lc($v) } else { push @erreurs, "$cle doit valoir true ou false, pas \"$v\"" }
  } elsif ($genre eq "entier") {
    push @erreurs, "$cle doit etre un nombre entier de 1 a 1000, pas \"$v\"" unless $v =~ /^\d{1,4}\z/ && $v >= 1 && $v <= 1000;
  } else {
    my ($bon) = grep { lc($_) eq lc($v) } split /\|/, $genre;
    if (defined $bon) { $v = $bon } else { push @erreurs, "$cle doit valoir " . join(", ", split /\|/, $genre) . ", pas \"$v\"" }
  }
  $valeurs{$t->[0]}{$cle} = $v;
}
close $f;
my @absentes = grep { my $c = $_; !exists $valeurs{$TABLE{$c}[0]}{$c} } sort keys %TABLE;
print "TeamKit : reglages absents de reglages-amp.txt (valeur actuelle gardee) : @absentes\n" if @absentes;
if (@erreurs) { print "ERREUR : $_\n" for @erreurs; print "Corrige ce reglage dans l onglet Configuration d AMP, puis relance.\n"; exit 2 }
# Imposes par le template, pas exposes dans AMP.
$valeurs{ConnectionSettings}{Port} = $port;            # le port attribue par AMP
$valeurs{ConnectionSettings}{Upnp} = "false";          # pas de box a ouvrir : 5 s perdues a chaque demarrage
$valeurs{WebsiteSettings}{EnableWebsite} = "false";    # page JSON sur 8900/tcp : port non ouvert par AMP
$valeurs{LogSettings}{LogLevel} = "Debug";             # la ligne de depart d un joueur est au niveau Debug
# Qualite du terrain : LMP impose la meme chez tous les joueurs, et met High par defaut ; un KSP neuf est en Default,
# donc chaque nouveau joueur etait deconnecte (vu le 11/10/2026). Default sur un univers NEUF seulement : un choix
# fait a la main dans GeneralSettings.xml n est jamais ecrase.
$valeurs{GeneralSettings}{TerrainQuality} = "Default" unless -e "$dossier/GeneralSettings.xml";
for my $nom (sort keys %valeurs) {
  my $chemin = "$dossier/$nom.xml";
  my $racine = "${nom}Definition";
  my $texte;
  if (-e $chemin) {
    open(my $x, "<:raw", $chemin) or die "ERREUR : lecture de $chemin impossible\n";
    local $/; $texte = <$x>; close $x;
  } else {
    $texte = "<?xml version=\"1.0\"?>\n<$racine>\n</$racine>\n";
  }
  my $avant = $texte;
  for my $e (sort keys %{$valeurs{$nom}}) {
    my $v = $valeurs{$nom}{$e};
    if ($texte =~ s{<$e>.*?</$e>}{<$e>$v</$e>}s) { }
    elsif ($texte =~ s{<$e\s*/>}{<$e>$v</$e>}) { }
    elsif ($texte =~ s{(\s*)</$racine>}{\n  <$e>$v</$e>$1</$racine>}) { }
    else { die "ERREUR : $chemin ne contient pas </$racine>. Supprime ce fichier : LMP le recreera.\n" }
  }
  next if $texte eq $avant;
  open(my $o, ">:raw", "$chemin.tmp") or die "ERREUR : ecriture de $chemin impossible\n";
  print $o $texte; close $o;
  rename("$chemin.tmp", $chemin) or die "ERREUR : remplacement de $chemin impossible\n";
}
print "TeamKit : reglages d AMP recopies dans serveur/Config/ (port $port).\n";
'
perl -e "$PERL_REGLAGES" "$REGLAGES" "$CFG" "$PORT" || exit 1
# Utilise seulement par verifier.py : applique les reglages sans lancer le serveur.
[ -n "$TK_ESSAI_REGLAGES" ] && exit 0

if [ -n "$(ss -Hlun "sport = :$PORT" 2>/dev/null)" ]; then
  echo "ERREUR : le port $PORT (UDP) est deja pris dans ce conteneur. Un autre serveur tourne-t-il encore ?"
  exit 1
fi

# Fichiers de travail hors du dossier de l'instance : une sauvegarde AMP qui lirait
# la fifo resterait bloquee.
TMPD="${XDG_RUNTIME_DIR:-/tmp}"
SORTIE="$TMPD/lmp-$PORT.sortie"
PRET="$TMPD/lmp-$PORT.pret"
rm -f "$SORTIE" "$PRET"
mkfifo "$SORTIE" || { echo "ERREUR : fifo $SORTIE impossible."; exit 1; }

# - entree : la console d'AMP, directement (LMP lit une commande par ligne) ;
# - env --default-signal=INT : bash met SIGINT en « ignore » pour une commande lancee en
#   arriere-plan, et .NET ne pose alors pas son gestionnaire de Ctrl+C (essai du 10/10/2026) ;
# - setpriv --pdeathsig TERM : si ce script est tue net, le serveur ne reste pas sur le port.
# - <&3 : sans redirection explicite, bash donne /dev/null comme entree a une commande en
#   arriere-plan, et la console d'AMP n'arriverait jamais.
cd "$SRV" || exit 1
exec 3<&0
setpriv --pdeathsig TERM -- env --default-signal=INT "$BIN" <&3 > "$SORTIE" 2>&1 &
PID=$!
exec 3<&-
exec 4< "$SORTIE"
rm -f "$SORTIE"

# Le serveur tourne-t-il encore ? (un processus termine mais pas encore recueilli par
# « wait » reste visible pour kill -0 : on lit son etat, Z = termine.)
en_vie() {
  local etat
  etat=$(cut -d ' ' -f 3 "/proc/$PID/stat" 2>/dev/null) || return 1
  [ -n "$etat" ] && [ "$etat" != Z ]
}

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, LMP enregistre l'univers puis s'arrete."
  kill -INT "$PID" 2>/dev/null
  # Filet : si LMP ne s'est pas arrete au bout de 45 s, arret sans sauvegarde.
  # Compteur et pas « for _ in $(seq ...) » : le piege s'execute pendant « IFS= read »,
  # avec IFS vide, et $(seq 1 90) ne serait plus coupe en 90 mots (essai du 10/10/2026).
  ( n=0
    while [ "$n" -lt 90 ]; do en_vie || exit 0; sleep 0.5; n=$((n + 1)); done
    echo "TeamKit : LMP ne repond pas a Ctrl+C depuis 45 s, arret force."
    kill -TERM "$PID" 2>/dev/null; sleep 5; kill -KILL "$PID" 2>/dev/null ) &
}
trap arreter TERM INT

DERNIERE_ALERTE=0
SUITE=0
NOTE=""
# read -t 1 : bash ne lance un piege qu'une fois la lecture rendue. Un SIGTERM arrive juste
# avant l'appel bloquant restait en attente tant que LMP n'ecrivait rien (essai du 10/10/2026 :
# arret jamais fait). Avec un delai d'une seconde, le piege part au plus tard une seconde
# apres. Une ligne coupee par le delai est recollee (DEBUT).
DEBUT=""
while :; do
  if IFS= read -r -t 1 ligne <&4; then
    ligne="$DEBUT${ligne%$'\r'}"
    DEBUT=""
    case "$ligne" in
      *"]: All systems up and running"*)
        : > "$PRET" ;;
      *"][Warning]: There is a new version of LMP!"*)
        # LMP le repete toutes les 30 secondes, avec la ligne « Your version is ... » qui
        # suit : une fois par heure suffit.
        MAINTENANT=$(date +%s)
        if [ $((MAINTENANT - DERNIERE_ALERTE)) -lt 3600 ]; then
          SUITE=0
          continue
        fi
        DERNIERE_ALERTE=$MAINTENANT
        SUITE=1 ;;
      *"]: Your version is "*"compatible with the latest version"*)
        [ "$SUITE" = 1 ] || continue
        SUITE=0 ;;
      *"][LMP]: Restarting..."*)
        # /restartserver (console ou fenetre Admin du jeu) : LMP relance « Server.exe », qui
        # n'existe pas sous Linux, puis attend une touche. On le traite comme un echec.
        rm -f "$PRET"
        NOTE="TeamKit : sous Linux, LMP ne sait pas se relancer tout seul. Le serveur va s'arreter : redemarre-le depuis AMP." ;;
      *"][Fatal]: "*)
        # Erreur fatale au demarrage : LMP attend alors une touche (Console.ReadLine) au lieu
        # de quitter, et l'instance resterait « en marche » sans serveur. Si le serveur n'est
        # pas pret 3 s plus tard, on l'arrete.
        if [ ! -e "$PRET" ] && [[ "$ligne" != *"Default settings will be used"* ]]; then
          ( sleep 3; [ -e "$PRET" ] && exit 0
            echo "TeamKit : LMP est bloque sur une erreur (ligne Fatal ci-dessus) et attend une touche : arret."
            kill -TERM "$PID" 2>/dev/null ) &
        fi ;;
    esac
    printf '%s\n' "$ligne"
    if [ -n "$NOTE" ]; then echo "$NOTE"; NOTE=""; fi
  else
    # >128 : delai d'une seconde ecoule (ou signal d'arret : le piege a deja agi) ;
    # ce qui a deja ete lu de la ligne en cours est garde pour la suite.
    if [ $? -gt 128 ]; then
      DEBUT="$DEBUT$ligne"
      continue
    fi
    [ -n "$DEBUT$ligne" ] && printf '%s\n' "$DEBUT$ligne"
    break
  fi
done

wait "$PID"
CODE=$?
rm -f "$PRET"
if [ "$ARRET" = 1 ] && { [ "$CODE" = 0 ] || [ "$CODE" = 130 ]; }; then
  echo "TeamKit : serveur LMP arrete proprement."
  exit 0
fi
exit "$CODE"
