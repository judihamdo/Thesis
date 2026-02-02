# Taktische Sprache – Syntaxübersicht

Diese Datei dokumentiert die aktuelle Syntax der unterstützten Taktiken in der **interaktiven taktischen Sprache**. Ziel dieser Sprache ist es, Programme schrittweise, strukturiert und korrekt zu konstruieren.

---

## description

**Syntax:**

```text
description: # passende_Beschreibung
```

**Beschreibung:**\
Fügt eine textuelle Beschreibung zum Programm hinzu.

**Beispiel:**

```text
description: # A simple program
```

---

## type

**Syntax:**

```text
type: LiteralName = Literal[LiteralElement, ...]

type: NameDesMixedTypes = PrimitiveType | LiteralType | RecordType | MixedType
```

**Beschreibung:**\
Definiert einen neuen Typ. Unterstützt werden:

- **LiteralType** (endliche Menge von Konstanten),
- **MixedType** (Vereinigung mehrerer Typen),
- Aliase auf bestehende primitive oder benutzerdefinierte Typen.

Der Typ wird ohne ein separates Schlüsselwort verwendet.

**Beispiel:**

```text
type: Pet = Literal['cat', 'dog']
```

---

## signature

**Syntax:**

```text
signature: Funktionsname: (Typen) -> Rückgabetyp
```

**Beschreibung:**  
Definiert die Signatur der Hauptfunktion (Name, Parametertypen und Rückgabetyp).

**Beispiel:**

```text
signature: main: (int) -> int
```

---

## intro

**Syntax:**

```text
intro: Variablenname
```

**Beschreibung:**\
Führt einen neuen Namen ein:

- für einen Funktionsparameter (wenn das Name-Loch aus `signature` stammt), oder
- für eine Pattern-Variable (wenn das Loch in einem `data`- oder `destruct`-Konstrukt vorkommt).

**Beispiel:**

```text
intro: x
```

---

## let

**Syntax:**

```text
let: Variablenname: Variablentyp
```

**Beschreibung:**\
Deklariert eine neue Variable im aktuellen Scope.

**Beispiel:**

```text
let: a: int
```

---

## fill

**Syntax:**

```text
fill: Ausdruck_mit_passendem_Typ
```

**Beschreibung:**\
Füllt ein Ausdrucks-Loch mit einem Ausdruck, dessen Typ zum erwarteten Typ des Lochs passt.

**Beispiel:**

```text
fill: 3
```

---

## switch

**Syntax:**

```text
switch: <HoleIndex>
```

**Beschreibung:**\
Wechselt zu einem anderen offenen Loch im Programm.

**Beispiel:**

```text
switch: 1
```

---

## data

**Syntax:**

```text
data: Klassenname(Feld1Name:Feld1Typ, ..., FeldNName:FeldNTyp)
```

**Beschreibung:**\
Definiert einen neuen **Record-Typ** (strukturierter Datentyp mit benannten Feldern).

**Beispiel:**

```text
data: Computer(ram: int, processor: int)
```

---

## destruct

**Syntax:**

```text
destruct: Ausdruck
```

Der Ausdruck muss einen der folgenden Typen haben:

- `BoolType`
- `LiteralType`
- `RecordType`
- `MixedType`

**Beschreibung:**\
Zerlegt einen Ausdruck abhängig von seinem Typ:

- `bool` → `if-then-else`
- `LiteralType` → `match-case`
- `RecordType` → `match-case`
- `MixedType` → `match-case`

**Beispiel:**

```text
destruct: x > 1
```

---

## return

**Syntax:**

```text
return:
```

**Beschreibung:**\
Fügt eine Return-Anweisung ein. Der eigentliche Rückgabewert wird anschließend mit `fill` gesetzt.

**Beispiel:**

```text
return:
```

---

## pass

**Syntax:**

```text
pass:
```

**Beschreibung:**\
Beendet einen Zweig innerhalb eines `destruct`-Konstrukts ohne weitere Anweisungen.

`pass` kann verwendet werden, wenn **kein `return` erforderlich ist**.\
Ähnlich wie in Python, wenn ein `if`-, `else`- oder `case`-Zweig nur Variablendeklarationen enthält oder keinen weiteren Code benötigt.

`pass` ist **nicht erlaubt**, wenn:

- an dieser Stelle noch Anweisungen notwendig sind, oder
- dadurch ein sinnvoller `if`-, `else`- oder `case`-Zweig leer bleiben würde.

### Beispiel:

```text
def random_function(x: int) -> float:
    n: int = x * 100
    if (x > 1):
        f = 0.1
    else:
        if (x < -100):
            return n + 100
        else:
            f2 = 0.0
        [0*]
    [1]
```

**Optionen für Loch 0:** `pass`, `destruct`, `return`, `let`

In diesem Beispiel kann im inneren `else`-Zweig selbst entschieden werden, ob das Loch mit weiterem Code gefüllt oder mit `pass` beendet wird.

Falls **alle möglichen Ausführungspfade bereits sicher mit einem `return` enden**, werden entsprechende Löcher automatisch erkannt und geschlossen; `pass` ist dann nicht mehr möglich.

---

## finish

**Beschreibung:**\
Beendet das Programm, wenn alle Löcher geschlossen sind.

**Beispiel:**

```text
finish:
```

