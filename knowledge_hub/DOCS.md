# Knowledge Hub – synthetischer Test

Diese App ist nicht produktionsbereit. Sie darf nur in einer isolierten Home-Assistant-Testinstallation mit synthetischen Daten getestet werden. Der Editor, der Zugriffsschutz und die Wiederherstellung sind nicht für echte Daten freigegeben.

Die Option `synthetic_ha_test` ist standardmäßig ausgeschaltet. Wenn sie eingeschaltet wird, erstellt die App bei jedem Start eine neue flüchtige Kopie der enthaltenen Beispieldaten. Änderungen gehen beim Neustart verloren. Der interne HTTP-Port akzeptiert nur Verbindungen von der dokumentierten Supervisor-Adresse `172.30.32.2`. Es wird kein Host-Port und keine HA-Datenfreigabe konfiguriert.

Ein echter Supervisor-/Ingress-Test steht noch aus. Das Verhalten bei anderen Netzwerkkonfigurationen ist nicht nachgewiesen. Keine produktiven Verzeichnisse einbinden.
