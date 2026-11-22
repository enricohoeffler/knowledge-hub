# Knowledge Hub – Testversion

Diese Version ist ausschließlich für synthetische, entbehrliche Beispieldateien gedacht. Keine produktiven Brain-Verzeichnisse oder vertraulichen Inhalte verbinden. Der Editor, der Zugriffsschutz und die Wiederherstellung sind nicht für echte Daten freigegeben.

Entweder `synthetic_ha_test` aktivieren (eingebaute, beim Neustart zurückgesetzte Beispiele) oder `smb_test_enabled` aktivieren (separate SMB-Testfreigabe). Beide Optionen gleichzeitig sind unzulässig. Die App verbindet sich direkt per SMB; `/share` wird nicht in den Container eingebunden.

Für den SMB-Test ein dediziertes Benutzerkonto verwenden, das auf dem Server ausschließlich Zugriff auf die Testfreigabe hat. In den App-Optionen einstellen:

- `smb_server`: Hostname oder IP-Adresse des SMB-Servers.
- `smb_share`: Name der SMB-Freigabe.
- `smb_username` und `smb_password`: Zugangsdaten des eingeschränkten SMB-Kontos.
- `smb_subdirectory`: optionaler relativer Unterordner auf der Freigabe.
- `allowed_files`: explizite relative Pfade der freigegebenen Beispieldateien, einschließlich `index.md`.

Das Passwort wird in den App-Optionen eingegeben und von Home Assistant als `/data/options.json` an die App übergeben; es steht nicht im Repository. Alternativ kann ein Home-Assistant-Secret referenziert werden. App-Daten und Backups entsprechend schützen. Bei Passwortwechsel das neue Passwort zuerst auf dem Server setzen und dann in den App-Optionen ändern; nach erfolgreichem Verbindungstest das alte Passwort widerrufen.

Die App verwendet nur die konfigurierte Server-/Freigabekombination und eine Dateipositivliste. Die tatsächliche Begrenzung der SMB-Rechte erfolgt serverseitig über das gewählte Benutzerkonto; Unterordner und Positivliste sind keine Ersatzberechtigung. DFS ist deaktiviert und SMB-Reparse-Punkte werden abgelehnt; Pfadprüfungen können bei gleichzeitigen Änderungen durch andere Clients überholt werden.

Der Editor erkennt Änderungen anhand einer Revision vor dem Speichern. Andere SMB-Clients können zwischen Prüfung und Ersetzen schreiben; dabei kann es zu Datenverlust kommen. Nur eine Person beziehungsweise ein Programm darf gleichzeitig an den Testdateien arbeiten. Sicherungen im Editor liegen nur im Arbeitsspeicher und gehen beim Neustart verloren. Vor dem Test separate Kopien sichern.

SMB-Ausfall, Wiederverbindung und gleichzeitige Schreibzugriffe wurden noch nicht mit einer echten SMB-Freigabe getestet. Ingress akzeptiert nur die dokumentierte Supervisor-Proxyadresse; CSRF- und Schutz vor aktivem HTML sind nicht vollständig geprüft.
