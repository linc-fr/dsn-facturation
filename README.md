# DSN Facturation

Outil web standalone : déposer un fichier DSN, obtenir le détail des bulletins facturables (entrées, sorties, absences nommées) et un score de complexité de la paie.

Ciblé pour les gestionnaires de paie indépendants et les cabinets qui facturent au bulletin et à l'événement. Extrait depuis [DSNreader](../DSNreader/) (onglet *Tracking gestionnaire*) pour en faire un produit autonome.

## Architecture

- `dsn_extractor/` : parser DSN déterministe + modèles Pydantic (copie de DSNreader, à garder synchronisé manuellement)
- `server/` : API FastAPI (POST `/api/extract`) + UI statique focalisée sur le tracking facturation

## Lancer en local

```bash
pip install -e ".[server]"
uvicorn server.app:app --reload
```

Puis http://localhost:8000

## Origine

Extrait de [DSNreader](../DSNreader/) le 2026-04-14, commit source de référence : `0b0dac3`.
