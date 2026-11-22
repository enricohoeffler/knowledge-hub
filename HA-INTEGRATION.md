# Vorbereitung für Home Assistant

Stand: 22.11.2026. Der Knowledge Hub ist ein Prototyp für synthetische Daten und darf in der vorliegenden Form nicht auf der produktiven Home-Assistant-Installation installiert werden.

## Festgestellter Stand

- Die erreichbare Installation meldet Home Assistant Core 2026.11.2. Der Supervisor antwortet; in der Liste installierter Apps ist kein Knowledge Hub enthalten.
- `knowledge_hub/config.yaml` beschreibt eine App mit Ingress auf Port 8099; der zuvor vorgesehene schreibende Zugriff auf `share` wurde entfernt. Die Datei ist ein Entwurf, keine getestete Installationskonfiguration. Ohne ausdrückliche Testoption oder lokale Testvariable beendet sich das Image absichtlich beim Start. Die standardmäßig ausgeschaltete Option `synthetic_ha_test` startet mit einer flüchtigen Kopie eingebauter Beispieldaten und bindet an alle Containerinterfaces.
- Die Browseroberfläche verwendet relative URLs für API und Website; der Server verarbeitet die vom Proxy weitergeleiteten Pfade. Ob dies unter dem tatsächlichen Ingress-Präfix einschließlich Suche und Navigation funktioniert, ist nicht nachgewiesen. Im synthetischen HA-Testmodus prüft der Server die TCP-Quelladresse auf `172.30.32.2`; eine Prüfung unter echtem Supervisor steht aus. CSRF und aktive Inhalte sind nicht ausreichend abgesichert.
- Eine spätere schreibende Einbindung von `/share` würde den Zugriff der App über die ausgewählten Testdateien hinaus erweitern. Die Positivliste ist keine ausreichende Betriebssicherheitsgrenze. Eine produktive SMB-Quelle darf nicht verbunden werden, solange Mount-Identität, Ausfallsicherheit, Zugriff und konkurrierende Schreibvorgänge nicht nachgewiesen sind.

## Abgleich mit den installierten Monitor-Apps

Elternportal Monitor 0.2.3 und Cateringexpert Monitor 0.3.0 sind auf der Zielinstallation als Supervisor-Apps installiert. Ihre lokalen Projekte enthalten jeweils ein `repository.yaml`, eine App-Konfiguration, einen Docker-Build mit Supervisor-Labels, Dokumentation und einen Launcher für die Supervisor-Optionen. Beide laufen geschützt ohne privilegierten Container und ohne Host-Netzwerk. Der Knowledge Hub übernimmt die Docker-Labels und `init: false`. Die Labels beschreiben den Build und stellen für sich genommen keine geprüfte Kompatibilität her.

Die Monitore sind Hintergrunddienste mit MQTT Discovery; sie verwenden kein Ingress. MQTT, Brokerzugriff und deren Launcher sind deshalb keine Lösung für die Browseroberfläche des Knowledge Hub. Auch `homeassistant_api` wird für den derzeitigen Funktionsumfang nicht benötigt. Automatischen Start (`boot: auto`) übernehmen wir für den nicht betriebsbereiten Prototyp bewusst noch nicht.

Das GitHub-Repository `enricohoeffler/knowledge-hub` und die zugehörige `repository.yaml` sind vorbereitet. Eine App-Store-Installation daraus wurde noch nicht getestet. Die laufenden Monitor-Apps belegen weder die Sicherheit noch die Funktion des Knowledge Hub unter Ingress.

## Abgleich mit Xavier Bergers MkDocs-App

Abgleich am 22.11.2026: Die online abrufbare `mkdocs/config.yaml` auf `main` weist wie die lokale Referenz Version 1.1.6 aus. Die folgenden Details zur Laufzeit stammen aus der lokalen Referenz auf Commit `8fff197aad0669d47b9b3fb573a9af58d16931b1`; der gesamte aktuelle `main`-Stand wurde nicht als identisch verifiziert.

| Bereich | MkDocs-Referenz | Knowledge Hub / Konsequenz |
| --- | --- | --- |
| Installation | Eigenes Git-Repository mit `repository.yaml`, App-Verzeichnis und veröffentlichtem architekturspezifischem Image. | Eigenes Repository vorbereitet; kein veröffentlichtes Image und keine getestete Store-Installation. Die URL des Originals installiert dessen MkDocs-App, nicht den Knowledge Hub. |
| Start | HA-Basisimage und S6 starten MkDocs sowie Nginx; Initialisierung kopiert bei fehlender Konfiguration Beispiele nach `/config`. | Python-Prozess ohne S6; die ausgeschaltete HA-Testoption aktiviert flüchtige Testdaten. Start über Supervisor und Erreichbarkeit sind ungeprüft. S6 ist für einen Prozess nicht zwingend. |
| Ingress | Port 8099; Nginx akzeptiert laut Referenz nur `172.30.32.2`. | Im synthetischen HA-Testmodus wird die TCP-Quelladresse geprüft; lokale Tests prüfen die Entscheidung und Abweisung echter Direktverbindungen. Echter Ingress ist ungeprüft. |
| Vorschau | Zusätzlich ist Port 8000 für `mkdocs serve` veröffentlicht. | Kein Host-Port; diesen Port nicht ohne gesondertes Authentifizierungs- und Sicherheitskonzept übernehmen. |
| Daten | `addon_config:rw`; MkDocs-Konfiguration und `docs` liegen im App-Konfigurationsverzeichnis. | Keine HA-Speicherfreigabe; Positivliste und isolierter Build sind Prototypen. Ein späteres Speicherkonzept muss Quelldaten, Policy, Backup und Zugriffsrechte getrennt betrachten. |
| Konfiguration | MkDocs-Dateien statt Supervisor-Optionen; die mitgelieferte Konfiguration nutzt unter anderem einen externen PlantUML-Dienst. | Leeres Optionsschema und eigene MkDocs-Vorlage; kein externer PlantUML-Dienst. Kein Original-Verhalten hinsichtlich Diagrammen oder Plugins voraussetzen. |
| Bearbeitung | Referenz beschreibt das Bearbeiten der Quelldateien außerhalb des MkDocs-Webservers. | Eigener browserbasierter Editor mit Schreib-API; deshalb sind CSRF, Konflikte, Isolation und Wiederherstellung zusätzliche Anforderungen. |

Quellen: [Upstream-Konfiguration](https://github.com/XavierBerger/home-assistant-addons/blob/main/mkdocs/config.yaml), [Upstream-Dokumentation](https://github.com/XavierBerger/home-assistant-addons/blob/main/mkdocs/DOCS.md), [HA-Ingress-Anleitung](https://contributors.home-assistant.io/apps/guides/ingress/) und [HA-App-Repository](https://contributors.home-assistant.io/apps/guides/repository/). Die Übernahme von Theme und Konfiguration ist in `README.md` und `knowledge_hub/UPSTREAM-LICENSE.md` angegeben.

## Reihenfolge bis zum Integrationstest

1. Eine isolierte HA-Testinstallation und ausschließlich synthetische Quelldaten verwenden. Keine produktiven Freigaben einbinden. Die App-Konfiguration und den Start mit testseitig bereitgestellter Policy und Quelle für diese Umgebung ausarbeiten; Architektur und Supervisor-Kompatibilität tatsächlich prüfen.
2. Ingress-Pfadpräfix für Oberfläche, Assets, Suche, Editor und sämtliche API-Aufrufe unterstützen. Verbindungen ausschließlich vom dokumentierten Ingress-Proxy akzeptieren; keinen zusätzlichen Host-Port veröffentlichen. Authentifizierung, CSRF und aktive Inhalte einschließlich iframe-Isolation fachgerecht absichern.
3. Speicherzugriff auf das notwendige Minimum begrenzen. Dateizugriff gegen Symlink-Rennen absichern und die Policy bei Widerruf zuverlässig durchsetzen. Vor echter SMB-Nutzung Mounttyp und Quelle verifizieren und bei Trennung, falschem Mount oder Schreibfehler geschlossen bleiben.
4. Gleichzeitiges Schreiben über alle beteiligten Prozesse und SMB-Clients sicher lösen; Konfliktentwürfe dauerhaft erhalten. Unabhängige versionierte Sicherung und Wiederherstellung praktisch testen.
5. Auf der Testinstallation Installation, Start, Neustart und Entfernung prüfen. In Chrome über echten HA-Ingress Navigation, Suche, Laden, Speichern, parallele Konflikte, Wiederherstellung, gesperrte Pfade und Abmeldung testen. Direkte Zugriffe und unzulässige Proxy-Quellen müssen scheitern. Fehler und Ergebnisse mit Versionen dokumentieren.

Erst nach erfolgreicher Sicherheitsprüfung und vollständigem Test ist eine konkrete produktive Installation sinnvoll zu planen. Siehe auch die detaillierten Grenzen in `README.md`.

## Prüfung dieser Sitzung

- Chrome zeigte die lokale synthetische Testseite, die Suche fand „Soljanka“, und der Editor öffnete die entsprechende Markdown-Datei. Die Browsersteuerung verlor beim Versuch, den Editor zu bearbeiten, den Fokus; Speichern und Wiederherstellen wurden im Browser nicht verifiziert.
- `node tests/test_editor.mjs` bestand. Nach Freigabe des Docker-Zugriffs wurde das Image neu gebaut; alle acht Python-Testgruppen liefen ohne Containernetzwerk erfolgreich. Zusätzlich startete der synthetische HA-Modus im Container und wies direkte Verbindungen mit gefälschtem Forwarded-Header ab. Das simuliert weder eine echte SMB-Trennung noch echten Ingress.
- Keine Home-Assistant-Einstellungen oder Apps wurden verändert.
