# Taktische Sprache -- Syntaxübersicht

Diese Datei dokumentiert die aktuelle Syntax der unterstützten Taktiken
in der **interaktiven taktischen Sprache**. Ziel dieser Sprache ist es,
Programme schrittweise, strukturiert und korrekt zu konstruieren.

------------------------------------------------------------------------

## description

**Syntax:**

``` text
description: # passende_Beschreibung
```

**Beschreibung:**\
Fügt eine textuelle Beschreibung zum Programm hinzu.

**Beispiel:**

``` text
description: # A simple program
```

------------------------------------------------------------------------

## type

**Syntax:**

``` text
type: LiteralName = Literal[LiteralElement, ...]

type: NameDesMixedTypes = PrimitiveType | LiteralType | RecordType | MixedType | ListType | TupleType
```

**Beschreibung:**\
Definiert einen neuen Typ. Unterstützt werden:

-   **LiteralType** (endliche Menge von Konstanten),
-   **MixedType** (Vereinigung mehrerer Typen),
-   Aliase auf bestehende primitive oder benutzerdefinierte Typen,
-   **ListType**,
-   **TupleType**.

Der Typ wird ohne ein separates Schlüsselwort verwendet.

**Beispiel:**

``` text
type: Pet = Literal['cat', 'dog']
```

------------------------------------------------------------------------

## signature

**Syntax:**

``` text
signature: Funktionsname: (Typen) -> Rückgabetyp
```

**Beschreibung:**\
Definiert die Signatur der Hauptfunktion (Name, Parametertypen und
Rückgabetyp).

**Beispiel:**

``` text
signature: main: (int) -> int
```

------------------------------------------------------------------------

## intro

**Syntax:**

``` text
intro: Variablenname
```

**Beschreibung:**\
Führt einen neuen Namen ein:

-   für einen Funktionsparameter (wenn das Name-Loch aus `signature`
    stammt), oder
-   für eine Pattern-Variable (wenn das Loch in einem `data`- oder
    `destruct`-Konstrukt vorkommt), oder
-   für eine Schleifenvariable (z. B. bei List- oder Range-Destruct).

**Beispiel:**

``` text
intro: x
```

------------------------------------------------------------------------

## let

**Syntax:**

``` text
let: Variablenname: Variablentyp
```

**Beschreibung:**\
Deklariert eine neue Variable im aktuellen Scope.

**Beispiel:**

``` text
let: a: int
```

------------------------------------------------------------------------

## fill

**Syntax:**

``` text
fill: Ausdruck_mit_passendem_Typ
```

**Beschreibung:**\
Füllt ein Ausdrucks-Loch mit einem Ausdruck, dessen Typ zum erwarteten
Typ des Lochs passt.

**Beispiel:**

``` text
fill: 3
```

------------------------------------------------------------------------

## switch

**Syntax:**

``` text
switch: <HoleIndex>
```

**Beschreibung:**\
Wechselt zu einem anderen offenen Loch im Programm.

**Beispiel:**

``` text
switch: 1
```

------------------------------------------------------------------------

## data

**Syntax:**

``` text
data: Klassenname(Feld1Name:Feld1Typ, ..., FeldNName:FeldNTyp)
```

**Beschreibung:**\
Definiert einen neuen **Record-Typ** (strukturierter Datentyp mit
benannten Feldern).

**Beispiel:**

``` text
data: Computer(ram: int, processor: int)
```

------------------------------------------------------------------------

## destruct

**Syntax:**

``` text
destruct: Ausdruck
```

Der Ausdruck muss einen der folgenden Typen haben:

-   `BoolType`
-   `LiteralType`
-   `RecordType`
-   `MixedType`
-   `TupleType`
-   `ListType`
-   `RangeType`

**Beschreibung:**\
Zerlegt einen Ausdruck abhängig von seinem Typ:

-   `bool` → `if-else`
-   `LiteralType` → `match-case`
-   `RecordType` → `match-case`
-   `MixedType` → `match-case`
-   `ListType` → `for-Schleife`
-   `RangeType` → `for-Schleife`
-   `TupleType` → Struktur-Destruct / Pattern-Zerlegung

**Beispiel:**

``` text
destruct: x > 1
```

------------------------------------------------------------------------

## return

**Syntax:**

``` text
return:
```

**Beschreibung:**\
Fügt eine Return-Anweisung ein. Der eigentliche Rückgabewert wird
anschließend mit `fill` gesetzt.

**Beispiel:**

``` text
return:
```

------------------------------------------------------------------------

## pass

**Syntax:**

``` text
pass:
```

**Beschreibung:**\
Beendet einen Zweig innerhalb eines `destruct`-Konstrukts ohne weitere
Anweisungen.

`pass` kann verwendet werden, wenn **kein `return` erforderlich ist**.\
Ähnlich wie in Python, wenn ein `if`-, `else`- oder `case`-Zweig nur
Variablendeklarationen enthält oder keinen weiteren Code benötigt.

`pass` ist **nicht erlaubt**, wenn:

-   an dieser Stelle noch Anweisungen notwendig sind, oder
-   dadurch ein sinnvoller `if`-, `else`- oder `case`-Zweig leer bleiben
    würde.

------------------------------------------------------------------------

## nil

**Syntax:**

``` text
nil:
```

**Beschreibung:**\
Schließt ein Listenloch. Nur auf Listenlöchern erlaubt.

**Beispiel:**

``` text
lt1: list[int] = [15, [**]]

nil:

lt1: list[int] = [15]
```

------------------------------------------------------------------------

## cons

**Syntax:**

``` text
cons:
```

**Beschreibung:**\
Erzeugt ein neues Element-Loch in einer Liste. Nur auf Listenlöchern
erlaubt.

**Beispiel:**

``` text
lt1: list[int] = [[**]]

cons:

lt1: list[int] = [[0] [**]]
```

------------------------------------------------------------------------

## new

**Beschreibung:**\
Mit new kann man neue Listen, neue Tuple oder neue Instanzen von
RecordType erstellen.\
Je nach Typ entsteht ein spezielles Loch (z. B. Listenloch bei
list\[T\]).

**Beispiel:**

``` text
new: list[int]
```

------------------------------------------------------------------------

## finish

**Beschreibung:**\
Beendet das Programm, wenn alle Löcher geschlossen sind.

**Beispiel:**

``` text
finish:
```
