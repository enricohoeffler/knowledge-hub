# Knowledge Hub – lokaler MkDocs-Prototyp

**Ausschließlich für synthetische Testdaten. Nicht produktionsbereit und nicht auf produktivem Home Assistant installieren.** Lokal startet das Programm nur mit `KH_SYNTHETIC_ONLY=yes`. Die standardmäßig ausgeschaltete HA-Testoption startet mit flüchtigen Beispieldaten; die App-Konfiguration ist ein Entwurf und nicht unter echtem Ingress geprüft. Die aktuelle Implementierung erfüllt noch nicht die geforderte Schutz- und Konfliktgrenze für echte Daten.

Die MkDocs-Konfiguration und Material-Version basieren auf dem [MkDocs-Add-on von Xavier Berger](https://github.com/XavierBerger/home-assistant-addons/tree/main/mkdocs), Stand Commit `8fff197aad0669d47b9b3fb573a9af58d16931b1`, Add-on-Version 1.1.6. Lizenz und Urheberhinweis: [UPSTREAM-LICENSE.md](knowledge_hub/UPSTREAM-LICENSE.md). Übernommen und angepasst sind Material-Theme, ausgewählte Markdown-Erweiterungen und das Ingress-App-Grundkonzept. Der Editor, die Positivliste und der Build-Schutz sind eigenständige Prototypen; der ursprüngliche Add-on-Laufzeitserver wurde nicht übernommen. Das Original veröffentlicht einen Vorschau-Port und verwendet eine externe PlantUML-Adresse; beides ist hier nicht eingerichtet. Weitere Plugins des Originals, die ausführbare Makros oder externen Datenverkehr ermöglichen können, sind nicht aktiviert.

## Architektur

Eine explizite Liste einzelner Dateipfade (`policy.json`) gilt für Editor und Build. Neue Dateien sind nicht automatisch freigegeben. Der Build kopiert ausschließlich Dateien aus dieser Liste in ein kurzlebiges temporäres Verzeichnis, führt MkDocs dort aus und übernimmt eine erzeugte Website erst nach erfolgreichem Build, Vollständigkeitsprüfung und erneutem Vergleich der Quelldateien. Der Server liefert ausschließlich die Dateien des erfolgreichen Builds aus dem Speicher aus; er stellt weder das Quellverzeichnis noch das Projektverzeichnis statisch bereit. Die gleiche Liste begrenzt die API zum Öffnen und Speichern. Die Testansicht zeigt die Buildzeit und einen einfachen Markdown-Editor.

```text
synthetische Quelle ── Positivliste ──┬─ temporäre Build-Eingabe ─ MkDocs ─ Website im Speicher
                                      └─ Editor-API ─ Hash-Vergleich ─ Quelldatei
```

Die Dateiliste wird beim Start eingelesen. Eine Änderung erfordert Neustart; eine zur Laufzeit widerrufene Freigabe wird sonst nicht wirksam. Die Zwischendateien werden nach einem regulären Build entfernt; bei Prozessabsturz können temporäre Dateien zurückbleiben. Website, Suchindex und letzte Sicherungen liegen im Arbeitsspeicher; Browser können Inhalte trotz `Cache-Control: no-store` bereits gespeichert oder heruntergeladen haben. Eine Freigabe lässt sich dort nicht rückwirkend zurücknehmen. Beim Ausfall einer ausgewählten Datei verweigert die App nach der nächsten Prüfung die Website; Erkennung erfolgt im Prototyp alle fünf Sekunden. Alte Inhalte können bis dahin und in Browsern verbleiben.

Die Eingrenzung verhindert nicht, dass freigegebene Seiten, Übersichten, Logs oder Anhänge bereits Inhalte gesperrter Dateien enthalten. Private und gemeinsame Wissensbereiche brauchen getrennte Quellen, Dienstkonten, Konfigurationen und Instanzen. Ein für den Generator austauschbarer Einstieg liegt in `build()`; eine Zensical-Integration existiert noch nicht.

## Lokal ausprobieren (Windows PowerShell)

Voraussetzungen: Docker Desktop und Zugriff auf die Docker-Engine. Das Image lädt öffentliche Python-Pakete; Laufzeit und Tests benötigen keine externen Dienste. Der folgende Befehl überschreibt keine bestehenden Daten: Zum Wiederholen einen neuen Testordnernamen verwenden. Nur diese synthetische Kopie bearbeiten.

```powershell
docker build -t knowledge-hub-prototype:local .\knowledge_hub
New-Item -ItemType Directory .test-data\demo-run
Copy-Item -Recurse .\demo\source .test-data\demo-run\source
Copy-Item .\demo\policy.json .test-data\demo-run\policy.json
$testDir = (Resolve-Path .test-data\demo-run).Path
docker run --rm --name knowledge-hub-demo -p 127.0.0.1:18099:8099 `
  --mount "type=bind,source=$testDir,target=/demo" `
  -e KH_SYNTHETIC_ONLY=yes -e KH_ROOT=/demo/source -e KH_POLICY=/demo/policy.json `
  -e HOST=0.0.0.0 knowledge-hub-prototype:local
```

Öffne `http://127.0.0.1:18099/`; beende den Container mit Strg+C. Der Port ist für diesen lokalen Versuch ausschließlich an Loopback gebunden. Das Image standardmäßig ohne die explizite Testvariable zu starten scheitert absichtlich. Eine bereits existierende `.test-data/demo-run` vorher nicht überschreiben; für einen neuen Lauf einen anderen Namen wählen.

Automatisierte Prüfungen ohne Containernetzwerk:

```powershell
docker build -t knowledge-hub-prototype:local .\knowledge_hub
docker run --rm --network none --mount "type=bind,source=$((Get-Location).Path)\tests,target=/tests,readonly" knowledge-hub-prototype:local python /tests/test_prototype.py
```

Die Editorlogik lässt sich mit installiertem Node.js separat prüfen:

```powershell
node tests/test_editor.mjs
```

Der Test führt das tatsächliche Client-Skript in einer simulierten DOM- und API-Umgebung aus. Er prüft Seitenwechsel nach dem Speichern, Erhalt ungespeicherter Entwürfe, die Sperre gegen Speichern auf einer anderen Seite und Eingaben während verzögerter Lade- und Speichervorgänge. Er ersetzt keinen interaktiven Browsertest.

## Tatsächlich geprüft

Am 22.11.2026: Docker Desktop unter Windows; Python 3.12 im Container, MkDocs 1.6.1, Material 9.8.1 und Python-Markdown 3.11.3. Alle acht automatisierten Testgruppen mit synthetischen Dateien bestanden:

- Freigegebene Dateien im Build und eine Markdown-Tabelle; ausgeschlossene und neu angelegte Dateien fehlen im Suchindex und sind über getestete direkte Website- und API-Pfade nicht abrufbar. Ein freigegebenes Linkziel ist erreichbar, das ausgeschlossene Ziel gibt 404 zurück. Traversal-Versuche und ein symbolischer Link auf eine ausgeschlossene Datei wurden abgewiesen.
- Öffnen und Speichern per API, Erhalt des Test-Frontmatters und des relativen Links, Ablehnung eines alten Hashes nach zwischenzeitlicher Änderung und Wiederherstellen des Testinhalts aus der flüchtigen Sicherung.
- Zwei gleichzeitig gestartete API-Schreibvorgänge auf derselben Revision führten zu einem Erfolg und einem Konflikt. Das prüft nur die prozessinterne Serialisierung.
- Eine externe Dateiänderung erscheint nach explizitem Aktualisierungslauf in der Website; ein künstlicher Buildfehler behält die letzte vollständige Fassung. Das testet nicht die echte SMB-Benachrichtigung.
- Das vorübergehende Entfernen einer ausgewählten Testdatei führt nach erneuter Prüfung zu HTTP 503; nach Wiederherstellung ist die Ansicht wieder erreichbar. Das simuliert nur einen Fehler und keine tatsächliche SMB-Trennung oder Mount-Identität.
- Verschwindet eine Datei während des Builds, wird die Website ebenfalls gesperrt und nach Wiederherstellung wieder verfügbar.
- Die Ingress-Quellprüfung wurde isoliert und die Abweisung einer direkten Verbindung im Container geprüft; ein echter Supervisor-Test steht aus.

Diese API- und Prozessprüfungen sind kein umfassender Sicherheitstest. Nicht geprüft: Browserbedienung und visuelle Darstellung, Bilder, Mermaid, Suche per UI, Konfliktkopien bei mehreren Browsern, echte parallele SMB-Schreiber, tatsächlicher Netzwerkausfall, Home Assistant Ingress oder externe Erreichbarkeit.

## Bekannte Grenzen vor Produktivbetrieb

- **Sicherheit:** Im synthetischen HA-Testmodus prüft der Server die TCP-Quelladresse des Ingress-Proxys; echte Ingress-Authentifizierung und CSRF sind nicht geprüft. Die aktuelle HTML-Ausgabe kann aktives HTML aus Markdown enthalten; das iframe mit `allow-scripts` und `allow-same-origin` ist keine Sicherheitsgrenze. Symlink-Prüfung ist anfällig für Änderungen zwischen Prüfung und Öffnen. Der Testserver ist nicht gehärtet. Zusätzlich sind Anhänge nach Typ und Inhalt zu begrenzen und alle Endpunkte, Traversal-Varianten sowie Suchindex und Caches umfassend zu prüfen. Daher keine echten Inhalte oder Freigaben einbinden.
- **Konflikte:** Der Hash-Vergleich und das anschließende Ersetzen sind gegenüber externen Prozessen nicht atomar. Eine konkurrierende Änderung zwischen Vergleich und Ersetzen kann verloren gehen; SMB-Locks/CAS müssten mit allen beteiligten Schreibern nachweislich zusammenwirken. Im Prozess selbst serialisiert ein Lock die API-Schreibvorgänge. Bei erkanntem Konflikt bleibt der Entwurf im geöffneten Editor; es gibt keine dauerhafte Konfliktkopie. Bei geschlossenem Browser oder Absturz kann er verloren gehen. Ein Netzwerkabbruch nach dem Absenden kann den Schreibausgang unklar lassen.
- **Sicherungen:** Die jeweils letzte vorherige Fassung liegt nur bis zum Prozessende im Speicher; die Schaltfläche lädt sie in den Editor, ein anschließendes Speichern prüft erneut den Hash. Das ist ein Versuch und kein Backup. Unabhängige versionierte Sicherungen und echte Restore-Tests sind erforderlich. Die im Wiki beschriebenen bidirektionalen Synchronisationen ohne Versionierung können Löschungen weitertragen. Git-Revisionsfunktionen nicht ohne Prüfung im bestehenden Repository aktivieren.
- **Darstellung:** Tabellen und normale relative Markdown-Links werden im Beispiel verarbeitet. Für fehlende/gesperrte Ziele liefert der Server einen generischen Hinweis. Links außerhalb der eingebundenen Quelle können nicht automatisch funktionieren. Mermaid ist nicht eingerichtet; Diagramme bleiben Codeblöcke. Bilder und andere Anhänge müssen einzeln freigegeben und praktisch geprüft werden. Der Editor erhält die unveränderte Textfassung, formatiert aber nicht automatisch. Änderungen an Metadaten erfolgen, wenn sie im Text bearbeitet werden.
- **SMB:** Ein Verzeichnis oder eine Sentinel-Datei allein beweist keinen aktiven richtigen CIFS-Mount. Der Prototyp hat keine Mount-Identitätsprüfung und kein sicheres Reconnect-Verfahren. Vor Produktivbetrieb müssen Mounttyp, erwartete Quelle und Zugriff auf jedem relevanten Pfad fail-closed geprüft und echte Trennung, Wiederverbindung sowie Schreibfehler getestet werden.
- **HA:** `config.yaml` und der synthetische Testmodus sind nicht unter echtem Ingress geprüft und nicht für produktiven Betrieb konfiguriert. Es wurden keine produktiven Einstellungen verändert.

## Geplante SMB- und HA-Einrichtung

HAOS kann SMB als Netzwerkspeicher mit Verwendung „Share“ unter `/share/<Name>` einbinden. Server, Share, Benutzer und Passwort werden dort konfiguriert; das Unterverzeichnis benötigt zusätzliche sichere Auswahl. Die Freigabe ist auch anderen berechtigten HA-Komponenten zugänglich, daher ein dediziertes Konto mit möglichst engen Serverberechtigungen verwenden. Geheimnisse nicht im Repository oder in Logs speichern; bei Rotation neues Passwort am Server setzen, in HA aktualisieren, Verbindung prüfen und altes Passwort widerrufen. HA-Konfigurationsbackups entsprechend schützen. Startreihenfolge: Dateiserver → HA-Netzwerkspeicher → verifizierter Mount → App; bei Ausfall Schreibzugriffe unterbinden und Wiederanlauf überprüfen. Änderungen an produktiven Berechtigungen erfordern die ausdrückliche Freigabe des Nutzers.

Home Assistant dokumentiert Ingress-Authentifizierung und verlangt, Verbindungen nur vom Ingress-Proxy zu akzeptieren. Es darf kein zusätzlicher Host-Port veröffentlicht werden. Pfadpräfix, Proxy-Quellprüfung, Authentifizierung, Browserverhalten und alle Wege zu generierten Dateien müssen auf der konkreten HA-Version getestet werden.

## Dokumentation und Versionen

- [MkDocs-Konfiguration](https://www.mkdocs.org/user-guide/configuration/) und [Bereitstellung](https://www.mkdocs.org/user-guide/deploying-your-docs/). Ein Navigationsfilter ist keine Dateizugriffskontrolle.
- [HA-Netzwerkspeicher](https://www.home-assistant.io/common-tasks/os/#network-storage), [Ingress-Sicherheit](https://developers.home-assistant.io/docs/apps/presentation/), [App-Konfiguration](https://developers.home-assistant.io/docs/apps/configuration/).
- [Zensical: Wartungsende von Material for MkDocs](https://zensical.org/upcoming-changes/): kritische Wartung bis 05.05.2027. Der Prototyp verwendet Material 9.8.1; eine spätere Migration ist noch offen.
- Der MkDocs-Generator ist auf 1.6.1 festgelegt; transitive Abhängigkeiten und Python-Image-Digest sind noch nicht vollständig fixiert. Vor produktivem Einsatz reproduzierbar fixieren und Sicherheitsupdates prüfen.
