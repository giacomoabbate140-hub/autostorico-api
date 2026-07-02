# AutoStorico API

API locale per stimare il valore del veicolo.

## Avvio locale

```powershell
$env:AUTOSTORICO_API_KEY="autostorico-test-key"
$env:AUTOSTORICO_API_PORT="8088"
C:\Users\giaco\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe server.py
```

## Endpoint

`POST /api/vehicle-value`

Header:

```text
Authorization: Bearer autostorico-test-key
Content-Type: application/json
```

Body esempio:

```json
{
  "plate": "EH032KE",
  "vehicleType": "Auto",
  "brand": "Audi",
  "model": "A1",
  "km": 172300,
  "firstRegistrationDate": "2016-01-01",
  "revisionHistoryCount": 4,
  "insuranceHistoryCount": 1,
  "taxHistoryCount": 1,
  "worksTotal": 0,
  "documentsCount": 0
}
```

Risposta:

```json
{
  "estimate": {
    "minValue": 5200,
    "averageValue": 6100,
    "maxValue": 7000,
    "confidence": "Alta: dati completi ricevuti dall'app.",
    "method": "API AutoStorico..."
  }
}
```

## Build app collegata all'API

Quando l'API è online:

```powershell
flutter build apk --release `
  --dart-define=AUTOSTORICO_VALUE_API_URL=https://tuodominio.it/api/vehicle-value `
  --dart-define=AUTOSTORICO_VALUE_API_KEY=autostorico-test-key
```

Per test sul telefono in Wi-Fi locale, sostituire `tuodominio.it` con l'IP del PC, per esempio:

```text
http://192.168.1.50:8088/api/vehicle-value
```
