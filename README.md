# Knowledge Hub

Knowledge Hub ist eine Home-Assistant-App für die Darstellung und Bearbeitung von Markdown-Dateien. MkDocs erzeugt die Leseansicht; der integrierte Editor schreibt auf eine direkt konfigurierte SMB-Testfreigabe. Die Anwendung ist weiterhin eine Testversion für entbehrliche Beispieldaten: Die Versionsnummer 1.0.0 bestätigt keine abgeschlossene Sicherheits- oder Produktivfreigabe.

## Einrichtung und Nutzung

Die App wird über dieses Repository in Home Assistant installiert und per Ingress geöffnet. In der App-Konfiguration entweder den flüchtigen synthetischen Test oder eine separate SMB-Testfreigabe aktivieren und deren Server, Freigabe, Zugangsdaten und optionalen Unterordner eintragen. Die App bindet `/share` nicht ein; die SMB-Rechte des verwendeten Kontos sind die tatsächliche Zugriffsgrenze. Details, Ausschlussliste und Grenzen stehen in der [App-Dokumentation](knowledge_hub/DOCS.md).

Markdown-Dateien und unterstützte Bilder sind im SMB-Testmodus standardmäßig sichtbar, sofern sie nicht ausgeschlossen sind. Über die Minus-Schaltflächen neben „Bearbeiten“ lassen sich die aktuelle Datei oder ihr Ordner ausblenden; das Wiederanzeigen erfolgt in der App-Konfiguration. Neue Dateien werden automatisch aufgenommen. Die Oberfläche folgt dem Home-Assistant-Farbschema.

Der Editor prüft die Revision vor dem Speichern und aktualisiert anschließend die Leseansicht. Die Prüfung ist gegenüber externen SMB-Schreibern nicht atomar; paralleles Schreiben kann Änderungen verlieren. Sicherungen im Editor sind flüchtig. SMB-Ausfall und Wiederverbindung, parallele externe Schreiber, CSRF und aktives HTML sind nicht vollständig geprüft. Separate Sicherungen verwenden und nur mit Testkopien arbeiten.

## Tests

```powershell
node tests/test_editor.mjs
docker build -t knowledge-hub-prototype:local .\knowledge_hub
docker run --rm --network none -e PYTHONPATH=/app --mount "type=bind,source=$((Get-Location).Path)\tests,target=/tests,readonly" knowledge-hub-prototype:local python /tests/test_prototype.py
docker run --rm --network none -e PYTHONPATH=/app --mount "type=bind,source=$((Get-Location).Path)\tests,target=/tests,readonly" knowledge-hub-prototype:local python /tests/test_launcher_options.py
```

Weitere Tests in `tests/` benötigen einen isolierten Samba-Server mit synthetischen Daten. Die lokale Demo und ihre Policy dienen weiterhin zum Testen des lokalen Prototyps; im SMB-Modus verwendet die App eine Ausschlussliste.

## Herkunft

Die MkDocs-Konfiguration und das Material-Theme basieren auf dem [MkDocs-Add-on von Xavier Berger](https://github.com/XavierBerger/home-assistant-addons/tree/main/mkdocs), Commit `8fff197aad0669d47b9b3fb573a9af58d16931b1`. Lizenz und Urheberhinweis stehen in [UPSTREAM-LICENSE.md](knowledge_hub/UPSTREAM-LICENSE.md). Editor und SMB-Anbindung sind eigenständige Entwicklungen.
