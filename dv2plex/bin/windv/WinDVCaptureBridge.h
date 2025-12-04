#pragma once

#include <Windows.h>

#ifdef WINDV_CAPTURE_BUILD
#define WINDV_CAPTURE_API __declspec(dllexport)
#else
#define WINDV_CAPTURE_API __declspec(dllimport)
#endif

extern "C" {

/**
 * Optionen für den Capture-Befehl.
 *
 * Alle Pfade werden als Wide-Strings (UTF-16) erwartet.
 * - output_directory: Zielordner (muss existieren oder wird erstellt)
 * - file_base_name: Basisdateiname ohne Erweiterung (z. B. "part_001")
 * - datetime_format: Optionales Format (strftime Syntax), kann NULL sein
 * - numeric_suffix_digits: Anzahl führender Nullen für den Auto-Counter
 * - type2_avi: TRUE → Type-2 AVI schreiben (Video + Audio getrennt)
 * - enable_preview: TRUE → DirectShow Preview aktiv lassen (HWND erforderlich)
 * - queue_size: Größe der DV-Frame Queue (Standard 120)
 */
struct WindvCaptureOptions {
    const wchar_t* output_directory;
    const wchar_t* file_base_name;
    const wchar_t* datetime_format;
    int numeric_suffix_digits;
    BOOL type2_avi;
    BOOL enable_preview;
    int queue_size;
};

WINDV_CAPTURE_API int WindvBridge_Initialize();
WINDV_CAPTURE_API int WindvBridge_SetDevice(const wchar_t* device_name);
WINDV_CAPTURE_API int WindvBridge_SetPreviewWindow(HWND hwnd);
WINDV_CAPTURE_API int WindvBridge_StartCapture(const WindvCaptureOptions* options);
WINDV_CAPTURE_API void WindvBridge_StopCapture();
WINDV_CAPTURE_API int WindvBridge_IsCapturing();
WINDV_CAPTURE_API const wchar_t* WindvBridge_LastError();
WINDV_CAPTURE_API void WindvBridge_Shutdown();

} // extern "C"



