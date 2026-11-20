# Neuimplementierung — Notizen aus der Plan-Diskussion

Arbeitsnotizen für den Neuanfang. Sie halten fest, was **entschieden** ist, was nur
**vorgeschlagen** und noch nicht bestätigt ist, und was **offen** ist. Grundlage für einen
neuen `IMPLEMENT.md`. Die Datei gehört später ins neue Repository.

Begonnen: 2026-11-16 · Zuletzt aktualisiert: 2026-11-16 (alle Punkte bis auf Markenfarbe/Logo entschieden)

Legende: **[E]** entschieden (vom Projektverantwortlichen bestätigt) · **[V]** Vorschlag,
noch nicht bestätigt · **[?]** offene Frage · **[!]** Folge einer Entscheidung, die
geklärt werden muss

---

## 1. Rahmen

- **[E]** Produktname: **Fact Spreader**, ein Wortwitz, der Fakten einen ansteckenden
  Charakter zuschreibt (wie „Superspreader“). Der Name passt zum Plugin
  [fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader).
- **[E]** Das Projekt wird **Open Source**, mit diesen Lizenzen:
  | Teil | Lizenz | Grund |
  |---|---|---|
  | Server und Weboberfläche | **AGPL-3.0-or-later** | Wer eine veränderte Fassung als Dienst betreibt, muss den Code offenlegen. Das passt zu einem Produkt, dessen Glaubwürdigkeit von Transparenz lebt |
  | Browser-Plugin (Fork) | **MIT** (wie das Original) | Die MIT-Lizenz und der Copyright-Hinweis des Originals bleiben erhalten. Die Verbreitung über die Stores bleibt einfach |
  | Methodik-Daten (Checklisten, Muster, Publisher-Liste, Personas, Eval-Sets, Fixture-Korpus) | **CC BY-SA 4.0** | Inhalt, kein Code. Weiternutzung mit Namensnennung, Verbesserungen bleiben offen |
  | Beiträge | **DCO** (`Signed-off-by`) statt CLA | Leichtgewichtig, üblich |

  Die Abhängigkeiten (LightRAG MIT, Docling MIT, lingua Apache-2.0, FastAPI MIT,
  Svelte MIT) sind mit AGPL-3.0 vereinbar. Die Alternativen sind EUPL-1.2 (europäisch,
  ebenfalls mit Netzwerk-Klausel) und Apache-2.0 (permissiv, eher für eine Verbreitung in
  Unternehmen). Keine Rechtsberatung: Vor der Veröffentlichung sollte jemand die Wahl
  bestätigen.
- **[E]** Neu anfangen, in einem neuen Repository unter
  `/Users/caboe/project/fact-spreader-server`.
- **[E]** Specs, Plan, Code, Kommentare und Prompts sind **Englisch**. Diese Notizen
  bleiben auf Deutsch als Protokoll der Entscheidungen.
- **[E]** Der Stack bleibt im Wesentlichen: Python 3.12 / FastAPI, LightRAG (stock, nur
  HTTP), Postgres (pgvector + AGE), Redis, Worker. **Frontend: Svelte statt React.**
- **[E]** **SvelteKit im SPA-Modus** (`adapter-static`): Dateibasiertes Routing und
  Layouts, kein Node-Server. FastAPI bleibt das einzige Backend.
- **[E]** `PURPOSE.md`, `PROTOCOL.md` und `PERSONAS.md` bleiben, soweit die Entscheidungen
  unten sie nicht berühren. Wo sie berührt werden, steht es in Abschnitt 11.
- **[E]** Die Agent-Umgebung für den Neuanfang hat **Docker**, einen **Browser
  (Playwright)** und einen **echten LLM-Key**, aber kein lokales Modell. Folge: Fast alle
  „Done when“-Prüfungen können `[agent]` sein, also Compose-Stack, Testcontainers, E2E,
  Screenshots und Live-Evals. `[human]` bleiben die optische Abnahme und der Test des
  Plugins im echten Browser. Live-Läufe kosten Geld, deshalb braucht der Agent ein
  eigenes Budget.

### Was aus dem alten Repository übernommen wird (vom Verantwortlichen delegiert)

| Was | Übernehmen? | Begründung |
|---|---|---|
| `PURPOSE.md`, `PROTOCOL.md`, `PERSONAS.md` | **ja, als Ausgangspunkt** | Werden nach Abschnitt 11 angepasst |
| Fixture-Korpus (`tests/fixtures/corpus/`) und Eval-Sets (`claims.seed.jsonl`, Claim-Set, `moderation.jsonl`) | **ja, geprüft und erweitert** | Inhaltlich wertvoll. Erweitert um fr/es, Belege nur in Tabellen/Diagrammen, Bild-Eingaben und Posts im Plugin-Stil. Die erwarteten Verdicts müssen nach der Gate-Änderung (Abschnitt 3a) neu bewertet werden |
| `publishers.json`, Confounder-Checklisten, `patterns.json`, Layer-B-Manifest | **ja** | Methodik-Arbeit, die unabhängig vom Code ist |
| `DECISIONS.md`, `NOTES.md`, `docs/FIRST_START_DE.md` | **nein, nur verlinkt** | Erfahrungsquelle. Das Wichtigste steht verdichtet in Abschnitt 10 |
| Code | **nein, nur als Lesestoff** | Neu geschrieben, mit Tests. Lesenswert: `gate.py`, `verdicts.py`, SSRF-Guard, Log-Scrubber, Cursor-Format, Spracherkennung. Wer Code kopiert, holt sich die alte Struktur mit, und das Gate ändert sich ohnehin |
| `AGENTS.md` | **neu schreiben** | Die harten Invarianten werden übernommen und angepasst |

## 2. Umfang

### In v1

- Prüf-Schnittstelle für Claims **und** Texte (Kern des Produkts, Abschnitt 4)
- Claim-Warteschlange und Archiv (Abschnitt 5)
- Dokumenten-Pipeline mit Freigabe und Batch-Upload (Abschnitt 3a)
- Rollen, Berechtigungen und Grenzen (Abschnitt 3)
- Nutzungs- und Verbrauchsübersicht mit LLM-Gateway (Abschnitt 3b)
- Fast-Modus (Abschnitt 6)
- Mehrsprachige Ein- und Ausgabe (Abschnitt 7)
- Bild-Eingaben und Abbildungen im Korpus (Abschnitt 8)
- OpenAI-kompatible Schnittstelle (`/v1/chat/completions`)
- Chat in der Weboberfläche für alle angemeldeten Benutzer
- Schnittstelle für das Browser-Plugin (Abschnitt 9)
- Recherche-Modus: Dokumente, geprüfte Claims, Zusammenfassung mit Links (Abschnitt 4a)

### Verschoben auf v2 **[E]**

- Federation: Peers und Dokumenten-Sync (Manifest, Changes, Snapshots). Konzept und
  Vorbereitung in v1 siehe „Federation“ unten.
- Public Mode (anonymer Chat)
- **Teilen-Link** zu einem Prüfbericht (öffentliche, schreibgeschützte Seite), frühestens
  in v2. Die Details werden dann noch einmal geklärt (Sichtbarkeit, Datenschutz für
  Kontextdaten, Moderation, Versionierung, Missbrauch).
- Webhooks
- **Websuche (Tier 3)**, also SearXNG, Brave, Tavily und die Seitenprüfung
- Benutzerkorrektur der Aussagen-Auswahl („diese auch prüfen“, „diese ignorieren“)
- Echtheitsprüfung von Bildern (Manipulation, alter Kontext, Rückwärts-Bildersuche)
- **[E]** Automatisches Hervorheben von Behauptungen auf Webseiten ohne Markieren
- **[E]** E-Mail-Benachrichtigungen

### Federation (Netz von Instanzen) — v2, aber vorbereitet

- **[E]** Das Konzept bleibt: Andere Server mit dieser Applikation werden als Peers
  eingetragen, und Dokumente lassen sich zwischen ihnen abgleichen (PROTOCOL §5–§6, alter
  Plan Phase 8). Umsetzung in v2.
- **[!]** Konflikt mit den neuen Entscheidungen: Weil freigegebene Dokumente als wahr
  gelten und jedes Dokument ausdrücklich freigegeben werden muss, darf ein Dokument aus
  einem Peer nicht ohne eigene Freigabe „wahr“ werden. Weil nur gegen das eigene
  LightRAG geprüft wird, passt die Live-Abfrage bei Peers (Evidence-Server, Tier 2) nicht
  mehr.
- **[E]** In v2 ist Federation **Dokumenten-Austausch, keine Live-Abfrage**:
  - Peer eintragen mit Identitätsprüfung (`instance_id`, Protokollversion). Ändert sich
    die Identität, wird der Peer gesperrt.
  - Sync über Snapshot + Änderungsprotokoll mit Cursor. Löschungen werden übertragen.
  - Synchronisierte Dokumente landen in der **eigenen Freigabe-Warteschlange**
    (Checkbox-Liste wie beim Batch) und zeigen Herkunft und Freigabe-Information des
    Peers an.
  - Optional pro Peer „Freigaben dieses Peers übernehmen“, standardmäßig aus und vom
    Redakteur bewusst gesetzt.
  - Es wird nichts weitergegeben, was man selbst von Dritten hat. Lizenzen werden
    respektiert (`metadata_only`). Pro Peer gibt es eine Vertrauens-Obergrenze, und die
    Herkunft bleibt sichtbar.
  - Die Live-Abfrage entfällt oder kommt später.
- **[E]** **Vorbereitung schon in v1** (kostet fast nichts und erspart eine Migration):
  - `instance_id` ab dem ersten Start, unveränderlich
  - stabile Dokument-IDs mit Versionen und ein Änderungsprotokoll für jede
    Dokument-Änderung
  - Herkunftsfelder `origin_instance_id` und `origin_document_id` (in v1 die eigene
    Instanz)
  - Lizenz- und Weitergabe-Status (`redistribution`), erfasst bei der Freigabe
  - Freigabe-Information (wer, wann) im Datenmodell

## 3. Rollen, Berechtigungen, Grenzen

- **[E]** Eine Organisation pro Installation, keine Mandantenfähigkeit.
- **[E]** Nur lokale Benutzerverwaltung, kein SSO.
- **[E]** Jeder angemeldete Benutzer darf den Chat benutzen.
- **[E]** Rollen in v1:
  | Rolle | Aufgabe |
  |---|---|
  | Betreiber (DevOps) | LLM-Provider, Modelle, Rollenzuweisung, LightRAG-Anbindung, Moderations-Backend, Datenfluss, Budgets, Health, Neuindizierung, Verbrauchsübersicht |
  | Redakteur | Entscheidet, was in den Korpus (LightRAG) kommt: prüfen, freigeben, ablehnen mit Begründung, Tags/Lizenz bestätigen, zurückziehen |
  | Reporter | Reicht Dokumente (und Claims) ein, auch über die API; sieht den Status der eigenen Einreichungen |
  | Nutzer | Chat, Claims prüfen lassen, Feedback |
  | Methodik | Confounder-Checklisten, Themen/Domänen, Argumentationsmuster, Publisher-Grading, Evidenz-Policy, Personas |
- **[E]** Qualitätssicherung und Auditor (nur lesen) gibt es in v1 nur als Berechtigungen,
  ohne eigene Oberfläche.
- **[E]** „Claims einreichen“ (`claims:submit`) ist eine eigene Berechtigung, die sich pro
  Benutzer einzeln vergeben oder entziehen lässt. **Standardmäßig ist sie bei allen an.**
- **[E]** Grenzen (Textlänge, Volumen u. a.) haben einen Standardwert pro Rolle und sind
  pro Benutzer einstellbar.
- **[E]** Berechtigungen sind die eigentliche Einheit (`chat:use`, `claims:submit`,
  `documents:submit`, `documents:review`, `config:manage`, `methodology:manage`,
  `users:manage`, `usage:read`, …). Rollen sind Vorlagen, die sie bündeln. Pro Benutzer
  gibt es zusätzliche Grants und Entzüge. Ein Benutzer kann mehrere Rollen haben, und der
  erste Account hat alle.
- **[E]** Dasselbe Muster gilt für Grenzen: Die Rolle liefert den Standard, der Benutzer
  kann abweichen, ein API-Key liegt höchstens darunter. Grenzen sind Textlänge,
  Anfragen/Tag, LLM-Budget, gleichzeitige Jobs, Dateigröße und Dateien pro Stapel.
- **[E]** `users:manage` ist eine eigene Berechtigung, getrennt vom Betreiber. Wer Modelle
  konfiguriert, kann sich nicht selbst zum Redakteur machen.
- **[E]** API-Keys gehören einem Benutzer und haben höchstens dessen Rechte.
- **[E]** Es gibt **eine App mit rollenbezogenen Bereichen** (Prüfen, Archiv, Redaktion,
  Methodik, Betrieb) statt eines großen Dashboards mit ausgeblendeten Teilen. Man meldet
  sich einmal an, und die Seitenleiste zeigt nur die eigenen Bereiche.
- **[E]** Optionales Vier-Augen-Prinzip: Ob man eigene Einreichungen freigeben darf, ist
  einstellbar.
- **[E]** Die Provenienz enthält Menschen: wer ein Dokument eingereicht und wer es wann
  freigegeben hat. **Mit Namen sehen das nur Redaktion, QS und Auditor.** Andere Benutzer
  sehen bei Zitaten „redaktionell freigegeben am …“.

## 3a. Zwei getrennte Pipelines **[E]**

| | **Claim-Pipeline** | **Dokumenten-Pipeline** |
|---|---|---|
| Eingabe | Behauptung oder Text (Klartext, Datei, URL, Bild), z. B. aus dem Plugin | Quellen, die als wahr gelten sollen |
| Wer | Benutzer mit `claims:submit` | Redakteur (Upload) oder Reporter/Systeme über einen Endpunkt |
| Verarbeitung | Prüfung **nur gegen das bestehende LightRAG**, **keine Websuche** | vollständige Prüfung, Freigabe, danach Teil des RAG |
| Landet im RAG? | **nie** | ja, nach Freigabe |
| Ergebnis | geht **direkt** raus, ohne redaktionelle Endkontrolle | erweitert die Wissensbasis |

- Die einzige Verbindung: Fehlen einem Claim Quellen, kann jemand ein Dokument
  nachreichen. Es durchläuft die Dokumenten-Pipeline ganz normal.
- **[E]** **Jedes Dokument muss ausdrücklich freigegeben werden**, es gibt keine
  automatische Freigabe. Beim Batch-Upload gibt es dafür eine Checkbox-Liste.
  **[E]** Dokumente ohne Warnung sind vorausgewählt, solche mit Warnung nicht. Warnungen
  sind z. B. eine nicht unterstützte Sprache, Injection-Verdacht, eine niedrige
  Quellennote, ein Duplikat oder eine unklare Lizenz.
- **[E]** Das gilt auch für Uploads eines Redakteurs. Er darf seine eigenen Dokumente
  freigeben, außer das optionale Vier-Augen-Prinzip ist eingeschaltet.
- **[E]** **Freigegebene Dokumente gelten als wahr. Eine Quelle reicht** für ein Verdict.
  Das ist vertretbar, weil jede Freigabe eine menschliche Entscheidung ist.
- **[E]** Zwei Fälle werden **protokolliert**:
  | Fall | Benutzer sieht | Protokoll | Wer sieht es |
  |---|---|---|---|
  | **Widerspruch** zwischen freigegebenen Dokumenten | Ergebnis mit **beiden** Belegen, als Widerspruch markiert | Claim, beide Dokumente, Passagen | Redakteur + Methodik: Liste „Widersprüche im Korpus“ |
  | **Kein Dokument** zum Claim gefunden | `insufficient_evidence`, „Im Korpus nichts dazu gefunden“ | Claim, Sprache, Themen, Häufigkeit (ähnliche Claims zusammengefasst) | Redakteur: Liste „Korpus-Lücken“, nach Häufigkeit sortiert, mit Einreichen direkt von dort |
- **[E]** Den Widerspruch erkennt der **Code** aus den Haltungen des Verifiers (ein
  freigegebenes Dokument `supports`, ein anderes `refutes`). Beziehen sich beide auf
  verschiedene Zeiträume, ist das eine Entwicklung, kein Widerspruch. Dann zählt die zum
  Claim passende Quelle.
- **[E]** Verdict bei einem Widerspruch: **neues Verdict `contested`** („die Quellen
  widersprechen sich“ ist eine andere Aussage als „wir wissen es nicht“). Es ist der
  siebte Wert in PROTOCOL §2.1. Die Gesamtverdict-Regel, die Personas, die
  Substanz-Vorlagen, die Farben und die Eval-Sets müssen ihn kennen.
- **[!]** Weitere Folgen von „eine Quelle reicht“:
  1. Das **Mindestquellen-Gate** (PROTOCOL §2.1: zwei unabhängige Quellen) ändert sich.
     Gate und erwartete Eval-Verdicts müssen angepasst werden.
  2. **Das Misleadingness-Audit bleibt.** Eine wahre Quelle macht einen Claim nicht
     automatisch vollständig, und `true_but_misleading` bleibt der Kernfall.
  3. **Die Aktualität bleibt.** Eine veraltete Zahl ist „wahr für 2019“, nicht für heute.
  4. **Die Publisher-Note** wirkt vor allem **bei der Freigabe** (als Warnung). Bei den
     Belegen wird sie weiter angezeigt.

### Batch-Upload in der Dokumenten-Pipeline

- **[E]** Jeder, der über die Weboberfläche Dokumente hochlädt, bekommt einen
  Batch-Upload für viele Dokumente gleichzeitig.
- **[E]** Alle Eingabewege: mehrere Dateien per Drag & Drop, ein ganzer Ordner, ein
  ZIP-Archiv (Schutz gegen ZIP-Bomben und Pfad-Tricks), eine URL-Liste und eine
  **Metadaten-Datei** (CSV/JSON) pro Datei.
- **[E]** Freigabe im Stapel über eine Checkbox-Liste (Dokumente ohne Warnung
  vorausgewählt), ein Klick gibt die Auswahl frei.
- **[E]** Größenordnung: **Dutzende** Dateien pro Stapel (bis etwa 100). Ein fortsetzbarer
  Upload (tus) ist damit nicht zwingend. Normale Uploads mit Wiederholung pro Datei
  reichen.
- **[E]** Gemeinsame Angaben (Tags, Lizenz, Domäne, Publisher) für den Stapel, pro Datei
  überschreibbar.
- **[E]** Jede Datei ist ein eigenes Dokument, der Stapel nur eine Klammer. Fehler
  betreffen nur die einzelne Datei. Duplikate werden innerhalb des Stapels und gegen den
  Korpus erkannt. Die Verarbeitung läuft im Worker weiter, auch wenn das Fenster zu ist.
- **[E]** Übersicht mit Status pro Datei und einer Zusammenfassung („80 bereit · 12 mit
  Warnung · 5 Duplikate · 3 Fehler“). Fehler lassen sich einzeln wiederholen.
- **[E]** Vor dem Start eine Kostenschätzung (Seiten, Abbildungen, Vision-Kosten), und das
  Budget gilt.
- **[E]** Grenzen (Dateien pro Stapel, Gesamtgröße) gelten pro Rolle und sind pro
  Benutzer einstellbar. Dieselbe Funktion gibt es auch über die API.

## 3b. Nutzungs- und Verbrauchsübersicht für den Betreiber

- **[E]** Im Dashboard des Betreibers gibt es eine Übersicht: welcher Benutzer wie viele
  API-Zugriffe hat, wie viele Tokens an LLMs geflossen sind und weitere gängige Daten.
- **[E]** Kosten werden in **US-Dollar** angezeigt, wie bei den Providern, ohne
  Umrechnung.
- **[E]** Jeder Benutzer sieht seinen **eigenen** Verbrauch und seine Grenzen.
- **[E]** Aufbewahrung: Einzelereignisse 90 Tage, Zusammenfassungen unbegrenzt.
- **[E]** **LLM-Gateway:** Alle Modell-Aufrufe laufen über ein internes Gateway, auch die
  von LightRAG (dort nur als `base_url` konfiguriert, LightRAG bleibt stock). Damit gelten
  Zählung, Budgets und Datenfluss überall, auch bei der Ingestion.
- **[E]** Das Gateway wird **selbst gebaut, als schmaler Teil des Backends**, nicht
  LiteLLM (vom Verantwortlichen delegiert). Gründe: Datenfluss-Policy und Budget-Check
  sind harte Invarianten und liegen ohnehin in unserem Code. Ein fremdes Gateway brächte
  ein zweites Budget- und Rechtesystem. Alle Provider sprechen die OpenAI-Schnittstelle,
  und es ist ein Dienst weniger. Umsetzung: ein OpenAI-kompatibler Endpunkt nur im
  internen Netz (Chat, Vision, Embeddings), LightRAG mit eigenem internem Key.
  Einschränkung: LightRAGs Calls werden dem Verbraucher „LightRAG“ zugeordnet, nicht exakt
  einem Dokument.
- **[E]** Inhalte:
  - pro Benutzer: Anfragen nach Zugangsweg (Web, Plugin, API, OpenAI-API), pro Key und
    Gerät, Verbrauch im Verhältnis zur Grenze, Prüfungen, Einreichungen, abgelehnte
    Anfragen (Rate-Limit, Budget, Moderation)
  - LLM: Tokens und Kosten nach Provider, Modell und Rolle, lokal und extern getrennt,
    Vision-Kosten getrennt, Kosten pro Prüfung (Fast vs. voll)
  - Leistung: Median und p95 für Cache, Fast und voll gegen die Ziele, Cache-Quote,
    Warteschlange, Fehlerquote pro Provider, Circuit Breaker
  - Qualität: Verteilung der Verdicts, Widersprüche, Consistency-Fallbacks,
    Beanstandungen des Judge, Moderations-Treffer, Feedback
  - System: Korpusgröße, offene Freigaben, Batch-Uploads, Zustand der Dienste
- **[E]** Gestaltung: Kennzahl-Karten mit Verlaufskurven (wie die Bildschirmzeit),
  Diagramme, Benutzertabelle mit Detailansicht, Zeitraum per Segmented Control,
  CSV-Export, Hinweise in der App. Diagramme mit LayerChart oder ECharts.
- **[E]** Ein zentrales Ereignis-Protokoll (Request und LLM-Call) mit stündlichen und
  täglichen Zusammenfassungen. Dieselben Daten speisen auch die Budgets.
- **[E]** Die Übersicht zeigt Mengen, keine Inhalte. Inhalte brauchen eine eigene
  Berechtigung (QS/Auditor).
- **[E]** Eigene Berechtigung `usage:read` (Standard: Betreiber).
- **[E]** Optional `/metrics` für Prometheus/Grafana.

## 3c. Modellauswahl: nur passende Modelle anzeigen

- **[E]** An jeder Stelle der Konfiguration werden **nur die Modelle angezeigt, die für
  diese Stelle passen**. Im alten Stand erschienen überall alle Modelle, z. B. ein
  Chat-Modell in der Auswahl für das Embedding.
- **[E]** Jedes Modell hat **Fähigkeiten** (`chat`, `vision`, `embedding`, `rerank`,
  `moderation`, `structured_output`) und Eigenschaften (Kontextlänge,
  Embedding-Dimension, mehrsprachig, lokal/extern).
- **[E]** Jede Stelle (Rolle) hat **Anforderungen**:
  | Stelle | Benötigt |
  |---|---|
  | Extraktion, Verifikation, Audit, Judge | `chat` + `structured_output`, Mindest-Kontextlänge |
  | Rendering (Personas) | `chat` |
  | Bild-Eingabe, Abbildungen im Korpus | `vision` |
  | Embedding (LightRAG) | `embedding`, mehrsprachig, Dimension passend zum Vektorspeicher |
  | Rerank | `rerank` |
  | Moderation | `moderation` oder `chat` + `structured_output`; für Bilder `vision` |
  | LightRAG-Extraktion | `chat` |
- **[E]** **Eine Regel-Quelle für Oberfläche und Backend.** Die Auswahllisten filtern nach
  denselben Anforderungen, die das Backend beim Speichern prüft. Eine falsche Zuweisung
  über die API ist ein `422` mit Begründung.
- **[E]** **Fähigkeiten werden ermittelt, nicht nur behauptet:**
  - Beim Anlegen fragt das System den Provider ab. Ollama meldet die Fähigkeiten selbst
    (`/api/show`), LM Studio den Modelltyp (llm/vlm/embeddings). Bei OpenAI-kompatiblen
    Providern, die nichts melden, wird ein Vorschlag aus dem Modellnamen gemacht.
  - Ein **Fähigkeitstest** bestätigt den Vorschlag: eine kurze Chat-Antwort, ein
    JSON-Schema, ein Testbild mit Text, ein Embedding-Aufruf mit gemessener Dimension und
    der sprachübergreifende Vergleich.
  - Jede Fähigkeit zeigt, ob sie **getestet** oder nur **angenommen** ist. Für Rollen mit
    Pflichtanforderungen zählen nur getestete Fähigkeiten.
- **[E]** Die Auswahl zeigt standardmäßig nur passende Modelle. Ein Schalter „Andere
  anzeigen“ listet die übrigen ausgegraut **mit Grund** („kein Embedding-Modell“,
  „Dimension 768, erwartet 1024“, „Vision nicht getestet“). Ist kein passendes Modell da,
  steht dort, was fehlt, mit einem Link „Modell hinzufügen“.
- **[E]** Ein Modell, das niemand zugewiesen hat, ist erlaubt. Die Modellliste zeigt
  pro Modell, wo es verwendet wird.

## 4. Die Prüf-Schnittstelle (Kern)

- **[E]** Wichtigster Punkt: eine Schnittstelle, über die man **Claims oder Texte**
  einreicht. Das System findet die Aussagen darin und bewertet ihre Richtigkeit.
- **[E]** Sie hat viele verschiedene Arten von Benutzern und muss sehr flexibel sein.
- **[E]** Eingabe als Klartext, **Datei-Upload** oder **URL** (und Bild, Abschnitt 8).
- **[E]** Die OpenAI-kompatible Schnittstelle bleibt bestehen.
- **[E]** Webhooks erst in v2.
- **[E]** Moderation für Eingaben der Claim-Pipeline (Plugin, „prüfe diesen Text“),
  Option (a): **kennzeichnen und prüfen**. Blockiert wird nur bei `sexual_minors`. Wer
  einen hetzerischen Post prüfen lässt, sagt ihn nicht selbst.
- **[E]** Dazu: Die Persona-Antwort gibt keine Beleidigungen wieder, und die Ausgabe wird
  moderiert (bei einem Treffer ersetzt die deterministische Vorlage den Text). Wer
  auffällig oft gekennzeichnete Inhalte einreicht, erscheint in der QS-Ansicht. Für
  eigene Äußerungen im Chat gilt die strengere Policy. Der Modus hängt am Zugangsweg,
  nicht an einer Angabe des Benutzers.
- **[E]** Ausgabe ist ein Prüfbericht: jede gefundene Aussage mit Fundstelle (Span) im
  Originaltext, Verdict, was stimmt / fehlt / nicht prüfbar ist, Belegen und Mustern.
- **[E]** Neue Pipeline-Stufe vor dem Decomposer: Aussagen-Extraktion mit
  Prüfwürdigkeit (Tatsachenbehauptung vs. Meinung vs. Floskel, Relevanz).
- **[E]** Ein Gesamtbild des Textes (z. B. durch Auswahl irreführend) kommt vom **Code**,
  als Zusammenfassung der Einzel-Verdicts plus Muster. Es gibt kein LLM-Gesamtverdict
  (Invariante 2).
- **[E]** Asynchron als Standard: `POST` → Job-ID, dann Status und Polling oder Live-Events
  per SSE. Teilergebnisse erscheinen, sobald einzelne Aussagen fertig sind. Der Worker
  ist damit in v1 Pflicht. Das beantwortet Kritikpunkt 6 (Abschnitt 10).
- **[E]** Ein synchroner Modus für kurze Eingaben, verbunden mit dem Fast-Modus.
- **[E]** Ein Idempotency-Key gegen doppelte Prüfungen nach einem Netzwerkfehler.
- **[E]** OpenAPI ist verbindlich. Clients für Weboberfläche und Plugin werden daraus
  generiert.
- **[E]** Wählbares Ausgabeformat: nur Substanz, Substanz + Persona oder `compact` (für
  das Plugin).
- **[E]** Die OpenAI-Schnittstelle ist eine dünne Schicht über dem Prüf-Endpunkt, kein
  eigener Pfad.
- **[E]** Chat und Weboberfläche benutzen dieselbe Schnittstelle wie externe Clients.
- **[E]** Eine eingereichte Datei oder URL ist **Prüfgegenstand, kein Korpus-Dokument**.
  Sie landet nicht in LightRAG und läuft unter der Datenklasse `user_input`. Das
  Einlesen der Formate teilt sie sich mit der Dokument-Ingestion. Es gelten SSRF-Schutz
  und Größen-/Zeitgrenzen.

## 4a. Recherche-Modus (dritte Art von Anfrage)

- **[E]** Gewünscht: Eine Frage wie „Donald Trump Minister korrupt inkompetent“ liefert
  alle passenden Dokumente bzw. eine Zusammenfassung mit Links.
- **[E]** Antwort in drei Blöcken:
  1. **Dokumente und Passagen**, nach Relevanz sortiert (Titel, Publisher, Datum, Note,
     Link, Ausschnitt), mit Filtern nach Zeitraum, Domäne, Sprache und Note. Nur Retrieval,
     **kein LLM**, unter 2 s.
  2. **Bereits geprüfte Claims** zum Thema aus dem Archiv.
  3. **Optional eine Zusammenfassung mit Links** (per Klick oder Parameter, kostet LLM).
- **[E]** Regeln für die Zusammenfassung (Risiko der Verleumdung bei realen Personen):
  - nur aus gefundenen Passagen; jeder Satz trägt einen Beleg; Konsistenzprüfung
    (Zitat-IDs + Judge). Scheitert sie, gibt es keine Zusammenfassung, nur die Liste.
  - **zugeschrieben, nie behauptet** („Laut [A] wurde X angeklagt …“, nie „X ist
    korrupt“)
  - wertende Begriffe der Frage werden nicht übernommen. Fehlen Belege, wird das gesagt.
  - **kein Verdict.** Ein Knopf „Als Claim prüfen“ formuliert einen Claim und schickt ihn
    durch die Prüf-Pipeline.
  - Lizenzen gelten (`metadata_only` → nur kurze Ausschnitte).
- **[E]** LightRAG-Graph: verwandte Personen und Organisationen als Navigation; die
  Graph-Beschreibungen sind LLM-Text und nie Beleg.
- **[E]** Schnittstelle `POST /v1/search` mit `summary: true/false`, in der OpenAI-
  Schnittstelle als Modell `factcheck:research`. Berechtigung `search:use` (Standard:
  an), dieselben Budgets, Antwortsprache wie die Frage.
- **[E]** Recherchen ohne Treffer landen in der Liste „Korpus-Lücken“.
- **[E]** Oberfläche: dasselbe Spotlight-Feld wie beim Prüfen, mit Moduswahl. Im Plugin
  ein zweiter Kontextmenü-Eintrag „Dazu recherchieren“.
- **[E]** Umfang: **v1**. Dokumentliste und Archiv-Treffer zuerst, die Zusammenfassung in
  v1 nach dem Kern.
- **[E]** Die strengen Regeln für die Zusammenfassung gelten wie oben beschrieben.
- **[E]** Den Modus **wählt der Benutzer ausdrücklich** (z. B. Segmented Control
  „Prüfen | Recherchieren“ über dem Eingabefeld; in der API über den Endpunkt bzw. das
  Modell). Es gibt keine automatische Erkennung.

## 5. Claim-Warteschlange und Archiv

- **[E]** Gehört in v1, ein wichtiger Bestandteil.
- **[E]** Ein Prüfergebnis geht **direkt raus**, ohne redaktionelle Endkontrolle.
- **[E]** **Alle Benutzer sehen alle geprüften Claims** (Archiv der Organisation).
- **[E]** **Claims aus dem Chat werden automatisch Teil** von Warteschlange und Archiv.
- **[E]** Die Warteschlange ist die Job-Liste der Prüf-Schnittstelle, nichts Zusätzliches.
- **[E]** Ablauf:
  1. Einreichen (Claim oder Text + Kontext)
  2. Duplikat-Prüfung über alle Benutzer, auch für umformulierte Varianten
  3. Automatische Prüfung im Worker
  4. Bei `insufficient_evidence` oder `needs_clarification` erfährt der Redakteur, dass
     Quellen fehlen. Reporter können verknüpfte Dokumente nachreichen.
  5. Offene Claims (z. B. aus der Lücken-Liste) werden **automatisch erneut geprüft**,
     wenn neue passende Dokumente freigegeben werden. Ein einstellbares Tagesbudget
     begrenzt die Kosten, und per Knopf geht es zusätzlich.
  6. Der Einreicher sieht den Status: eingereicht → in Prüfung → Quellen fehlen →
     geprüft
- **[E]** Aus einem Chat-Ergebnis mit `insufficient_evidence` lässt sich „Quellen fehlen“
  melden.
- **[E]** Korrekturen geschehen nur im Nachhinein. Man verbessert die Grundlage (Quellen,
  Checklisten, Publisher-Note) und lässt neu prüfen. Ein Redakteur ändert kein Verdict von
  Hand (Invariante 2). Auffällige Fälle erscheinen in der QS-Ansicht.
- **[E]** Der Einreicher eines Claims ist im Archiv nur für ihn selbst und für QS/Auditor
  sichtbar, nicht für andere Benutzer.
- **[E]** Claims, zu denen nichts gefunden wurde, und Widersprüche landen in den
  Protokoll-Listen aus Abschnitt 3a.

## 6. Fast-Modus

- **[E]** Ist gewünscht, in erster Linie für das Browser-Plugin.
- **[E]** Ziel: Cache-Treffer unter 2 s, vorläufiges Ergebnis unter 15 s.
- **[E]** Die volle Prüfung **folgt automatisch** im Hintergrund und ersetzt das Ergebnis
  versioniert.
- **[E]** Der Fast-Modus gilt **auch für Texte**. Die Aussagen werden parallel geprüft.
- **[E]** Zuerst kommt der Cache mit semantischer Ähnlichkeit, sodass auch umformulierte
  virale Behauptungen gefunden werden. Durch das Archiv aller Claims (Abschnitt 5) wird
  der Cache schnell wertvoll. Danach folgt ein schneller Durchlauf: weniger bzw.
  zusammengelegte LLM-Calls, optional ein schnelleres Modell, Checkliste ohne Nachsuche,
  nur Substanz.
- **[E]** Ein schnelles Ergebnis ist ausdrücklich als `preliminary` markiert. Harte Regel
  im Code: Ein glattes `true` gibt es nur, wenn das Audit nichts Offenes gefunden hat,
  sonst `audit_incomplete` oder eine Herabstufung. Das Gate gilt unverändert (in der
  Form aus Abschnitt 3a).

## 7. Sprachen

- **[E]** Antwortsprache ist standardmäßig die Sprache der Eingabe. Pro Request lässt sie
  sich überschreiben.
- **[E]** Französische Claims werden bearbeitet und auf Französisch beantwortet.
  Weitere Sprachen (u. a. Spanisch) sind zulässig, auch für Korpus-Dokumente.
- **[E]** Ein Korpus-Dokument in einer nicht unterstützten Sprache erzeugt eine Warnung
  für den Redakteur und alle, die freigeben. Sie dürfen es trotzdem freigeben, und es
  landet im Korpus.
- **[E]** Eine **Claim-Eingabe** in einer nicht unterstützten Sprache wird geprüft und
  **auf Englisch beantwortet, mit einem Hinweis**.
- **[E]** Die Liste der unterstützten Sprachen ist konfigurierbar. Eine Sprache gilt als
  unterstützt, wenn es Substanz-Vorlagen, Sprachvarianten der Persona-Checks und eine
  Freigabe durch die Methodik gibt. Zum Start: en, de, fr, es (wie die Oberfläche).
- **[E]** Die interne Pipeline (Extraktion, Verifikation, Audit) arbeitet auf Englisch.
  Nachtrag 2026-11-20: Die nutzersichtbaren Erklärungsfelder der Verifikation
  (Begründung, Was-stimmt/Was-fehlt/nicht-prüfbar, Argumentmuster) werden in der
  Antwortsprache ausgegeben, damit der Bericht nicht gemischtsprachig ist.
  Suchbegriffe entstehen mehrsprachig, nur die Ausgabe ist lokalisiert.
- **[E]** Die deterministische Substanz kommt aus übersetzten Vorlagen, nicht vom LLM
  (Invariante 3). Personas rendern in der Zielsprache, und der Judge prüft in der
  Zielsprache.
- **[E]** Sprachabhängige Persona-Checks brauchen Sprachvarianten, z. B. muss
  `no_second_person` auch „du/Sie/vous/tú“ kennen.
- **[E]** Belege werden im Original gezeigt, mit einer Übersetzung in die Antwortsprache.
  Belege in nicht unterstützten Sprachen tragen einen sichtbaren Hinweis.
- **[E]** Die Spracherkennung kennt mehr Sprachen als die unterstützten, sonst ist
  „nicht unterstützt“ nicht erkennbar (Erfahrung aus dem alten Stand).

## 8. Vision und Bilder

- **[E]** Variante B: Ein Vision-Modell ist von Anfang an Pflicht für Bild-Eingaben.
  Textmodelle bleiben für die anderen Rollen erlaubt.
- **[E]** Bei Bild-Eingaben prüft v1 nur **die Aussagen im Bild**, nicht dessen Echtheit.
  **[E]** Das Ergebnis sagt das ausdrücklich.
- **[E]** Abbildungen im Korpus werden verarbeitet, wo es die Qualität verbessert.
- **[E]** Ein Verdict darf auf einer ungeprüften Abbildungs-Beschreibung beruhen. Es trägt
  dann den Hinweis `relies_on_figure_description`.
- **[E]** Bildpfad der Eingabe: Das Vision-Modell liest den Text, beschreibt Inhalt und
  Diagramme und gibt das als Struktur aus. Danach folgen Claim-Extraktion und die normale
  Pipeline. Ein Bild ist Prüfgegenstand, nie Beleg.
- **[E]** Die Vision-Fähigkeit wird vom Modelltest **geprüft** (Testbild mit Text), nicht
  nur behauptet.
- **[E]** Korpus-Ingestion nach Inhaltstyp:
  | Inhalt | Weg |
  |---|---|
  | Tabellen | Strukturerkennung im Parser (Docling) → Markdown-Tabelle, kein Modell |
  | Diagramme/Abbildungen | Vision-Modell-Beschreibung |
  | Gescannte Seiten | OCR oder Vision-Modell |
  | Fließtext | Parser |

  Damit wird Docling wieder Pflicht und ist nicht mehr optional.
- **[E]** Regeln für Abbildungs-Beschreibungen (sie sind Modell-Output, kein
  Quellentext):
  1. Sie sind eigene Passagen vom Typ `figure_description` mit Seite, Abbildung und dem
     erzeugenden Modell.
  2. Sie dürfen zitiert werden, aber die Anzeige zeigt immer den Bildausschnitt mit.
  3. Sie gehören zu ihrem Dokument und sind nie eine zusätzliche, unabhängige Quelle.
  4. Der Redakteur sieht sie bei der Freigabe und kann sie korrigieren (dann gelten sie
     als redaktionell geprüft, und der Hinweis entfällt).
  5. Sie werden einmal erzeugt und gespeichert. Das Modell ist pro Korpus festgelegt
     (Invariante 10).
  6. Die Eval enthält Fälle, deren Beleg nur in einem Diagramm oder einer Tabelle steht.
- **[E]** Bild-Moderation braucht ein passendes Modell (z. B. Llama Guard 3 Vision).

## 9. Browser-Plugin

- **[E]** Ziel: Text oder Bild in sozialen Medien markieren und über ein Plugin gegen die
  Schnittstelle prüfen lassen.
- **[E]** Grundlage ist [fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader)
  (MIT, Svelte 5 + Tailwind, Manifest V3, Chrome- und Firefox-Manifest, Text- und
  Bildauswahl, i18n de/en/es/fr/pt, Playwright, spricht OpenAI-kompatible Endpoints mit
  Streaming und `image_url`). Der Projektverantwortliche passt es an oder forkt es.
- **[E]** Zunächst nur für angemeldete Benutzer.
- **[E]** Heute basiert es auf API-Keys. Ein „Plugin verbinden“-Ablauf wäre gut.
- **[E]** Plugin verbinden: einmal an der Instanz anmelden, dann bekommt das Plugin einen
  widerrufbaren Token mit minimalen Rechten (`claims:submit`). Er erscheint in der
  Weboberfläche als Gerät. Die Instanz-URL ist im Plugin einstellbar.
- **[E]** Anpassungen im Fork:
  - Personas über `GET /v1/models` holen statt eigener System-Prompts. Ein Client-`system`
    ist bei uns Kontext, keine Anweisung.
  - Die direkte LightRAG-Anbindung für unsere Instanz abschalten.
  - Das strukturierte `factcheck`-Feld anzeigen (kompakt: Badge, ein Satz Fazit, 2–3
    fehlende Kontexte, Link zum vollen Bericht).
  - „Plugin verbinden“ statt API-Key.
  - Die Bildverkleinerung von 512 px auf etwa 1.500–2.000 px anheben, damit Text in
    Screenshots lesbar bleibt.
- **[E]** Kontext (Seiten-URL, Plattform, Autor, Datum) wird **standardmäßig
  mitgesendet**. Er ist für die Prüfung wertvoll, das Datum vor allem für das Audit.
- **[E]** Weil alle Benutzer das Archiv sehen, würden Autor und URL fremder Posts sonst
  für die ganze Organisation sichtbar. Deshalb: Das Plugin zeigt deutlich, was es
  mitsendet, und es lässt sich pro Prüfung abschalten. Im Archiv sehen nur QS und Auditor
  den Autor, andere Benutzer sehen Plattform und Datum. Die Aufbewahrungsfristen gelten.
- **[E]** Datenschutz: Markierte Texte sind fremde, teils personenbezogene Daten. Geht ein
  Text an einen externen Provider, muss das sichtbar sein, und Datenfluss-Policy und
  Aufbewahrung gelten. Weil Chat- und Plugin-Claims im Archiv landen (Abschnitt 5), gilt
  das dort auch.
- **[E]** Gemeinsamer generierter API-Client und gemeinsame Svelte-Komponenten für
  Weboberfläche und Plugin.

## 9a. Frontend-Design

- **[E]** Das Design soll moderner sein, z. B. so, dass es ein Apple-Produkt sein könnte.
- **[E]** Stil: **klassisch-ruhig mit sparsamen Glas-Effekten**, kein volles Liquid
  Glass.
- **[E]** Erscheinungsbild: **automatisch nach System** (hell/dunkel), umschaltbar.
- **[E]** Markenfarbe und Logo gibt es noch nicht. **[V]** Ich schlage eine ruhige
  Akzentfarbe und ein einfaches Zeichen vor, wenn das Design-System entsteht.
- **[E]** Leitlinien: Zurückhaltung (eine Hauptaktion pro Bildschirm, viel Weißraum),
  Hierarchie durch Typografie, Materialien (Unschärfe, weiche Schatten, große Radien),
  Bewegung mit Bedeutung (Svelte-Transitions, „Bewegung reduzieren“ respektieren), hell
  und dunkel gleichwertig, systemnahe Muster (Seitenleiste, Sheets, Popover, Segmented
  Controls, gruppierte Listen).
- **[E]** Bildschirme:
  - Prüfen: zentriertes Eingabefeld wie Spotlight für Text, Datei, Bild und URL
  - Prüfbericht: große Verdict-Karte mit einem Satz Fazit, aufklappbare Abschnitte; im
    Text sind die Aussagen farbig unterstrichen, die Erklärung öffnet sich seitlich;
    ruhige Schritt-Anzeige
  - Belege als Karten (Publisher, Datum, Note als Abzeichen, Zitat, Bildausschnitt)
  - Archiv der geprüften Claims mit Suche
  - Redaktions-Warteschlange wie Mail (Liste/Detail, Tastenkürzel, Warnzeile)
  - Batch-Upload mit Fortschrittsliste wie beim Kopieren im Finder
  - Verbrauchsübersicht wie die Bildschirmzeit
  - Einstellungen wie die macOS-Systemeinstellungen, keine JSON-Editoren
  - Einrichtung wie beim ersten Start eines Macs, ein Schritt pro Bildschirm
  - Plugin-Popup wie ein iOS-Widget, mit denselben Komponenten
- **[E]** Verdict-Farben: eigene ruhige Palette. Farbe ist nie das einzige Merkmal, Text
  und Symbol stehen immer dabei.
- **[E]** Technik: System-Font-Stack (SF Pro auf Apple-Geräten, Inter als Ersatz; SF Pro
  nicht einbetten, Lizenz), Lucide oder Phosphor statt SF Symbols (Lizenz), Tailwind mit
  Design-Tokens, Bits UI / shadcn-svelte als zugängliche Grundbausteine.
- **[E]** Design-System vor den Seiten (Tokens und etwa zehn Kernkomponenten,
  Vorschau-Seite oder Storybook), gemeinsam für Weboberfläche und Plugin.
- **[E]** Playwright-Screenshots (hell, dunkel, schmal, breit) in jeder Phase. Das
  Aussehen nimmt ein Mensch ab (`[human]`).

## 10. Kritik am alten Plan — was besser werden soll

Aus der Durchsicht von `IMPLEMENT.md`, `NOTES.md` und `docs/FIRST_START_DE.md` des alten
Repositories. Grundsätzlich bestätigt („sehr gute Punkte, für die Implementierung
merken“).

1. **Durchstich statt Schichtbau.** Der alte Plan hat Schicht für Schicht gebaut, und
   der erste echte End-to-End-Lauf kam erst ganz am Ende. Neu: Phase 1 ist ein minimaler
   Durchstich. Ein Claim geht über die API durch echtes LightRAG und ein echtes LLM, über
   Gate und Verdict bis zu einer Antwort. Danach wird verbreitert, zuerst um die
   Text-Eingabe mit Extraktion, dann um die Oberflächen.
2. **Prüfungen müssen in der Umgebung ausführbar sein.** Prüfungen, die Docker, einen
   Browser oder ein Modell brauchen, liefen nie und wurden als „missing“ abgehakt. Neu:
   Die Prüfungen sind als `[agent]` oder `[human]` markiert, bei `[human]` wird gestoppt.
   Die Umgebung hat jetzt Docker, Browser und einen LLM-Key (Abschnitt 1), es gibt also
   keine Ausrede mehr.
3. **Kleinerer Umfang** (Abschnitt 2).
4. **Schlankere Konfiguration.** Bisher gab es 8 + 5 Rollen, eine vom Backend
   gerenderte LightRAG-`.env` mit manuellem Neustart und eine Startanleitung mit 668
   Zeilen. Neu: LightRAG wird statisch über Compose/`.env` konfiguriert und zeigt auf das
   LLM-Gateway, ein Modell für alle Rollen ist Standard, Overrides sind optional.
5. **Ein Vertrag zwischen Frontend und Backend.** Wizard und Login sind an ungeprüften
   Datenformen gescheitert. Neu: Der Client wird aus OpenAPI generiert, und der Typecheck
   bricht bei einer Formänderung.
6. **Worker und Streaming früh entscheiden.** Bisher war das Streaming gepuffert, und kein
   Job lief wirklich. Neu: Die Pipeline läuft als Worker-Job, die Events kommen per
   Redis pub/sub als SSE (Abschnitt 4).
7. **Postgres auch in den Tests** (Testcontainers) und ein fertiges Image mit pgvector + AGE
   statt 20–40 Minuten Kompilierung.
8. **Echte Modelle früh.** Bisher prüfte ein handgeskripteter Mock nur die Verkabelung.
   Neu: aufgezeichnete echte Antworten (Record/Replay), ab Phase 2 eine kleine
   Live-Eval und ein Latenzbudget. Gemessen wurden 108–136 s pro Turn, das Ziel ist
   deutlich weniger (Fast-Modus: 15 s), mit weniger sequenziellen LLM-Calls.
9. **Werkzeuge entweder einsetzen oder streichen.** Testcontainers, Playwright und Docling
   werden eingesetzt. **[E]** Schemathesis nur für die öffentliche `/v1`-Schnittstelle.
   Es erzeugt aus der OpenAPI-Beschreibung automatisch tausende gültige, ungewöhnliche
   und kaputte Anfragen und meldet 500er, Antworten, die nicht zum Schema passen, und
   undokumentierte Statuscodes.
10. **Weniger Doku-Prosa.** `DECISIONS.md` hatte rund 1.100 Zeilen, dazu NOTES, NOTES_DE
    und TODO_START_DE. Neu: eine schlankere Regel, Entscheidungen statt Bugfix-Berichte.

### Was bleibt

- Gate und Verdict als reine Funktionen im Code (das Gate in neuer Form, Abschnitt 3a)
- Deterministische Substanz, die Persona stilisiert nur
- Checked Streaming
- LightRAG als Black Box über `/query/data`, nie Antwortgenerierung
- `file_source = <doc_id>@v<version>`
- Fixture-Korpus in zwei Schichten (synthetisch für CI, real als Manifest für Live-Evals)
- Contracts first
- Die harten Invarianten aus `AGENTS.md`

## 11. Folgen für die Specs

- **PROTOCOL.md:**
  - v1-Teilmenge festlegen, denn §5–§6 (Federation, Dokument-API) wandern nach v2.
  - **§2.1 Gate:** eine Quelle reicht bei freigegebenen Dokumenten. Widersprüche
    (eventuell neues Verdict `contested`), Recency und Audit regeln (Abschnitt 3a).
  - Die Protokoll-Listen „Widersprüche im Korpus“ und „Korpus-Lücken“ als Endpunkte.
  - Tier 3 (Websuche) und Tier 4 aus v1 entfernen.
  - Die Prüf-Schnittstelle für Texte, Dateien und URLs mit Spans, Teilergebnissen und
    Job-Status erweitern (bisher gibt es nur `POST /v1/factcheck` für Claims).
  - Endpunkte für Dokument-Einreichung, Batch, Freigabe, Claim-Archiv und Verbrauch
    ergänzen.
  - Bilder (`image_url`-Teile, Bild-Eingabe) ergänzen.
  - Den Fast-Modus und `preliminary` ergänzen.
  - Den Antwortsprachen-Parameter ergänzen.
  - Den Recherche-Endpunkt `POST /v1/search` und das Modell `factcheck:research`
    ergänzen.
  - `figure_description` als Passagentyp und `relies_on_figure_description` als Hinweis
    ergänzen.
- **PURPOSE.md:**
  - §3.9 „admin only“ durch das Rollenmodell ersetzen.
  - In §3.11 „English interface, English + German corpus“ durch mehrsprachige Ein- und
    Ausgabe und offene Korpussprachen ersetzen.
  - §3.8 Moderation um die Policy für Prüfgegenstände ergänzen (Option a).
  - §3.1a Evidenz-Hierarchie ohne Websuche.
  - Den Kernanwendungsfall Browser-Plugin aufnehmen.
- **PERSONAS.md:** Sprachvarianten für die deterministischen Checks und eventuell eine
  kompakte Plugin-Persona bzw. ein Format.

## 11a. Weitere Punkte aus der Lückenprüfung

1. **[E] Entschiedene Claims bei Korpus-Änderungen:** Claims, deren Grundlage
   zurückgezogen oder geändert wurde, werden automatisch neu geprüft. Bei neuen Dokumenten
   werden passende entschiedene Claims nur neu geprüft, wenn sie häufig gefragt sind,
   innerhalb desselben Tagesbudgets. Jedes Ergebnis ist versioniert.
2. **[E] Archiv und DSGVO:** Claim und Ergebnis bleiben unbegrenzt. Kontextdaten (Autor,
   URL) werden nach einer einstellbaren Frist entfernt (Vorschlag: 90 Tage). QS kann
   einzelne Einträge löschen. Benutzer können eigene Chats löschen, und die geprüften
   Claims bleiben dann anonym im Archiv.
3. **[E] Betrieb:** mitgelieferter Reverse-Proxy (Caddy) mit automatischem HTTPS (Let's
   Encrypt, im LAN ein selbst signiertes Zertifikat). Ein Backup-Befehl sichert Postgres
   und die Originaldateien, die Wiederherstellung wird getestet. Der LightRAG-Index wird
   nicht gesichert, sondern aus den freigegebenen Dokumenten neu aufgebaut.
4. **[E] Ersteinrichtung:** Admin-Konto → Organisation → Provider mit Fähigkeitstest →
   ein Modell für alle Rollen → Moderations-Probe → fertig. LightRAG ist statisch
   konfiguriert und zeigt auf das Gateway, es gibt keinen Neustart und keine gerenderte
   `.env`. Ziel: 15 Minuten bis zum ersten Faktencheck, vom Agenten gemessen.
5. **[E] Personas in v1:** drei Personas plus das kompakte Plugin-Format, die übrigen
   nach und nach.
6. **[E] Smartphones:** Die Weboberfläche ist responsiv und eine PWA mit „Teilen-Ziel“
   (Android: Posts aus jeder App an die Prüfung teilen; iOS über eine Kurzbefehl-Vorlage).
7. **[E] Kontosicherheit:** Wer `users:manage` hat, setzt Passwörter zurück (ohne E-Mail
   in v1). TOTP ist Pflicht für Betreiber-, Redakteurs- und Benutzerverwaltungsrechte,
   sonst optional.
8. **[E] Budget erschöpft:** Cache-Treffer werden weiter ausgeliefert. Neue Prüfungen
   bekommen eine klare Meldung „Budget erschöpft, wieder verfügbar ab …“. Dazu gibt es eine
   globale Monatsobergrenze pro Instanz.
9. **[E] Safari:** Chrome/Edge und Firefox in v1, Safari (Xcode, App Store) in v2.
10. **[E] Alte Daten:** keine Migration aus der alten Installation.

## 12. Offene Fragen

1. Markenfarbe und Logo: Der Agent schlägt sie vor, sobald das Design-System entsteht
   (Abschnitt 9a).

Alle übrigen Vorschläge wurden am 2026-11-16 gesammelt bestätigt (**[E]**).
