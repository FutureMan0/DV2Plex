#include "stdafx.h"

// Einige Builds verwenden DumpGraph nur für Debugzwecke.
// Sollte die DirectShow-Hilfsfunktion nicht verfügbar sein, stellen wir hier
// eine leere Implementierung bereit, um Link-Fehler zu vermeiden.

extern "C" void DumpGraph(IFilterGraph* pGraph, DWORD level)
{
	UNREFERENCED_PARAMETER(pGraph);
	UNREFERENCED_PARAMETER(level);
}


