# Deploy AutoStorico API su Render

## 1. Carica il progetto

Carica questi file su un repository GitHub oppure su Render tramite progetto collegato:

- `server.py`
- `requirements.txt`
- `Procfile`
- `render.yaml`

## 2. Crea Web Service

Su Render:

1. New
2. Web Service
3. Runtime: Python
4. Build command:

```text
pip install -r requirements.txt
```
5. Start command:

```text
python server.py
```

## 3. Variabili ambiente

Imposta:

```text
AUTOSTORICO_API_KEY=una_chiave_lunga_segreta
AUTOSTORICO_API_HOST=0.0.0.0
```

Non impostare `PORT`: Render la fornisce automaticamente.

## 4. Verifica sicura Premium Google Play

Per vendere il piano `premium_6_mesi` aggiungi su Render queste variabili:

```text
AUTOSTORICO_PREMIUM_API_KEY=una_seconda_chiave_lunga_segreta
GOOGLE_PLAY_PACKAGE_NAME=autostorico.myapp
GOOGLE_PLAY_SUBSCRIPTION_ID=premium_6_mesi
GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID=defects_gold
GOOGLE_PLAY_SERVICE_ACCOUNT_FILE=/etc/secrets/google-play-service-account.json
```

La service account deve avere l'accesso alla Google Play Developer API per l'app
`autostorico.myapp`. Carica il suo JSON come Secret File di Render con nome
`google-play-service-account.json`; non inserirlo mai nel repository GitHub.

Premium viene verificato con l'endpoint Google Play subscriptions. La card
`defects_gold`, essendo un acquisto una tantum, viene verificata con l'endpoint
Google Play products.

Compila l'app con:

```powershell
flutter build appbundle --release `
  --dart-define=ENTITLEMENT_API_URL=https://NOME-SERVIZIO.onrender.com/api/premium/verify `
  --dart-define=ENTITLEMENT_API_KEY=la_stessa_seconda_chiave_lunga_segreta
```

## 5. Test API

Apri:

```text
https://NOME-SERVIZIO.onrender.com/health
```

Deve rispondere:

```json
{"ok": true, "service": "autostorico-value-api"}
```

## 5. Dominio

Su Render aggiungi custom domain:

```text
api.autostorico.it
```

Poi nel pannello DNS del dominio crea il record indicato da Render.

Di solito sara un `CNAME` tipo:

```text
api -> NOME-SERVIZIO.onrender.com
```

Aspetta la verifica SSL. Quando Render segna il dominio come verificato, l'API finale sara:

```text
https://api.autostorico.it/api/vehicle-value
```

## 6. Build AAB finale

Quando il dominio funziona:

```powershell
flutter build appbundle --release `
  --dart-define=AUTOSTORICO_VALUE_API_URL=https://api.autostorico.it/api/vehicle-value `
  --dart-define=AUTOSTORICO_VALUE_API_KEY=una_chiave_lunga_segreta
```

Per Google Play si carica il file:

```text
build/app/outputs/bundle/release/app-release.aab
```
