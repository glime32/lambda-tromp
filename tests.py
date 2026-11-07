#!/usr/bin/env python3
"""Vérifie les calculs, et que les deux moteurs (pas à pas et NbE) trouvent la même forme normale."""
import importlib.util
import os

ici = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("lam", os.path.join(ici, "lambda.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

s = L.Session()
s.charge(os.path.join(ici, "prelude.lam"))
cas = {"PLUS 2 3": 5, "FOIS 3 4": 12, "PUISS 2 5": 32, "PUISS 3 2": 9, "PRED 0": 0, "PRED 7": 6,
       "MOINS 9 4": 5, "MOINS 2 5": 0, "FACT 0": 1, "FACT 4": 24, "FIB 7": 13, "SOMME_JUSQUA 10": 55,
       "SOMME (CARTE (FOIS 3) (CONS 1 (CONS 2 NIL)))": 9, "LONGUEUR NIL": 0, "SECOND (PAIRE 1 2)": 2,
       "SI (ET VRAI (NON FAUX)) 7 8": 7, "SI (OU FAUX FAUX) 7 8": 8, "SI (EGAL? 4 4) 1 0": 1}
ok = 0
for expr, attendu in cas.items():
    t = s.lit(expr)
    pas, n = s.normalise(t)
    vite = L.normalise_vite(t)
    bon = L.lit_entier(pas) == attendu and pas == vite
    ok += bon
    print(f"  {'ok   ' if bon else 'ÉCHEC'} {expr} = {L.lit_entier(pas)} ({n} étapes)")
bon = s.lit("S K K") == s.lit("S K K") and s.normalise(s.lit("S K K"))[0] == s.lit("I")
ok += bon
print(f"  {'ok   ' if bon else 'ÉCHEC'} S K K = I")
try:
    L.normalise_vite(s.lit("OMEGA"), carburant=100_000)
    print("  ÉCHEC OMEGA devrait boucler")
except RuntimeError:
    ok += 1
    print("  ok    OMEGA n'a pas de forme normale (détecté)")
total = len(cas) + 2
print(f"{ok} / {total}")
raise SystemExit(ok != total)
