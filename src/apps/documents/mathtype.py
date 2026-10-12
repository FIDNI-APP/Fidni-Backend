"""Formules MathType et « Éditeur d'équations 3.0 » d'un document Word → LaTeX.

Dans un .docx, une formule MathType est un objet OLE (`word/embeddings/oleObjectN.bin`, ProgID
`Equation.DSMT4`, `Equation.3`…) dont Word ne montre qu'une image WMF. L'objet garde pourtant la formule
elle-même dans son flux « Equation Native » : un en-tête de 28 octets puis la formule au format MTEF
(MathType Equation Format, spécification publique de Design Science), v3 (Éditeur d'équations 3.0,
MathType 3) ou v5 (MathType 5 à 7). On le lit ici en arbre (lignes, caractères, gabarits, piles,
matrices), puis on écrit le LaTeX lu par KaTeX.

Une entrée hostile ne fait qu'échouer proprement (MathTypeErreur) : lecture bornée, profondeur bornée.
"""
import io
import re
import struct

MAX_OLE = 2 * 1024 * 1024
MAX_PROFONDEUR = 64
MAX_NOEUDS = 20000


class MathTypeErreur(Exception):
    pass


# ── Lecture ────────────────────────────────────────────────────────────────────────────────────────

class _Lecteur:
    def __init__(self, data):
        self.d, self.p, self.noeuds = data, 0, 0

    def u8(self):
        if self.p >= len(self.d):
            raise MathTypeErreur('fin de données inattendue')
        self.p += 1
        return self.d[self.p - 1]

    def u16(self):
        return self.u8() | (self.u8() << 8)

    def mtuint(self):
        b = self.u8()
        return b if b < 0xFF else self.u16()

    def cstr(self):
        fin = self.d.find(b'\x00', self.p)
        if fin < 0:
            raise MathTypeErreur('chaîne non terminée')
        s = self.d[self.p:fin]
        self.p = fin + 1
        return s

    def saut(self, n):
        self.p += n
        if self.p > len(self.d):
            raise MathTypeErreur('fin de données inattendue')


class Ligne:
    def __init__(self, objets):
        self.objets = objets  # None : emplacement vide


class Car:
    def __init__(self, code, police, embell, debut_fonction=False):
        self.code, self.police, self.embell, self.debut_fonction = code, police, embell, debut_fonction


class Gabarit:
    def __init__(self, selecteur, variation, sous):
        self.selecteur, self.variation, self.sous = selecteur, variation, sous


class Pile:
    def __init__(self, halign, lignes):
        self.halign, self.lignes = halign, lignes


class Matrice:
    def __init__(self, lignes, colonnes, traits_l, traits_c, cases):
        self.lignes, self.colonnes, self.traits_l, self.traits_c, self.cases = lignes, colonnes, traits_l, traits_c, cases


class Embell:
    def __init__(self, sorte):
        self.sorte = sorte


def _decalage(r):
    dx, dy = r.u8(), r.u8()
    if dx == 128 and dy == 128:
        r.u16(), r.u16()


def _regle(r):
    for _ in range(r.u8()):
        r.u8(), r.u16()


def _taille(r):
    s = r.u8()
    if s == 101:
        r.u16()
    elif s == 100:
        r.u8(), r.u16()
    else:
        r.u8()


def _quartets(r, n):
    """Tableaux de dimensions des préférences (EQN_PREFS v5) : quartets, unité puis valeurs jusqu'à 0xF."""
    reste = []

    def q():
        if not reste:
            b = r.u8()
            reste.extend([b >> 4, b & 0x0F])
        return reste.pop(0)

    for _ in range(n):
        q()
        for _ in range(64):
            if q() == 0xF:
                break


def _traits(octets_lus, n, v3):
    vals = []
    for b in octets_lus:
        vals += ([(b >> 6) & 3, (b >> 4) & 3, (b >> 2) & 3, b & 3] if v3 else [b & 3, (b >> 2) & 3, (b >> 4) & 3, (b >> 6) & 3])
    return vals[:n]


def _liste(r, v3, prof):
    """Objets jusqu'à l'enregistrement END."""
    if prof > MAX_PROFONDEUR:
        raise MathTypeErreur('formule trop imbriquée')
    out = []
    while True:
        r.noeuds += 1
        if r.noeuds > MAX_NOEUDS:
            raise MathTypeErreur('formule trop longue')
        o = _enregistrement(r, v3, prof)
        if o is _FIN:
            return out
        if o is not None:
            out.append(o)


_FIN = object()


def _enregistrement(r, v3, prof):
    tag = r.u8()
    if v3:
        sorte, opts = tag & 0x0F, tag >> 4
        NUDGE, NULL, LSPACE, RULER, EMB = 0x08, 0x01, 0x04, 0x02, 0x02
    else:
        sorte = tag
        if sorte == 0:
            return _FIN
        opts = r.u8() if sorte in (1, 2, 3, 4, 5, 6) else 0
        NUDGE, NULL, LSPACE, RULER, EMB = 0x08, 0x01, 0x04, 0x02, 0x01
    if sorte == 0:
        return _FIN
    if sorte in (1, 2, 3, 4, 5, 6) and opts & NUDGE:
        _decalage(r)
    if sorte == 1:  # LINE
        if opts & LSPACE:
            r.u16()
        if opts & RULER:
            _regle(r)
        return Ligne(None if opts & NULL else _liste(r, v3, prof + 1))
    if sorte == 2:  # CHAR
        police = (r.u8() + 128) & 0xFF
        if v3:
            code = r.u16()
        else:
            code = r.u16() if not opts & 0x20 else None
            if opts & 0x04:
                b = r.u8()
                code = b if code is None else code
            elif opts & 0x10:
                c = r.u16()
                code = c if code is None else code
        embell = [e.sorte for e in _liste(r, v3, prof + 1) if isinstance(e, Embell)] if opts & EMB else []
        return Car(code or 0, police, embell, debut_fonction=(not v3 and bool(opts & 0x02)))
    if sorte == 3:  # TMPL
        sel = r.u8()
        v = r.u8()
        if not v3 and v & 0x80:
            v = (v & 0x7F) | (r.u8() << 8)
        r.u8()  # options propres au gabarit
        return Gabarit(sel, v, _liste(r, v3, prof + 1))
    if sorte == 4:  # PILE
        halign = r.u8()
        r.u8()
        if opts & RULER:
            _regle(r)
        return Pile(halign, [x for x in _liste(r, v3, prof + 1) if isinstance(x, (Ligne, Pile))])
    if sorte == 5:  # MATRIX
        r.u8(), r.u8(), r.u8()
        nl, nc = r.u8(), r.u8()
        if v3:
            tl = [r.u8() for _ in range((2 * (nl + 1) + 7) // 8)]
            tc = [r.u8() for _ in range((2 * (nc + 1) + 7) // 8)]
        else:
            tl = [r.u8() for _ in range((nl + 4) // 4)]
            tc = [r.u8() for _ in range((nc + 4) // 4)]
        cases = [x for x in _liste(r, v3, prof + 1) if isinstance(x, (Ligne, Pile))]
        return Matrice(nl, nc, _traits(tl, nl + 1, v3), _traits(tc, nc + 1, v3), cases)
    if sorte == 6:  # EMBELL (en MTEF 3, un octet de plus suit le type)
        e = r.u8()
        if v3:
            r.u8()
        return Embell(e)
    if sorte == 7:
        _regle(r)
    elif sorte == 8:
        if v3:
            r.u8(), r.u8(), r.cstr()
        else:
            r.mtuint(), r.u8()
    elif sorte == 9:
        _taille(r)
    elif sorte in (10, 11, 12, 13, 14):
        pass
    elif v3:
        raise MathTypeErreur(f'enregistrement MTEF 3 inconnu ({sorte})')
    elif sorte == 15:
        r.mtuint()
    elif sorte == 16:
        o = r.u8()
        for _ in range(4 if o & 1 else 3):
            r.u16()
        if o & 4:
            r.cstr()
    elif sorte == 17:
        r.mtuint(), r.cstr()
    elif sorte == 18:
        r.u8()
        _quartets(r, r.u8())
        _quartets(r, r.u8())
        for _ in range(r.u8()):
            if r.u8():
                r.u8()
    elif sorte == 19:
        r.cstr()
    elif sorte == 102:
        r.mtuint(), r.cstr(), r.cstr()
    elif sorte >= 100:
        r.saut(r.u8())
    else:
        raise MathTypeErreur(f'enregistrement MTEF inconnu ({sorte})')
    return None


def lire_mtef(data):
    """Octets MTEF → (version, objets du niveau supérieur)."""
    r = _Lecteur(data)
    version = r.u8()
    r.u8(), r.u8(), r.u8(), r.u8()  # plateforme, produit, version, sous-version
    if version == 3:
        return 3, _liste(r, True, 0)
    if version in (4, 5):
        r.cstr()  # clé d'application (« DSMT4 »…)
        r.u8()    # options de l'équation
        return 5, _liste(r, False, 0)
    raise MathTypeErreur(f'MTEF version {version} non prise en charge')


def mtef_de_ole(octets):
    """Objet OLE (oleObjectN.bin) → octets MTEF du flux « Equation Native »."""
    if len(octets) > MAX_OLE:
        raise MathTypeErreur('objet trop lourd')
    try:
        import olefile
        with olefile.OleFileIO(io.BytesIO(octets)) as ole:
            if not ole.exists('Equation Native'):
                raise MathTypeErreur('pas de flux « Equation Native »')
            flux = ole.openstream('Equation Native').read()
    except MathTypeErreur:
        raise
    except Exception as e:
        raise MathTypeErreur(f'objet OLE illisible ({e.__class__.__name__})')
    if len(flux) < 30:
        raise MathTypeErreur('flux trop court')
    entete = struct.unpack('<H', flux[:2])[0]
    return flux[entete:]


# ── Écriture LaTeX ─────────────────────────────────────────────────────────────────────────────────

SYMBOLES = {
    0x00B1: r'\pm', 0x00D7: r'\times', 0x00F7: r'\div', 0x00B7: r'\cdot', 0x2212: '-', 0x2213: r'\mp',
    0x2264: r'\leqslant', 0x2265: r'\geqslant', 0x2A7D: r'\leqslant', 0x2A7E: r'\geqslant', 0x2260: r'\neq',
    0x2248: r'\approx', 0x2261: r'\equiv', 0x223C: r'\sim', 0x2243: r'\simeq', 0x2245: r'\cong', 0x221D: r'\propto',
    0x226A: r'\ll', 0x226B: r'\gg', 0x2208: r'\in', 0x2209: r'\notin', 0x220B: r'\ni', 0x2282: r'\subset',
    0x2283: r'\supset', 0x2286: r'\subseteq', 0x2287: r'\supseteq', 0x2284: r'\not\subset', 0x2288: r'\nsubseteq',
    0x222A: r'\cup', 0x2229: r'\cap', 0x2205: r'\emptyset', 0x2300: r'\varnothing', 0x2216: r'\setminus',
    0x2200: r'\forall', 0x2203: r'\exists', 0x2204: r'\nexists', 0x00AC: r'\neg', 0x2227: r'\wedge', 0x2228: r'\vee',
    0x221E: r'\infty', 0x2202: r'\partial', 0x2207: r'\nabla', 0x2032: "'", 0x2033: "''", 0x00B0: r'^{\circ}',
    0x2192: r'\to', 0x2190: r'\leftarrow', 0x2194: r'\leftrightarrow', 0x21D2: r'\Rightarrow', 0x21D0: r'\Leftarrow',
    0x21D4: r'\Leftrightarrow', 0x27F6: r'\longrightarrow', 0x27F9: r'\Longrightarrow', 0x27FA: r'\Longleftrightarrow',
    0x21A6: r'\mapsto', 0x27FC: r'\longmapsto', 0x2197: r'\nearrow', 0x2198: r'\searrow', 0x2191: r'\uparrow',
    0x2193: r'\downarrow', 0x21C4: r'\rightleftarrows', 0x2026: r'\ldots', 0x22EF: r'\cdots', 0x22EE: r'\vdots',
    0x22F1: r'\ddots', 0x2211: r'\sum', 0x220F: r'\prod', 0x2210: r'\coprod', 0x222B: r'\int', 0x222C: r'\iint',
    0x222D: r'\iiint', 0x222E: r'\oint', 0x22C3: r'\bigcup', 0x22C2: r'\bigcap', 0x221A: r'\surd', 0x22A5: r'\perp',
    0x2225: r'\parallel', 0x2220: r'\angle', 0x2221: r'\measuredangle', 0x25B3: r'\triangle', 0x2295: r'\oplus',
    0x2297: r'\otimes', 0x2218: r'\circ', 0x2219: r'\bullet', 0x2217: '*', 0x2223: r'\mid', 0x2224: r'\nmid',
    0x2016: r'\|', 0x2329: r'\langle', 0x232A: r'\rangle', 0x27E8: r'\langle', 0x27E9: r'\rangle', 0x3008: r'\langle',
    0x3009: r'\rangle', 0x230A: r'\lfloor', 0x230B: r'\rfloor', 0x2308: r'\lceil', 0x2309: r'\rceil',
    0x2115: r'\mathbb{N}', 0x2124: r'\mathbb{Z}', 0x211A: r'\mathbb{Q}', 0x211D: r'\mathbb{R}', 0x2102: r'\mathbb{C}',
    0x2113: r'\ell', 0x210F: r'\hbar', 0x2111: r'\Im', 0x211C: r'\Re', 0x2135: r'\aleph', 0x2118: r'\wp',
    0x2146: r'\mathrm{d}', 0x2147: r'\mathrm{e}', 0x2148: r'\mathrm{i}', 0x22C5: r'\cdot', 0x2022: r'\bullet',
    0x2234: r'\therefore', 0x2235: r'\because', 0x22A2: r'\vdash', 0x2A2F: r'\times',
    0x226E: r'\not<', 0x226F: r'\not>', 0x2270: r'\nleqslant', 0x2271: r'\ngeqslant', 0x227A: r'\prec', 0x227B: r'\succ',
    0x00A0: '~', 0x2009: r'\,', 0x200A: r'\,', 0x2003: r'\quad',
    0x2002: r'\;', 0x205F: r'\:', 0x200B: '', 0xFEFF: '',
    # Zone privée MathType
    0xEF00: '', 0xEF01: '', 0xEF02: r'\,', 0xEF03: r'\:', 0xEF04: r'\;', 0xEF05: r'\quad', 0xEF06: r'\qquad',
    0xEF07: '', 0xEF08: r'\,', 0xE98F: r'\cdot', 0xE90B: r'\supseteq', 0xE90C: r'\subseteq', 0xEA06: r'\nleqslant',
    0xEA07: r'\ngeqslant', 0xEA0B: r'\nsupseteq', 0xEA0C: r'\nsubseteq', 0xEA42: r'\nsubseteq', 0xEA43: r'\nsupseteq',
    0xEA44: r'\subsetneq', 0xEA45: r'\supsetneq', 0xEA34: r'\lneqq', 0xEA35: r'\gneqq', 0xED10: r'\mathrm{d}',
    0xED11: r'\mathrm{e}', 0xED12: r'\mathrm{i}', 0xEE19: "''''",
}
GREC = {
    0x03B1: 'alpha', 0x03B2: 'beta', 0x03B3: 'gamma', 0x03B4: 'delta', 0x03B5: 'varepsilon', 0x03F5: 'epsilon',
    0x03B6: 'zeta', 0x03B7: 'eta', 0x03B8: 'theta', 0x03D1: 'vartheta', 0x03B9: 'iota', 0x03BA: 'kappa',
    0x03BB: 'lambda', 0x03BC: 'mu', 0x03BD: 'nu', 0x03BE: 'xi', 0x03BF: 'o', 0x03C0: 'pi', 0x03D6: 'varpi',
    0x03C1: 'rho', 0x03F1: 'varrho', 0x03C3: 'sigma', 0x03C2: 'varsigma', 0x03C4: 'tau', 0x03C5: 'upsilon',
    0x03C6: 'varphi', 0x03D5: 'phi', 0x03C7: 'chi', 0x03C8: 'psi', 0x03C9: 'omega',
    0x0393: 'Gamma', 0x0394: 'Delta', 0x0398: 'Theta', 0x039B: 'Lambda', 0x039E: 'Xi', 0x03A0: 'Pi', 0x03A3: 'Sigma',
    0x03A5: 'Upsilon', 0x03A6: 'Phi', 0x03A8: 'Psi', 0x03A9: 'Omega',
}
# Majuscules grecques identiques aux latines.
GREC_LATIN = {0x0391: 'A', 0x0392: 'B', 0x0395: 'E', 0x0396: 'Z', 0x0397: 'H', 0x0399: 'I', 0x039A: 'K', 0x039C: 'M',
              0x039D: 'N', 0x039F: 'O', 0x03A1: 'P', 0x03A4: 'T', 0x03A7: 'X'}
ECHAPPES = {'{': r'\{', '}': r'\}', '#': r'\#', '%': r'\%', '&': r'\&', '_': r'\_', '$': r'\$', '\\': r'\backslash',
            '~': r'\sim', '^': r'\hat{}', '<': '<', '>': '>'}
FONCTIONS = {'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'sinh', 'cosh', 'tanh', 'coth', 'arcsin', 'arccos', 'arctan',
             'ln', 'log', 'lg', 'exp', 'lim', 'limsup', 'liminf', 'max', 'min', 'sup', 'inf', 'det', 'dim', 'ker',
             'deg', 'gcd', 'arg', 'Pr', 'hom'}
FONCTIONS_FR = {'tg': r'\operatorname{tg}', 'th': r'\operatorname{th}', 'ch': r'\operatorname{ch}', 'sh': r'\operatorname{sh}',
                'Arctan': r'\operatorname{Arctan}', 'pgcd': r'\operatorname{pgcd}', 'ppcm': r'\operatorname{ppcm}',
                'card': r'\operatorname{card}', 'Card': r'\operatorname{Card}', 'Im': r'\operatorname{Im}',
                'Re': r'\operatorname{Re}', 'Ker': r'\operatorname{Ker}', 'id': r'\operatorname{id}'}
EMBELLS = {2: r'\dot', 3: r'\ddot', 4: r'\dddot', 8: r'\tilde', 9: r'\hat', 11: r'\vec', 12: r'\overleftarrow',
           13: r'\overleftrightarrow', 14: r'\vec', 15: r'\overleftarrow', 17: r'\bar', 19: r'\overgroup',
           20: r'\overgroup', 24: r'\ddddot', 29: r'\underline', 30: r'\utilde', 33: r'\underrightarrow',
           34: r'\underleftarrow', 35: r'\underleftrightarrow', 36: r'\underrightarrow', 37: r'\underleftarrow'}
PRIMES = {5: "'", 6: "''", 18: "'''"}
DELIMS = {'(': '(', ')': ')', '[': '[', ']': ']', '{': r'\{', '}': r'\}', '|': '|', 0x2016: r'\|', 0x2225: r'\|',
          0x2329: r'\langle', 0x232A: r'\rangle', 0x27E8: r'\langle', 0x27E9: r'\rangle', 0x3008: r'\langle',
          0x3009: r'\rangle', 0x230A: r'\lfloor', 0x230B: r'\rfloor', 0x2308: r'\lceil', 0x2309: r'\rceil',
          0x27E6: '[', 0x27E7: ']', 0x301A: '[', 0x301B: ']',  # crochets blancs : \llbracket refuse \left
          # Morceaux de la police Symbol (zone privée) et barres MathType.
          0xF8EB: '(', 0xF8EC: '(', 0xF8ED: '(', 0xF8F6: ')', 0xF8F7: ')', 0xF8F8: ')', 0xF8EF: '[', 0xF8FA: ']',
          0xF8F1: r'\{', 0xF8F2: r'\{', 0xF8F3: r'\{', 0xF8FC: r'\}', 0xF8FD: r'\}', 0xF8FE: r'\}',
          0xEC07: '|', 0xEC08: '|', 0xEC09: r'\|', 0xEC0A: r'\|'}


def _car_tex(c, v3):
    """Un caractère (sans gras/texte) → LaTeX."""
    code = c.code
    if v3 and 0xEB00 <= code <= 0xEB0F:  # espaces de l'Éditeur d'équations 3.0
        return {0xEB01: '', 0xEB02: r'\,', 0xEB04: r'\;', 0xEB05: r'\quad', 0xEB08: r'\,'}.get(code, r'\,')
    if code in GREC:
        return '\\' + GREC[code]
    if code in GREC_LATIN:
        return GREC_LATIN[code]
    if code in SYMBOLES:
        return SYMBOLES[code]
    if 0xF000 <= code <= 0xF033:
        return r'\mathfrak{' + _lettre(code - 0xF000) + '}'
    if 0xF080 <= code <= 0xF0B3:
        return r'\mathbb{' + _lettre(code - 0xF080) + '}'
    if 0xF0C0 <= code <= 0xF0C9:
        return r'\mathbb{' + str(code - 0xF0C0) + '}'
    if 0xF100 <= code <= 0xF133:
        return r'\mathcal{' + _lettre(code - 0xF100) + '}'
    if 0x1D400 <= code:  # alphanumériques mathématiques (rare en MTEF 16 bits)
        return ''
    ch = chr(code) if 0x20 <= code < 0xE000 else ''
    if ch == ' ':
        return ''
    return ECHAPPES.get(ch, ch)


def _lettre(i):
    return chr(ord('A') + i) if i < 26 else chr(ord('a') + i - 26)


def _texte_tex(chars):
    s = ''.join(chr(c.code) if 0x20 <= c.code < 0xE000 else ' ' for c in chars)
    s = re.sub(r'([\\{}#%&_$^~])', lambda m: {'\\': r'\textbackslash ', '~': r'\textasciitilde ', '^': r'\textasciicircum '}
               .get(m.group(1), '\\' + m.group(1)), s)
    return r'\text{' + s + '}'


class _Ecrivain:
    def __init__(self, v3):
        self.v3 = v3

    # Une ligne : suite d'objets ; les indices/exposants s'accrochent à ce qui précède.
    def ligne(self, objets):
        out = []
        i = 0
        objets = objets or []
        while i < len(objets):
            o = objets[i]
            if isinstance(o, Car):
                # Texte (police 1) et noms de fonctions (police 2) : regroupés.
                if o.police in (1, 2) and not o.embell:
                    j = i
                    while j < len(objets):
                        x = objets[j]
                        if isinstance(x, Car) and x.police == o.police and not x.embell and not (j > i and x.debut_fonction):
                            j += 1
                            continue
                        # Espaces entre deux mots du texte : dans le texte.
                        k = j
                        while o.police == 1 and k < len(objets) and isinstance(objets[k], Car) and self.espace(objets[k]):
                            k += 1
                        if k > j and k < len(objets) and isinstance(objets[k], Car) and objets[k].police == 1:
                            j = k
                            continue
                        break
                    out.append(self.mot(objets[i:j], o.police))
                    i = j
                    continue
                out.append(self.car(o))
            elif isinstance(o, Gabarit):
                out.append(self.gabarit(o))
            elif isinstance(o, Pile):
                out.append(self.pile(o))
            elif isinstance(o, Matrice):
                out.append(self.matrice(o))
            elif isinstance(o, Ligne):
                out.append(self.ligne(o.objets))
            i += 1
        return _joindre(out)

    def espace(self, c):
        return c.code in (0x20, 0xA0) or (self.v3 and 0xEB00 <= c.code <= 0xEB0F) or 0xEF01 <= c.code <= 0xEF08 \
            or 0x2002 <= c.code <= 0x200A

    def mot(self, chars, police):
        chars = [Car(0x20, c.police, []) if self.espace(c) else c for c in chars]
        s = ''.join(chr(c.code) if 0x20 <= c.code < 0xE000 else '' for c in chars)
        if police == 2:
            if s in FONCTIONS:
                return '\\' + s
            if s in FONCTIONS_FR:
                return FONCTIONS_FR[s]
            if re.fullmatch(r'[A-Za-z]+', s):
                return r'\operatorname{' + s + '}'
            return _joindre([self.car(c) for c in chars])
        if not s.strip():
            return r'\ ' if s else ''
        # Un seul symbole en police texte (« , », « ; ») : en maths.
        if len(s.strip()) == 1 and not s.strip().isalpha():
            return _joindre([self.car(c) for c in chars])
        return _texte_tex(chars)

    def car(self, c):
        t = _car_tex(c, self.v3)
        if c.police == 7 and re.fullmatch(r'[A-Za-z0-9]', t or ''):  # vecteurs-matrices : gras
            t = r'\mathbf{' + t + '}'
        for e in c.embell:
            if e in PRIMES:
                t = t + PRIMES[e]
            elif e == 10:
                t = r'\not ' + t
            elif e in (16, 21, 22, 23):
                t = r'\cancel{' + t + '}'
            elif e in EMBELLS:
                t = EMBELLS[e] + '{' + t + '}'
        return t

    def bloc(self, o):
        if o is None:
            return ''
        if isinstance(o, Ligne):
            return self.ligne(o.objets)
        if isinstance(o, Pile):
            return self.pile(o)
        if isinstance(o, Car):
            return self.car(o)
        return self.ligne([o])

    def pile(self, p):
        lignes = [self.ligne(x.objets) if isinstance(x, Ligne) else self.pile(x) for x in p.lignes]
        if len(lignes) == 1:
            return lignes[0]
        marques = any(_a_marque(x) for x in p.lignes)
        if p.halign == 4 or marques:
            corps = r' \\ '.join(_aligner(x, lt) for x, lt in zip(p.lignes, lignes))
            return r'\begin{aligned}' + corps + r'\end{aligned}'
        col = {1: 'l', 3: 'r'}.get(p.halign, 'c')
        return r'\begin{array}{' + col + '}' + r' \\ '.join(lignes) + r'\end{array}'

    def matrice(self, m):
        cases = [self.bloc(c) for c in m.cases]
        rangs = []
        for i in range(m.lignes):
            rangs.append(' & '.join(cases[i * m.colonnes:(i + 1) * m.colonnes]))
        if not any(m.traits_l) and not any(m.traits_c):
            return r'\begin{matrix}' + r' \\ '.join(rangs) + r'\end{matrix}'
        tc = (m.traits_c + [0] * (m.colonnes + 1))[:m.colonnes + 1]
        spec = ''.join(('|' if tc[i] else '') + 'c' for i in range(m.colonnes)) + ('|' if tc[m.colonnes] else '')
        tl = (m.traits_l + [0] * (m.lignes + 1))[:m.lignes + 1]
        corps = ''
        for i, rg in enumerate(rangs):
            corps += (r'\hline ' if tl[i] else '') + rg + (r' \\ ' if i < len(rangs) - 1 or tl[m.lignes] else '')
        if tl[m.lignes]:
            corps += r'\hline'
        return r'\begin{array}{' + spec + '}' + corps + r'\end{array}'

    # Gabarits : chaque classe a ses emplacements (lignes) puis, parfois, ses caractères (parenthèses, ∑…).
    def gabarit(self, g):
        lignes = [x for x in g.sous if isinstance(x, (Ligne, Pile))]
        cars = [x for x in g.sous if isinstance(x, Car)]
        L = [self.bloc(x) for x in lignes]
        def l(i):  # noqa: E743
            return L[i] if i < len(L) else ''
        sel, v = (g.selecteur, g.variation)
        self._sel = sel
        sorte = _sorte(sel, v, self.v3)
        if sorte == 'fence':
            return self.clotures(g, cars, l(0), sel, v)
        if sorte == 'root':
            return r'\sqrt[' + l(1) + ']{' + l(0) + '}' if l(1) else r'\sqrt{' + l(0) + '}'
        if sorte == 'frac':
            return '{' + l(0) + '}/{' + l(1) + '}' if self._barre_oblique(sel, v) else r'\frac{' + l(0) + '}{' + l(1) + '}'
        if sorte == 'ubar':
            return r'\underline{' + l(0) + '}'
        if sorte == 'obar':
            return r'\overline{' + l(0) + '}'
        if sorte == 'arrow':
            fl = _fleche(sel, v, self.v3)
            return fl + ('[' + l(1) + ']' if l(1) else '') + '{' + l(0) + '}'
        if sorte in ('bigop', 'integ'):
            op = _joindre([self.car(c) for c in cars]) if cars else (r'\int' if sorte == 'integ' else r'\sum')
            bas, haut = l(1), l(2)
            limites = (r'\limits' if sorte == 'bigop' and op.startswith(r'\int') else '')
            return op + limites + ('_{' + bas + '}' if bas else '') + ('^{' + haut + '}' if haut else '') + ' ' + l(0)
        if sorte == 'lim':
            return l(0) + ('_{' + l(1) + '}' if l(1) else '') + ('^{' + l(2) + '}' if l(2) else '')
        if sorte == 'hbrace':
            haut = (v & 1) if not self.v3 else sel == 27
            return (r'\overbrace{' + l(0) + '}^{' + l(1) + '}') if haut else (r'\underbrace{' + l(0) + '}_{' + l(1) + '}')
        if sorte in ('sub', 'sup', 'subsup'):
            return self.scripts(sorte, lignes, v)
        if sorte == 'dirac':
            return r'\left\langle ' + r' \middle| '.join(x for x in L if x) + r' \right\rangle'
        if sorte == 'vec':
            gauche, droite = (v & 1), (v & 2)
            if self.v3:
                gauche, droite = sel == 46 and v == 0, not (sel == 46 and v == 0)
            cmd = r'\overleftrightarrow' if gauche and droite else r'\overleftarrow' if gauche else r'\overrightarrow'
            if not self.v3 and v & 4:
                cmd = cmd.replace('over', 'under')
            return cmd + '{' + l(0) + '}'
        if sorte == 'tilde':
            return r'\widetilde{' + l(0) + '}'
        if sorte == 'hat':
            return r'\widehat{' + l(0) + '}'
        if sorte == 'arc':
            return r'\overgroup{' + l(0) + '}'
        if sorte == 'strike':
            return r'\cancel{' + l(0) + '}'
        if sorte == 'box':
            return r'\boxed{' + l(0) + '}'
        return _joindre([x for x in L if x])

    def _barre_oblique(self, sel, v):
        return sel == 41 if self.v3 else bool(v & 2)

    def scripts(self, sorte, lignes, v):
        bas = self.bloc(lignes[0]) if len(lignes) > 0 else ''
        haut = self.bloc(lignes[1]) if len(lignes) > 1 else ''
        if len(lignes) == 1 and sorte == 'sup':
            bas, haut = '', self.bloc(lignes[0])
        s = ('_{' + bas + '}' if bas else '') + ('^{' + haut + '}' if haut else '')
        if not s:
            return ''
        avant = (self._sel == 44) if self.v3 else bool(v & 1)
        return '{}' + s if avant else _SCRIPT + s

    def clotures(self, g, cars, contenu, sel, v):
        defaut = {0: ('<', '>'), 1: ('(', ')'), 2: ('{', '}'), 3: ('[', ']'), 4: ('|', '|'), 5: (0x2016, 0x2016),
                  6: (0x230A, 0x230B), 7: (0x2308, 0x2309), 8: ('[', ']')}
        if self.v3:
            gauche_la, droite_la = (v in (0, 1)) if sel <= 5 else True, (v in (0, 2)) if sel <= 5 else True
        else:
            gauche_la, droite_la = (bool(v & 1), bool(v & 2)) if sel <= 8 else (True, True)
        dg, dd0 = defaut.get(sel if sel <= 8 else 1, ('(', ')'))
        dg, dd0 = DELIMS.get(dg, dg), DELIMS.get(dd0, dd0)
        if sel in (6, 7):  # plancher, plafond : les morceaux de crochets ne disent pas lequel
            cars = []
        g_car = cars[0] if cars and gauche_la else None
        d_car = cars[-1] if cars and droite_la and (len(cars) > 1 or not gauche_la) else None
        gd = (_delim(g_car) if g_car else '.') if gauche_la else '.'
        dd = (_delim(d_car) if d_car else '.') if droite_la else '.'
        if gauche_la and gd == '.':
            gd = dg
        if droite_la and dd == '.':
            dd = dd0
        return r'\left' + _sep(gd) + contenu + r'\right' + _sep(dd)


_SCRIPT = '\x00SCRIPT\x00'


def _delim(c):
    if c.code in DELIMS:
        return DELIMS[c.code]
    ch = chr(c.code) if 0x20 <= c.code < 0xE000 else ''
    return DELIMS.get(ch, '.') if ch else '.'


def _sep(d):
    return d if not d[-1:].isalpha() else d + ' '


def _sorte(sel, v, v3):
    if v3:
        if sel <= 12:
            return 'fence'
        return {13: 'root', 14: 'frac', 16: 'ubar', 17: 'obar', 18: 'arrow', 19: 'arrow', 20: 'arrow', 27: 'hbrace',
                28: 'hbrace', 39: 'lim', 40: 'ldiv', 41: 'frac', 45: 'dirac', 46: 'vec', 47: 'vec', 48: 'box',
                15: {0: 'sup', 1: 'sub', 2: 'subsup'}.get(v, 'subsup'), 44: {0: 'sup', 1: 'sub', 2: 'subsup'}.get(v, 'subsup'),
                }.get(sel, 'integ' if 21 <= sel <= 26 else 'bigop' if 29 <= sel <= 38 or sel in (42, 43) else '')
    if sel <= 9:
        return 'fence'
    return {10: 'root', 11: 'frac', 12: 'ubar', 13: 'obar', 14: 'arrow', 15: 'integ', 23: 'lim', 24: 'hbrace',
            25: 'hbrace', 26: 'ldiv', 27: 'sub', 28: 'sup', 29: 'subsup', 30: 'dirac', 31: 'vec', 32: 'tilde',
            33: 'hat', 34: 'arc', 35: 'jstatus', 36: 'strike', 37: 'box'}.get(sel, 'bigop' if 16 <= sel <= 22 else '')


def _fleche(sel, v, v3):
    if v3:
        return {18: r'\xleftarrow', 19: r'\xrightarrow', 20: r'\xleftrightarrow'}[sel]
    if v & 1:
        return r'\xLeftrightarrow'
    if v & 2:
        return r'\xrightleftharpoons'
    gauche, droite = bool(v & 0x10), bool(v & 0x20)
    return r'\xleftarrow' if gauche and not droite else r'\xleftrightarrow' if gauche and droite else r'\xrightarrow'


def _a_marque(x):
    return isinstance(x, Ligne) and any(isinstance(o, Car) and o.code == 0xEF00 for o in (x.objets or []))


RELATIONS = re.compile(r'(=|<|>|\\leqslant|\\geqslant|\\neq|\\approx|\\equiv|\\Leftrightarrow|\\Rightarrow|\\in\b)')


def _aligner(x, tex):
    """Ligne d'un calcul aligné : « & » à la marque d'alignement, sinon devant la première relation."""
    if '&' in tex:
        return tex
    m = RELATIONS.search(tex)
    return tex[:m.start()] + '&' + tex[m.start():] if m else tex


def _joindre(morceaux):
    out = ''
    for m in morceaux:
        if not m:
            continue
        if m.startswith(_SCRIPT):
            m = m[len(_SCRIPT):]
            if not out or out.endswith((' ', '{', '&', '(')):
                out += '{}'
            out += m
            continue
        if out and re.search(r'\\[A-Za-z]+$', out) and re.match(r'[A-Za-z0-9]', m):
            out += ' '
        out += m
    return out


def mtef_vers_latex(data):
    version, objets = lire_mtef(data)
    v3 = version == 3
    e = _Ecrivain(v3)
    tex = e.ligne(objets).strip()
    tex = re.sub(r'(?<=\d),(?=\d)', '{,}', tex)       # virgule décimale
    tex = re.sub(r'\\int\s*\\int\s*\\int(?![a-z])', r'\\iiint', tex)
    tex = re.sub(r'\\int\s*\\int(?![a-z])', r'\\iint', tex)
    tex = re.sub(r'\s+', ' ', tex).replace('\x00', '')
    return tex


def ole_vers_latex(octets):
    """oleObjectN.bin d'un document Word → LaTeX (MathTypeErreur si ce n'est pas une formule lisible)."""
    tex = mtef_vers_latex(mtef_de_ole(octets))
    if not tex:
        raise MathTypeErreur('formule vide')
    return tex
