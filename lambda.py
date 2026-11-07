#!/usr/bin/env python3
"""
lambda — un interpréteur de λ-calcul pur, qui dessine les termes en
diagrammes de Tromp.

Dans le λ-calcul il n'y a QUE des fonctions à un argument : pas de nombres,
pas de booléens, pas de boucles. Tout se construit avec des fonctions
(entiers de Church, combinateur Y...) et le seul calcul est la β-réduction :
(λx. corps) argument  →  corps où x est remplacé par argument.

  python3 lambda.py                     boucle interactive (prélude chargé)
  python3 lambda.py fichier.lam         exécuter un fichier
  python3 lambda.py -e "FACT 4"         évaluer une expression
"""
import os
import re
import sys

sys.setrecursionlimit(1_000_000)

# ===================================================================== termes
# Indices de de Bruijn : une variable est le nombre de λ à remonter pour
# trouver celui qui la lie. λx. λy. x  s'écrit  λ λ 1. Plus de capture de
# variable possible, et deux termes équivalents sont égaux tels quels.


class Var:
    __slots__ = ("i", "libre")

    def __init__(self, i):
        self.i, self.libre = i, i + 1

    def __eq__(self, o):
        return isinstance(o, Var) and o.i == self.i

    def __hash__(self):
        return hash(("v", self.i))


class Lam:
    __slots__ = ("b", "nom", "libre")

    def __init__(self, b, nom="x"):
        self.b, self.nom, self.libre = b, nom, max(b.libre - 1, 0)

    def __eq__(self, o):
        return isinstance(o, Lam) and o.b == self.b

    def __hash__(self):
        return hash(("l", self.b))


class App:
    __slots__ = ("f", "a", "libre")

    def __init__(self, f, a):
        self.f, self.a, self.libre = f, a, max(f.libre, a.libre)

    def __eq__(self, o):
        return isinstance(o, App) and o.f == self.f and o.a == self.a

    def __hash__(self):
        return hash(("a", self.f, self.a))


# `libre` = 1 + le plus grand indice libre du terme (0 s'il est clos). Il
# permet de ne pas reconstruire les sous-termes qu'une substitution ou un
# décalage ne touche pas : ils sont partagés tels quels.

def decale(t, d, seuil=0):
    """Ajoute d aux variables libres (indice >= seuil)."""
    if d == 0 or t.libre <= seuil:
        return t
    if isinstance(t, Var):
        return Var(t.i + d) if t.i >= seuil else t
    if isinstance(t, Lam):
        return Lam(decale(t.b, d, seuil + 1), t.nom)
    return App(decale(t.f, d, seuil), decale(t.a, d, seuil))


def substitue(t, j, s):
    """t[j := s]"""
    if t.libre <= j:
        return t
    if isinstance(t, Var):
        return s if t.i == j else t
    if isinstance(t, Lam):
        return Lam(substitue(t.b, j + 1, decale(s, 1)), t.nom)
    return App(substitue(t.f, j, s), substitue(t.a, j, s))


def beta(lam, arg):
    """(λ. corps) arg  →  corps[0 := arg], puis on retire le λ disparu."""
    return decale(substitue(lam.b, 0, decale(arg, 1)), -1)


def etape(t):
    """Une β-réduction en ordre normal (le rédex le plus à gauche, le plus
    à l'extérieur). Renvoie (nouveau terme, chemin du rédex) ou (t, None).
    Cet ordre trouve toujours la forme normale quand elle existe."""
    if isinstance(t, App):
        if isinstance(t.f, Lam):
            return beta(t.f, t.a), ()
        f, ch = etape(t.f)
        if ch is not None:
            return App(f, t.a), ("f",) + ch
        a, ch = etape(t.a)
        if ch is not None:
            return App(t.f, a), ("a",) + ch
        return t, None
    if isinstance(t, Lam):
        b, ch = etape(t.b)
        return (Lam(b, t.nom), ("b",) + ch) if ch is not None else (t, None)
    return t, None


def taille(t):
    pile, n = [t], 0
    while pile:
        u = pile.pop()
        n += 1
        if isinstance(u, Lam):
            pile.append(u.b)
        elif isinstance(u, App):
            pile += (u.f, u.a)
    return n


# =========================================== normalisation par évaluation (NbE)
# Pour aller vite : on transforme le terme en vraies fonctions Python
# (paresseuses, comme l'ordre normal), on les applique, puis on relit le
# résultat comme un terme. Même forme normale, sans compter les étapes.

class _Neutre:
    __slots__ = ("niveau", "args")

    def __init__(self, niveau, args=()):
        self.niveau, self.args = niveau, args


class _Fermeture:
    __slots__ = ("corps", "env", "nom")

    def __init__(self, corps, env, nom):
        self.corps, self.env, self.nom = corps, env, nom


class _Glacon:
    """Argument pas encore évalué (évaluation paresseuse, partagée)."""
    __slots__ = ("terme", "env", "val")

    def __init__(self, terme, env):
        self.terme, self.env, self.val = terme, env, None

    def force(self):
        if self.val is None:
            self.val = _eval(self.terme, self.env)
            self.terme = self.env = None
        return self.val


class _Carburant:
    reste = 0


def _consomme():
    _Carburant.reste -= 1
    if _Carburant.reste < 0:
        raise RuntimeError("pas de forme normale trouvée (le calcul ne s'arrête peut-être jamais)")


def _eval(t, env):
    while True:
        _consomme()
        if isinstance(t, Var):
            v = env[-1 - t.i]
            return v.force() if isinstance(v, _Glacon) else v
        if isinstance(t, Lam):
            return _Fermeture(t.b, env, t.nom)
        f = _eval(t.f, env)
        arg = _Glacon(t.a, env)
        if isinstance(f, _Fermeture):
            t, env = f.corps, f.env + (arg,)
            continue
        return _Neutre(f.niveau, f.args + (arg,))


def _applique(f, arg):
    if isinstance(f, _Fermeture):
        return _eval(f.corps, f.env + (arg,))
    return _Neutre(f.niveau, f.args + (arg,))


def _relit(v, niveau):
    _consomme()
    if isinstance(v, _Glacon):
        v = v.force()
    if isinstance(v, _Fermeture):
        x = _Neutre(niveau)
        return Lam(_relit(_applique(v, x), niveau + 1), v.nom)
    t = Var(niveau - 1 - v.niveau)
    for a in v.args:
        t = App(t, _relit(a, niveau))
    return t


def normalise_vite(t, carburant=5_000_000):
    _Carburant.reste = carburant
    try:
        return _relit(_eval(t, ()), 0)
    except RecursionError:
        raise RuntimeError("terme trop profond")


# ===================================================================== lecture

class ErreurSyntaxe(Exception):
    pass


JETONS = re.compile(r"\s*(?:(λ|\\)|(\.)|(\()|(\))|(\d+)|([A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_?'!]*))")


def jetons(texte):
    pos, res = 0, []
    texte = texte.rstrip()
    while pos < len(texte):
        m = JETONS.match(texte, pos)
        if not m or m.end() == pos:
            raise ErreurSyntaxe(f"caractère inattendu : {texte[pos:].strip()[:1]!r} (colonne {pos + 1})")
        pos = m.end()
        for genre, val in zip(("lam", "point", "(", ")", "nombre", "nom"), m.groups()):
            if val is not None:
                res.append((genre, val))
    return res


def church(n):
    corps = Var(0)
    for _ in range(n):
        corps = App(Var(1), corps)
    return Lam(Lam(corps, "x"), "f")


class Lecteur:
    """terme  := λ noms . terme | application
       application := atome atome ...
       atome  := nom | nombre | ( terme )"""

    def __init__(self, texte, definitions):
        self.j, self.k, self.defs = jetons(texte), 0, definitions

    def voit(self, genre):
        return self.k < len(self.j) and self.j[self.k][0] == genre

    def prend(self, genre):
        if not self.voit(genre):
            vu = self.j[self.k][1] if self.k < len(self.j) else "la fin de la ligne"
            attendu = {"point": "'.'", ")": "')'", "nom": "un nom"}.get(genre, genre)
            raise ErreurSyntaxe(f"j'attendais {attendu}, j'ai trouvé {vu!r}")
        self.k += 1
        return self.j[self.k - 1][1]

    def terme(self, portee):
        if self.voit("lam"):
            self.prend("lam")
            noms = [self.prend("nom")]
            while self.voit("nom"):
                noms.append(self.prend("nom"))
            self.prend("point")
            corps = self.terme(portee + noms)
            for nom in reversed(noms):
                corps = Lam(corps, nom)
            return corps
        t = self.atome(portee)
        while self.k < len(self.j) and not self.voit(")"):
            if self.voit("lam"):  # f λx. ... : le λ s'étend jusqu'au bout
                return App(t, self.terme(portee))
            t = App(t, self.atome(portee))
        return t

    def atome(self, portee):
        if self.voit("("):
            self.prend("(")
            t = self.terme(portee)
            self.prend(")")
            return t
        if self.voit("nombre"):
            return church(int(self.prend("nombre")))
        if self.voit("nom"):
            nom = self.prend("nom")
            if nom in portee:
                return Var(len(portee) - 1 - max(i for i, n in enumerate(portee) if n == nom))
            if nom in self.defs:
                return decale(self.defs[nom], len(portee))
            raise ErreurSyntaxe(f"« {nom} » n'est ni une variable liée ni une définition")
        raise ErreurSyntaxe("terme incomplet")

    def tout(self):
        if not self.j:
            raise ErreurSyntaxe("rien à lire")
        t = self.terme([])
        if self.k != len(self.j):
            raise ErreurSyntaxe(f"en trop : {self.j[self.k][1]!r}")
        return t


# =================================================================== affichage

COULEUR = sys.stdout.isatty()


def montre(t, rouge=None):
    """Écrit le terme avec des noms (renommés si besoin pour éviter les
    confusions) ; le sous-terme au chemin `rouge` est mis en évidence."""

    def nom_libre(nom, noms):
        while nom in noms:
            nom += "'"
        return nom

    def rec(t, noms, chemin, gauche_app=False, dans_arg=False):
        surligne = rouge is not None and chemin == rouge
        if isinstance(t, Var):
            s = noms[-1 - t.i] if t.i < len(noms) else f"?{t.i}"
        elif isinstance(t, Lam):
            liants, u, ch = [], t, chemin
            while isinstance(u, Lam):
                n = nom_libre(u.nom, noms + liants)
                liants.append(n)
                u, ch = u.b, ch + ("b",)
            s = "λ" + " ".join(liants) + ". " + rec(u, noms + liants, ch)
            if gauche_app or dans_arg:
                s = f"({s})"
        else:
            f = rec(t.f, noms, chemin + ("f",), gauche_app=True)
            a = rec(t.a, noms, chemin + ("a",), dans_arg=True)
            if isinstance(t.a, App):
                a = f"({a})"
            s = f"{f} {a}"
        if surligne:
            s = f"\033[1;35m{s}\033[0m" if COULEUR else f"[{s}]"
        return s

    return rec(t, [], ())


def lit_entier(t):
    """λf x. f (f (... x)) -> n, sinon None."""
    if isinstance(t, Lam) and isinstance(t.b, Lam):
        n, u = 0, t.b.b
        while isinstance(u, App) and u.f == Var(1):
            n, u = n + 1, u.a
        if u == Var(0):
            return n
    return None


def interprete(t, defs_nf):
    morceaux = []
    n = lit_entier(t)
    if n is not None:
        morceaux.append(str(n))
    if t == Lam(Lam(Var(1))):
        morceaux.append("VRAI")
    if t == Lam(Lam(Var(0))):
        morceaux.append("FAUX")
    morceaux += [nom for nom, nf in defs_nf.items() if nf == t and nom not in morceaux and not nom.isdigit()][:3]
    return " ≡ ".join(dict.fromkeys(morceaux))


# ================================================================ diagrammes

def tromp_svg(termes, titres=None, u=8):
    """Diagrammes de Tromp :
       - un λ est une barre horizontale ;
       - une variable est un trait vertical qui descend de la barre de son λ ;
       - une application relie, par un trait horizontal en bas, le trait de la
         fonction et celui de l'argument ; celui de la fonction continue.
    Plusieurs termes sont dessinés côte à côte (une réduction pas à pas)."""
    traits = []

    def place(t, x, y, barres):
        """Renvoie (largeur, hauteur, colonne du trait qui pend en bas)."""
        if isinstance(t, Var):
            traits.append(("v", x, barres[-1 - t.i], y))
            return 1, 0, x
        if isinstance(t, Lam):
            w, h, c = place(t.b, x, y + 1, barres + [y])
            traits.append(("h", x, x + w - 1, y))
            return w, h + 1, c
        wf, hf, cf = place(t.f, x, y, barres)
        wa, ha, ca = place(t.a, x + wf + 1, y, barres)  # une colonne vide entre les deux
        wa += 1
        h = max(hf, ha) + 1
        traits.append(("v", cf, y + hf, y + h))  # la fonction continue vers le bas
        traits.append(("v", ca, y + ha, y + h - 1))  # l'argument descend jusqu'au lien
        traits.append(("a", cf, ca, y + h - 1))  # le lien d'application
        return wf + wa, h, cf

    boites, x0, hmax = [], 1, 0
    for k, t in enumerate(termes):
        w, h, c = place(t, x0, 1, [])
        traits.append(("v", c, 1 + h, 1 + h + 1))
        largeur_titre = int(len(titres[k]) * 6.5 / u) + 1 if titres else 0
        boites.append((x0, max(w, largeur_titre)))
        x0 += max(w, largeur_titre) + 3
        hmax = max(hmax, h + 2)
    W, H = x0 * u, (hmax + 2) * u + (14 if titres else 0)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
         f'<rect width="{W}" height="{H}" fill="#0b0710"/>']
    for genre, a, b, c in traits:
        if genre == "v":  # colonne a, de la ligne b à la ligne c
            X = a * u + u / 2
            o.append(f'<line x1="{X}" x2="{X}" y1="{b * u + u / 2}" y2="{c * u + u / 2}" stroke="#d6a6ff" stroke-width="{u * 0.3}"/>')
        else:  # de la colonne a à la colonne b, ligne c : barre de λ ou lien d'application
            couleur = "#ff8c42" if genre == "h" else "#d6a6ff"
            debut, fin = (a * u + u * 0.15, b * u + u * 0.85) if genre == "h" else (a * u + u / 2, b * u + u / 2)
            o.append(f'<line x1="{debut}" x2="{fin}" y1="{c * u + u / 2}" y2="{c * u + u / 2}" '
                     f'stroke="{couleur}" stroke-width="{u * 0.3}" stroke-linecap="square"/>')
    if titres:
        for (x, w), titre in zip(boites, titres):
            o.append(f'<text x="{(x + w / 2) * u}" y="{H - 6}" fill="#a89cb8" font-family="sans-serif" font-size="11" '
                     f'text-anchor="middle">{titre}</text>')
    o.append("</svg>")
    return "\n".join(o)


# ===================================================================== session

class Session:
    def __init__(self):
        self.defs, self.defs_nf = {}, {}
        self.trace, self.max_etapes, self.rapide = False, 200_000, False

    def charge(self, chemin):
        with open(chemin, encoding="utf-8") as f:
            for num, ligne in enumerate(f, 1):
                try:
                    self.ligne(ligne, silencieux=True)
                except ErreurSyntaxe as e:
                    raise SystemExit(f"{chemin}:{num} : {e}")

    def lit(self, texte):
        return Lecteur(texte, self.defs).tout()

    def normalise(self, t, afficher=False):
        if self.rapide:
            return normalise_vite(t), None  # RuntimeError si ça ne s'arrête pas
        n = 0
        while True:
            u, ch = etape(t)
            if ch is None:
                return t, n
            if afficher:
                print(f"  {n:>4}  {montre(t, ch)}")
            t, n = u, n + 1
            if n >= self.max_etapes:
                raise RuntimeError(f"pas de forme normale après {n} étapes (le calcul ne s'arrête peut-être jamais)")

    def ligne(self, ligne, silencieux=False):
        ligne = re.split(r"--|#", ligne, maxsplit=1)[0].strip()
        if not ligne:
            return
        if ligne.startswith(":"):
            return self.commande(ligne)
        m = re.match(r"([A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_?'!]*)\s*=(?!=)\s*(.*)", ligne)
        if m:
            nom, corps = m.groups()
            t = self.lit(corps)
            self.defs[nom] = t
            try:  # forme normale, pour reconnaître un résultat (« ≡ SUCC »)
                self.defs_nf[nom] = normalise_vite(t, carburant=20_000)
            except RuntimeError:
                self.defs_nf.pop(nom, None)  # Y, OMEGA, FACT... n'en ont pas
            if not silencieux:
                print(f"  {nom} défini")
            return
        t = self.lit(ligne)
        try:
            nf, n = self.normalise(t, afficher=self.trace)
        except RuntimeError as e:
            print(f"  {e}")
            return
        sens = interprete(nf, self.defs_nf)
        etapes = f"   ({n} réduction{'s' if n != 1 else ''} β)" if n is not None else ""
        entier = lit_entier(nf)
        brut = montre(nf) if entier is None or entier <= 6 else "λf x. f (f (f (… (f x))))"
        print(f"  = {sens + '   ' if sens else ''}{brut}{etapes}")

    def commande(self, ligne):
        mots = ligne.split(maxsplit=2)
        c = mots[0]
        if c in (":trace", ":t"):
            self.trace = not self.trace
            print(f"  trace {'activée' if self.trace else 'désactivée'}")
        elif c == ":rapide":
            self.rapide = not self.rapide
            print(f"  mode rapide (normalisation par évaluation) {'activé' if self.rapide else 'désactivé'}")
        elif c == ":defs":
            for nom, t in self.defs.items():
                print(f"  {nom:10} = {montre(t)}")
        elif c in (":dessin", ":film") and len(mots) == 3:
            t = self.lit(mots[2])
            if c == ":dessin":
                try:
                    termes, titres = [t, normalise_vite(t)], ["terme", "forme normale"]
                except RuntimeError:
                    termes, titres = [t], ["terme (pas de forme normale)"]
            else:
                termes, titres = [t], ["0"]
                while len(termes) < 40:
                    t, ch = etape(t)
                    if ch is None:
                        break
                    termes.append(t)
                    titres.append(str(len(termes) - 1))
            with open(mots[1], "w", encoding="utf-8") as f:
                f.write(tromp_svg(termes, titres))
            print(f"  {len(termes)} diagramme(s) -> {mots[1]}")
        elif c == ":charge" and len(mots) >= 2:
            self.charge(mots[1])
        else:
            print("  :trace            afficher chaque réduction (le rédex est en couleur)\n"
                  "  :rapide           normaliser sans compter les étapes (beaucoup plus rapide)\n"
                  "  :defs             lister les définitions\n"
                  "  :dessin f.svg T   diagramme de Tromp de T et de sa forme normale\n"
                  "  :film f.svg T     diagrammes de chaque étape de la réduction de T\n"
                  "  :charge f.lam     charger un fichier\n"
                  "  NOM = terme       définir ;  λx y. corps  ou  \\x y. corps")


def main():
    ici = os.path.dirname(os.path.abspath(__file__))
    s = Session()
    s.charge(os.path.join(ici, "prelude.lam"))
    args = sys.argv[1:]
    if args[:1] == ["-e"]:
        for expr in args[1:]:
            s.ligne(expr)
        return
    if args and args[0] in ("-h", "--aide"):
        print(__doc__)
        return
    if args:
        for chemin in args:
            with open(chemin, encoding="utf-8") as f:
                for num, ligne in enumerate(f, 1):
                    if ligne.strip() and not ligne.lstrip().startswith(("--", "#")):
                        print(f"> {ligne.rstrip()}")
                    try:
                        s.ligne(ligne)
                    except ErreurSyntaxe as e:
                        print(f"  {chemin}:{num} : {e}")
        return
    try:
        import readline  # noqa: F401  (flèches et historique)
    except ImportError:
        pass
    print("λ-calcul — :aide pour les commandes, Ctrl-D pour quitter")
    while True:
        try:
            ligne = input("λ> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            s.ligne(ligne)
        except ErreurSyntaxe as e:
            print(f"  erreur : {e}")
        except RecursionError:
            print("  terme trop profond")


if __name__ == "__main__":
    main()
