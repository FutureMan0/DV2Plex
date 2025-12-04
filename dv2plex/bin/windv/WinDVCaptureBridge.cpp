#define WIN32_LEAN_AND_MEAN

#include "stdafx.h"
#include "WinDVCaptureBridge.h"

#include "DShow.h"

#include <atomic>
#include <ctime>
#include <mutex>
#include <string>
#include <memory>
#include <vector>

using namespace std::string_literals;

namespace
{
    std::wstring AnsiToWide(const CStringA& value)
    {
        if (value.IsEmpty())
        {
            return {};
        }

        int required = MultiByteToWideChar(CP_ACP, 0, value, -1, nullptr, 0);
        if (required <= 0)
        {
            return {};
        }

        std::wstring buffer(static_cast<size_t>(required) - 1, L'\0');
        MultiByteToWideChar(CP_ACP, 0, value, -1, buffer.data(), required);
        return buffer;
    }

    class WinDVCaptureEngine : public CFrameHandler
    {
    public:
        WinDVCaptureEngine();
        ~WinDVCaptureEngine();

        bool Initialize();
        bool SetDevice(const std::wstring& deviceName);
        bool SetPreviewWindow(HWND hwnd);
        bool StartCapture(const WindvCaptureOptions& options);
        void StopCapture();
        bool IsCapturing() const;
        void Shutdown();
        const std::wstring& LastError() const { return m_lastError; }
        void ReportExternalError(const std::wstring& message) { SetError(message); }

        void HandleFrame(REFERENCE_TIME duration, BYTE* data, int len) override;

    private:
        enum class State { Idle = 0, Capturing, Stopping };

        struct NormalizedOptions
        {
            CStringA basePath;
            CStringA datetimeFormat;
            int numericDigits = 0;
            bool type2Avi = true;
            bool enablePreview = true;
            int queueSize = 120;
        };

        static UINT AFX_CDECL CaptureThreadEntry(LPVOID param);
        void CaptureThread();
        void ResetState();
        bool EnsureDirectories(const std::wstring& path);
        NormalizedOptions Normalize(const WindvCaptureOptions& options);
        void SetError(const std::wstring& message);
        std::wstring FormatMessage(const wchar_t* message) const;
        std::wstring FormatMessage(const CString& message) const;

        mutable std::mutex m_mutex;
        std::atomic<State> m_state;
        bool m_comInitialized;

        // Configuration
        CStringW m_deviceWide;
        CStringA m_deviceAnsi;
        HWND m_previewWindow;

        // DirectShow helpers
        CDVInput* m_dvInput;
        CMonitor* m_monitor;
        CDVQueue* m_queue;
        CAVIWriter* m_writer;
        CWinThread* m_captureThread;
        CMediaType m_mediaType;

        NormalizedOptions m_options;

        std::wstring m_lastError;
    };

    WinDVCaptureEngine::WinDVCaptureEngine()
        : m_state(State::Idle),
          m_comInitialized(false),
          m_previewWindow(nullptr),
          m_dvInput(nullptr),
          m_monitor(nullptr),
          m_queue(nullptr),
          m_writer(nullptr),
          m_captureThread(nullptr)
    {
    }

    WinDVCaptureEngine::~WinDVCaptureEngine()
    {
        Shutdown();
    }

    bool WinDVCaptureEngine::Initialize()
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        if (!m_comInitialized)
        {
            HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
            if (FAILED(hr) && hr != RPC_E_CHANGED_MODE)
            {
                SetError(L"CoInitializeEx fehlgeschlagen.");
                return false;
            }
            m_comInitialized = true;
        }
        return true;
    }

    bool WinDVCaptureEngine::SetDevice(const std::wstring& deviceName)
    {
        if (!Initialize())
        {
            return false;
        }

        std::lock_guard<std::mutex> guard(m_mutex);
        if (m_state.load() != State::Idle)
        {
            SetError(L"Gerät kann während einer laufenden Aufnahme nicht geändert werden.");
            return false;
        }

        m_deviceWide = deviceName.c_str();
        m_deviceAnsi = CStringA(m_deviceWide);
        return true;
    }

    bool WinDVCaptureEngine::SetPreviewWindow(HWND hwnd)
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        if (m_state.load() == State::Capturing)
        {
            SetError(L"Preview-Fenster kann während einer laufenden Aufnahme nicht gewechselt werden.");
            return false;
        }
        m_previewWindow = hwnd;
        return true;
    }

    WinDVCaptureEngine::NormalizedOptions WinDVCaptureEngine::Normalize(const WindvCaptureOptions& options)
    {
        NormalizedOptions normalized;
        normalized.enablePreview = options.enable_preview ? true : false;
        normalized.type2Avi = options.type2_avi ? true : false;
        normalized.numericDigits = options.numeric_suffix_digits > 0 ? options.numeric_suffix_digits : 0;
        normalized.queueSize = options.queue_size > 0 ? options.queue_size : 120;

        std::wstring basePath;
        if (options.output_directory && *options.output_directory)
        {
            basePath.assign(options.output_directory);
            if (!basePath.empty() && basePath.back() != L'\\' && basePath.back() != L'/')
            {
                basePath.push_back(L'\\');
            }
        }
        if (options.file_base_name && *options.file_base_name)
        {
            basePath.append(options.file_base_name);
        }
        else
        {
            basePath.append(L"capture");
        }

        normalized.basePath = CStringA(basePath.c_str());

        if (options.datetime_format && *options.datetime_format)
        {
            normalized.datetimeFormat = CStringA(options.datetime_format);
        }
        else
        {
            normalized.datetimeFormat = CStringA("%Y%m%d_%H%M%S");
        }

        return normalized;
    }

    bool WinDVCaptureEngine::EnsureDirectories(const std::wstring& path)
    {
        if (path.empty())
        {
            return true;
        }

        size_t pos = path.find_last_of(L"\\/");
        if (pos == std::wstring::npos)
        {
            return true;
        }

        std::wstring directory = path.substr(0, pos);
        if (directory.empty())
        {
            return true;
        }

        DWORD attrs = GetFileAttributesW(directory.c_str());
        if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY))
        {
            return true;
        }

        if (!EnsureDirectories(directory))
        {
            return false;
        }

        if (CreateDirectoryW(directory.c_str(), nullptr))
        {
            return true;
        }

        if (GetLastError() == ERROR_ALREADY_EXISTS)
        {
            return true;
        }

        SetError(L"Verzeichnis konnte nicht erstellt werden.");
        return false;
    }

    bool WinDVCaptureEngine::StartCapture(const WindvCaptureOptions& options)
    {
        if (m_deviceAnsi.IsEmpty())
        {
            SetError(L"Kein DirectShow-Gerät konfiguriert.");
            return false;
        }

        if (!Initialize())
        {
            return false;
        }

        auto normalized = Normalize(options);

        if (!EnsureDirectories(AnsiToWide(normalized.basePath)))
        {
            return false;
        }

        std::lock_guard<std::mutex> guard(m_mutex);
        if (m_state.load() != State::Idle)
        {
            SetError(L"Aufnahme läuft bereits.");
            return false;
        }

        try
        {
            m_dvInput = new CDVInput(m_deviceAnsi);
            m_dvInput->GetMediaType(&m_mediaType);

            int sampleSize = static_cast<int>(m_mediaType.GetSampleSize());
            if (sampleSize < 144000)
            {
                m_mediaType.SetSampleSize(144000);
                sampleSize = 144000;
            }

            m_queue = new CDVQueue(normalized.queueSize, sampleSize);

            if (normalized.enablePreview && m_previewWindow != nullptr)
            {
                m_monitor = new CMonitor(m_previewWindow, &m_mediaType);
            }

            m_writer = new CAVIWriter(
                normalized.basePath,
                normalized.datetimeFormat,
                normalized.numericDigits,
                std::time(nullptr),
                normalized.type2Avi,
                &m_mediaType);

            m_options = normalized;

            m_dvInput->Run(this);

            m_state.store(State::Capturing);
            m_captureThread = AfxBeginThread(CaptureThreadEntry, this, THREAD_PRIORITY_NORMAL, 0, CREATE_SUSPENDED);
            if (!m_captureThread)
            {
                SetError(L"Capture-Thread konnte nicht gestartet werden.");
                StopCapture();
                return false;
            }
            m_captureThread->m_bAutoDelete = FALSE;
            m_captureThread->ResumeThread();
        }
        catch (CDShowException* ex)
        {
            SetError(FormatMessage(ex->m_message));
            ex->Delete();
            StopCapture();
            return false;
        }
        catch (CException* ex)
        {
            TCHAR buffer[512]{0};
            ex->GetErrorMessage(buffer, _countof(buffer));
            ex->Delete();
            CStringW wide(buffer);
            SetError(std::wstring(wide));
            StopCapture();
            return false;
        }
        catch (...)
        {
            SetError(L"Unbekannter Fehler beim Starten der Aufnahme.");
            StopCapture();
            return false;
        }

        return true;
    }

    void WinDVCaptureEngine::StopCapture()
    {
        std::unique_lock<std::mutex> guard(m_mutex);
        if (m_state.load() == State::Idle)
        {
            return;
        }

        m_state.store(State::Stopping);

        if (m_queue)
        {
            m_queue->Put(-1, nullptr, 0);
        }

        guard.unlock();

        if (m_captureThread)
        {
            WaitForSingleObject(m_captureThread->m_hThread, INFINITE);
            delete m_captureThread;
            m_captureThread = nullptr;
        }

        guard.lock();
        if (m_dvInput)
        {
            m_dvInput->Stop();
            delete m_dvInput;
            m_dvInput = nullptr;
        }

        if (m_monitor)
        {
            delete m_monitor;
            m_monitor = nullptr;
        }

        if (m_writer)
        {
            delete m_writer;
            m_writer = nullptr;
        }

        if (m_queue)
        {
            delete m_queue;
            m_queue = nullptr;
        }

        m_state.store(State::Idle);
    }

    bool WinDVCaptureEngine::IsCapturing() const
    {
        return m_state.load() == State::Capturing;
    }

    void WinDVCaptureEngine::Shutdown()
    {
        StopCapture();
        std::lock_guard<std::mutex> guard(m_mutex);
        if (m_comInitialized)
        {
            CoUninitialize();
            m_comInitialized = false;
        }
    }

    void WinDVCaptureEngine::HandleFrame(REFERENCE_TIME duration, BYTE* data, int len)
    {
        if (!m_queue)
        {
            return;
        }
        m_queue->Put(duration, data, len);
    }

    UINT AFX_CDECL WinDVCaptureEngine::CaptureThreadEntry(LPVOID param)
    {
        auto* engine = reinterpret_cast<WinDVCaptureEngine*>(param);
        if (engine)
        {
            engine->CaptureThread();
        }
        return 0;
    }

    void WinDVCaptureEngine::CaptureThread()
    {
        BYTE* buffer = nullptr;
        REFERENCE_TIME duration = 0;
        int len = 0;

        while (m_state.load() == State::Capturing)
        {
            if (!m_queue->Get(&duration, &buffer, &len))
            {
                continue;
            }

            if (!buffer)
            {
                break;
            }

            if (m_monitor && m_options.enablePreview)
            {
                if (m_queue->m_load < (m_options.queueSize / 2))
                {
                    m_monitor->HandleFrame(duration, buffer, len);
                }
            }

            if (m_writer)
            {
                m_writer->HandleFrame(duration, buffer, len);
            }
        }
    }

    void WinDVCaptureEngine::SetError(const std::wstring& message)
    {
        std::lock_guard<std::mutex> guard(m_mutex);
        m_lastError = message;
    }

    std::wstring WinDVCaptureEngine::FormatMessage(const wchar_t* message) const
    {
        if (!message)
        {
            return {};
        }
        return std::wstring(message);
    }

    std::wstring WinDVCaptureEngine::FormatMessage(const CString& message) const
    {
        CStringW wide(message);
        return std::wstring(wide);
    }

    std::unique_ptr<WinDVCaptureEngine> g_engine;
    std::mutex g_engineMutex;

    WinDVCaptureEngine* EnsureEngine()
    {
        std::lock_guard<std::mutex> guard(g_engineMutex);
        if (!g_engine)
        {
            g_engine = std::make_unique<WinDVCaptureEngine>();
        }
        return g_engine.get();
    }
} // namespace

extern "C"
{

    int WindvBridge_Initialize()
    {
        auto* engine = EnsureEngine();
        return engine->Initialize() ? 0 : -1;
    }

    int WindvBridge_SetDevice(const wchar_t* device_name)
    {
        auto* engine = EnsureEngine();
        if (!device_name)
        {
            engine->ReportExternalError(L"Device-Name darf nicht leer sein.");
            return -1;
        }
        return engine->SetDevice(device_name) ? 0 : -1;
    }

    int WindvBridge_SetPreviewWindow(HWND hwnd)
    {
        auto* engine = EnsureEngine();
        return engine->SetPreviewWindow(hwnd) ? 0 : -1;
    }

    int WindvBridge_StartCapture(const WindvCaptureOptions* options)
    {
        if (!options)
        {
            return -1;
        }
        auto* engine = EnsureEngine();
        return engine->StartCapture(*options) ? 0 : -1;
    }

    void WindvBridge_StopCapture()
    {
        auto* engine = EnsureEngine();
        engine->StopCapture();
    }

    int WindvBridge_IsCapturing()
    {
        auto* engine = EnsureEngine();
        return engine->IsCapturing() ? 1 : 0;
    }

    const wchar_t* WindvBridge_LastError()
    {
        auto* engine = EnsureEngine();
        return engine->LastError().c_str();
    }

    void WindvBridge_Shutdown()
    {
        auto* engine = EnsureEngine();
        engine->Shutdown();
    }

} // extern "C"

